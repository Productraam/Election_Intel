"""
Election Intelligence - Flask Application
Full API backend with Auth, Database, PWA, and WhatsApp integration.
"""

import os
import io
import json
import re
from datetime import datetime, timezone

# Load .env file if present (for local dev / bare-metal deploys).
# Must happen before any os.environ.get() calls.
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'), override=False)
except ImportError:
    pass  # python-dotenv not installed; rely on real env vars

from flask import Flask, request, jsonify, render_template, send_file, g
from werkzeug.security import generate_password_hash, check_password_hash
from voter_parser import VoterListParser
from analytics import ElectionAnalytics
from database import db, init_db, User, Ward, Voter, ElectionHistory, AuditLog, Contact, WhatsAppCampaign, WhatsAppMessage, WardUploadHistory, TagDefinition, MessageTemplate, WorkAssignment
from auth import create_token, require_auth, require_role, get_user_id, decode_token, optional_auth, restrict_voters_for, voter_in_scope

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
app.config['SECRET_KEY'] = os.environ.get('EI_SECRET_KEY', 'election-intel-secret-2026')

# Initialize database
init_db(app)

SAVE_DIR = os.path.join(os.path.dirname(__file__), 'saved_wards')
os.makedirs(SAVE_DIR, exist_ok=True)

# In-memory store for current session (loaded from DB)
STORE = {
    'voters': [],
    'metadata': {},
    'filename': None,
    'upload_time': None,
    'election_history': [],
    'ward_id': None,       # current DB ward id
    'ward_ids': [],        # multiple ward ids when aggregated
    'source': None,        # 'upload' (fresh parse) | 'edited' | 'loaded'
}


def get_analytics():
    """Return an analytics instance scoped to the current authenticated
    user (karyakarta sees only their assigned pages, booth_agent only their
    assigned booths). Unauthenticated/unscoped roles see all voters."""
    voters = restrict_voters_for(STORE['voters'])
    return ElectionAnalytics(voters, STORE['metadata'])


def _scoped_voters():
    """Voters visible to the current user (or all voters if unscoped)."""
    return restrict_voters_for(STORE['voters'])


def _log_audit(action, voter_nqt_id='', field='', old_val='', new_val='', ward_id=None):
    """Log an audit entry if auth is active."""
    try:
        entry = AuditLog(
            user_id=getattr(g, 'user_id', None),
            ward_id=ward_id or STORE.get('ward_id'),
            voter_nqt_id=str(voter_nqt_id)[:40],
            action=str(action)[:40],
            field_name=str(field)[:40],
            old_value=str(old_val)[:500],
            new_value=str(new_val)[:500],
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _optional_auth():
    """Try to authenticate from header but don't require it."""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        payload = decode_token(auth_header[7:])
        if payload:
            g.user_id = payload['user_id']
            g.username = payload['username']
            g.role = payload['role']


@app.before_request
def _attach_user_context():
    """Decode bearer token on every request so role-based scoping works
    even on legacy endpoints that lack an explicit @require_auth."""
    _optional_auth()


# ─── Pages ──────────────────────────────────────────────────────────

@app.before_request
def before_req():
    _optional_auth()

@app.route('/')
def index():
    return render_template('dashboard.html')


# ─── Upload & Parse ─────────────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400

    fname = f.filename.lower()
    max_pages = request.form.get('max_pages', type=int) or None
    parser = VoterListParser()

    try:
        if fname.endswith('.pdf'):
            stream = io.BytesIO(f.read())
            parser.parse_pdf_stream(stream, max_pages=max_pages)
        elif fname.endswith('.csv'):
            parser.parse_csv_stream(f.stream)
        elif fname.endswith('.txt'):
            parser.parse_text_stream(f.stream)
        else:
            return jsonify({'error': 'Unsupported format. Use PDF, CSV, or TXT'}), 400
    except Exception as e:
        return jsonify({'error': f'Parse error: {str(e)}'}), 400

    if not parser.voters:
        return jsonify({'error': 'No voters found in file. Check file format.'}), 400

    STORE['voters'] = parser.voters
    STORE['metadata'] = parser.metadata
    STORE['filename'] = f.filename
    STORE['upload_time'] = datetime.now().isoformat()
    STORE['source'] = 'upload'

    return jsonify({
        'success': True,
        'filename': f.filename,
        'total_voters': len(parser.voters),
        'metadata': parser.metadata
    })


@app.route('/api/upload/analysis')
def upload_analysis():
    """Post-upload EPIC analysis. Compares the currently-loaded STORE
    against every saved ward and classifies each voter into:
      - new          : EPIC not seen anywhere (or no EPIC present)
      - in_this_ward : EPIC already present in the ward whose name we
                       matched against (if any). Used for re-upload.
      - in_other_ward: EPIC currently lives in a DIFFERENT saved ward.
    The response powers the post-upload preview modal so the user can
    decide whether to save as a new ward or merge into an existing one
    (in which case the existing save-ward flow moves EPICs across wards).
    """
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400

    # Build EPIC -> ward_safe_name index from saved snapshots
    epic_to_ward = {}      # epic_upper -> safe_name
    ward_voter_counts = {} # safe_name -> total voters in that ward
    ward_display_names = {}  # safe_name -> human ward_name (from JSON)
    try:
        for fn in sorted(os.listdir(SAVE_DIR)):
            if not fn.endswith('.json'):
                continue
            safe = fn[:-5]
            try:
                with open(os.path.join(SAVE_DIR, fn), 'r', encoding='utf-8') as f:
                    d = json.load(f)
            except Exception:
                continue
            ward_display_names[safe] = d.get('ward_name') or safe
            voters = d.get('voters', [])
            ward_voter_counts[safe] = len(voters)
            for ov in voters:
                e = (ov.get('voter_id') or '').strip().upper()
                if e and e not in epic_to_ward:  # first wins
                    epic_to_ward[e] = safe
    except Exception:
        pass

    new_count = 0
    no_epic_count = 0
    by_other_ward = {}   # safe_name -> {'ward_name', 'count', 'samples':[{nqt_id, name, voter_id}, ...]}
    new_samples = []     # up to N samples of new EPICs

    SAMPLE_LIMIT = 5
    for v in STORE['voters']:
        e = (v.get('voter_id') or '').strip().upper()
        if not e:
            no_epic_count += 1
            continue
        target = epic_to_ward.get(e)
        if target:
            bucket = by_other_ward.setdefault(target, {
                'ward_safe_name': target,
                'ward_name': ward_display_names.get(target, target),
                'count': 0,
                'samples': [],
            })
            bucket['count'] += 1
            if len(bucket['samples']) < SAMPLE_LIMIT:
                bucket['samples'].append({
                    'nqt_id': v.get('nqt_id') or '',
                    'name': v.get('name') or '',
                    'voter_id': v.get('voter_id') or '',
                })
        else:
            new_count += 1
            if len(new_samples) < SAMPLE_LIMIT:
                new_samples.append({
                    'nqt_id': v.get('nqt_id') or '',
                    'name': v.get('name') or '',
                    'voter_id': v.get('voter_id') or '',
                })

    existing_total = sum(b['count'] for b in by_other_ward.values())
    existing_wards = sorted(by_other_ward.values(), key=lambda b: -b['count'])

    # Saved-ward list (for the "merge into existing ward" dropdown)
    saved_wards = [
        {'safe_name': s, 'name': ward_display_names[s], 'voter_count': ward_voter_counts.get(s, 0)}
        for s in sorted(ward_display_names)
    ]

    return jsonify({
        'filename': STORE.get('filename') or '',
        'metadata': STORE.get('metadata') or {},
        'total_voters': len(STORE['voters']),
        'with_epic': len(STORE['voters']) - no_epic_count,
        'without_epic': no_epic_count,
        'new_epics': new_count,
        'existing_epics': existing_total,
        'existing_by_ward': existing_wards,
        'new_samples': new_samples,
        'saved_wards': saved_wards,
    })


@app.route('/api/status')
def status():
    return jsonify({
        'loaded': len(STORE['voters']) > 0,
        'filename': STORE['filename'],
        'total_voters': len(STORE['voters']),
        'upload_time': STORE['upload_time'],
        'metadata': STORE['metadata']
    })


@app.route('/api/details')
def details():
    """Return full PDF page-1 metadata, file info, and booth list."""
    meta = STORE.get('metadata', {})
    # Unique booth/part numbers from voter data
    booths = sorted(set(
        str(v.get('part_no', '')) for v in STORE['voters'] if v.get('part_no')
    ))
    return jsonify({
        'filename': STORE.get('filename'),
        'upload_time': STORE.get('upload_time'),
        'metadata': meta,
        'booths': booths,
        'parsed_voter_count': len(STORE['voters']),
    })


@app.route('/api/debug-pdf', methods=['POST'])
def debug_pdf():
    """Debug endpoint: show raw text/tables extracted from PDF"""
    import pdfplumber

    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    stream = io.BytesIO(f.read())

    pages_text = []
    pages_tables = []
    with pdfplumber.open(stream) as pdf:
        for i, page in enumerate(pdf.pages[:5]):  # First 5 pages
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            pages_text.append({'page': i + 1, 'text': text[:3000], 'chars': len(text)})
            for t_idx, table in enumerate(tables):
                pages_tables.append({
                    'page': i + 1, 'table_idx': t_idx,
                    'rows': len(table),
                    'sample_rows': table[:5]
                })

    return jsonify({
        'total_pages': len(pages_text),
        'pages_text': pages_text,
        'tables': pages_tables
    })


# ─── Analytics APIs ─────────────────────────────────────────────────

@app.route('/api/summary')
def summary():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    # Honor the same filters the voter list uses, so dashboard KPIs can
    # reflect the active filter set.
    voters = _scoped_voters()
    search = request.args.get('search', '').strip().lower()
    booth = request.args.get('booth', '')
    classification = request.args.get('classification', '')
    tag_filter = request.args.get('tag', '').strip()
    sentiment_f = request.args.get('sentiment', '').strip().lower()
    party_f = request.args.get('party_lean', '').strip().lower()
    if search:
        voters = [v for v in voters if search in v['name'].lower() or search in v.get('voter_id', '').lower() or search in v.get('nqt_id', '').lower()]
    if booth:
        voters = [v for v in voters if str(v.get('part_no', '')) == booth]
    if classification:
        voters = [v for v in voters if (v.get('classification') or '').lower() == classification.lower()]
    if tag_filter:
        voters = [v for v in voters if tag_filter in (v.get('tags') or [])]
    if sentiment_f:
        voters = [v for v in voters if (v.get('sentiment') or '').lower() == sentiment_f]
    if party_f:
        voters = [v for v in voters if (v.get('party_lean') or '').lower() == party_f]
    return jsonify(ElectionAnalytics(voters, STORE['metadata']).get_summary())


@app.route('/api/gender-by-age')
def gender_by_age():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_gender_by_age())


@app.route('/api/community')
def community():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_community_analysis())


@app.route('/api/surnames')
def surnames():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_surname_analysis())


@app.route('/api/families')
def families():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_family_analysis())


@app.route('/api/booth-analysis')
def booth_analysis():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_booth_analysis())


@app.route('/api/booth-strength')
def booth_strength():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_booth_strength())


@app.route('/api/winning-formula')
def winning_formula():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_winning_formula(STORE.get('election_history')))


@app.route('/api/data-quality')
def data_quality():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_data_quality())


# ─── Phase 2: Field Ops ─────────────────────────────────────────────

@app.route('/api/panna-pramukh')
def panna_pramukh():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_panna_pramukh_plan())


@app.route('/api/contact-coverage')
def contact_coverage():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_contact_coverage())


@app.route('/api/sentiment')
def sentiment():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_sentiment_analysis())


@app.route('/api/slip-status')
def slip_status():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_slip_distribution_status())


# ─── Phase 3: Election Day ──────────────────────────────────────────

@app.route('/api/polling-day')
def polling_day():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_polling_day_tracker())


@app.route('/api/turnout-prediction')
def turnout_prediction():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_turnout_prediction())


@app.route('/api/volunteer-needs')
def volunteer_needs():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_volunteer_requirement())


@app.route('/api/vote-simulator', methods=['POST'])
def vote_simulator():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    data = request.json or {}
    return jsonify(get_analytics().get_vote_share_simulator(
        pakka_pct=data.get('pakka_pct', 100),
        swing_capture_pct=data.get('swing_capture_pct', 50),
        first_time_pct=data.get('first_time_pct', 60)
    ))


# ─── Strategy APIs ──────────────────────────────────────────────────

@app.route('/api/conversion-funnel')
def conversion_funnel():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_conversion_funnel())


@app.route('/api/three-contact-plan')
def three_contact_plan():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_three_contact_plan())


@app.route('/api/family-influence')
def family_influence():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_family_influence_map())


@app.route('/api/election-day-slots')
def election_day_slots():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_election_day_slots())


@app.route('/api/caste-strategy')
def caste_strategy():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_caste_strategy())


@app.route('/api/family-tree')
def family_tree():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_family_tree())


# ─── Tags & Scheme Coverage ─────────────────────────────────────────

@app.route('/api/tags/summary')
def tag_summary():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_tag_analysis())


@app.route('/api/scheme-coverage')
def scheme_coverage():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_scheme_coverage())


@app.route('/api/party-lean')
def party_lean():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    return jsonify(get_analytics().get_party_lean_analysis())


@app.route('/api/bulk-tag', methods=['POST'])
def bulk_tag():
    """Add or remove a tag from multiple voters."""
    data = request.json
    if not data or 'nqt_ids' not in data or 'tag' not in data:
        return jsonify({'error': 'Provide nqt_ids and tag'}), 400

    tag = str(data['tag']).strip()[:50]
    action = data.get('action', 'add')  # 'add' or 'remove'
    nqt_ids = set(data['nqt_ids'])
    count = 0

    for voter in STORE['voters']:
        if voter.get('nqt_id') in nqt_ids:
            tags = voter.get('tags') or []
            if action == 'add' and tag not in tags:
                tags.append(tag)
                count += 1
            elif action == 'remove' and tag in tags:
                tags.remove(tag)
                count += 1
            voter['tags'] = tags

    return jsonify({'success': True, 'updated': count, 'tag': tag, 'action': action})


# ─── Election History ───────────────────────────────────────────────

@app.route('/api/history', methods=['GET'])
def get_history():
    """Get election history for currently loaded ward."""
    return jsonify({
        'election_history': STORE.get('election_history', []),
        'analysis': ElectionAnalytics.get_historical_analysis(STORE.get('election_history', [])),
    })


@app.route('/api/history', methods=['POST'])
def add_history():
    """Add an election result entry."""
    data = request.json
    if not data:
        return jsonify({'error': 'No data'}), 400

    # Validate
    year = data.get('year')
    election_type = data.get('election_type', '').strip()
    parties = data.get('parties', [])
    if not year or not election_type:
        return jsonify({'error': 'Year and election_type required'}), 400

    # Sanitize parties
    clean_parties = []
    total_votes = 0
    for p in parties:
        name = str(p.get('name', '')).strip()
        votes = int(p.get('votes', 0) or 0)
        if name and votes >= 0:
            clean_parties.append({
                'name': name,
                'votes': votes,
                'candidate': str(p.get('candidate', '')).strip()[:100],
            })
            total_votes += votes

    entry = {
        'year': int(year),
        'election_type': election_type[:50],
        'parties': clean_parties,
        'total_votes': data.get('total_votes', total_votes) or total_votes,
        'turnout_pct': float(data.get('turnout_pct', 0) or 0),
        'winner': str(data.get('winner', '')).strip()[:50],
    }

    if 'election_history' not in STORE:
        STORE['election_history'] = []
    STORE['election_history'].append(entry)

    # Persist to saved ward file if one is loaded
    _persist_history()

    return jsonify({'success': True, 'total_entries': len(STORE['election_history'])})


@app.route('/api/history/<int:index>', methods=['DELETE'])
def delete_history(index):
    """Delete an election history entry by index."""
    history = STORE.get('election_history', [])
    if index < 0 or index >= len(history):
        return jsonify({'error': 'Invalid index'}), 400
    history.pop(index)
    _persist_history()
    return jsonify({'success': True, 'total_entries': len(history)})


def _persist_history():
    """Save election history back to the ward JSON file if applicable."""
    fname = STORE.get('filename', '')
    if not fname:
        return
    # Try to find the saved ward file
    safe_name = _safe_ward_filename(fname.replace('.pdf', '').replace('.csv', '').replace('.txt', ''))
    for f in os.listdir(SAVE_DIR):
        if f.endswith('.json'):
            fpath = os.path.join(SAVE_DIR, f)
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if data.get('ward_name', '') == fname or f[:-5] == safe_name:
                    data['election_history'] = STORE.get('election_history', [])
                    with open(fpath, 'w', encoding='utf-8') as fh:
                        json.dump(data, fh, ensure_ascii=False)
                    return
            except Exception:
                pass


# ─── Hierarchy ──────────────────────────────────────────────────────

@app.route('/api/hierarchy')
def get_hierarchy():
    from hierarchy import build_tree
    return jsonify(build_tree())


@app.route('/api/hierarchy/load', methods=['POST'])
def load_hierarchy_level():
    """Load aggregated data for any hierarchy level."""
    from hierarchy import find_ward_files, load_combined_voters, get_all_wards
    data = request.json or {}
    level = data.get('level', '')
    value = data.get('value', '')
    path = data.get('path', {})

    if level == 'root':
        ward_files = [w['file'] for w in get_all_wards()]
    elif level == 'ward':
        ward_files = [value]
    else:
        ward_files = find_ward_files(level, value, path)

    if not ward_files:
        return jsonify({'error': 'No wards found at this level'}), 404

    voters, meta, history = load_combined_voters(ward_files)
    if not voters:
        return jsonify({'error': 'No voter data found'}), 404

    STORE['voters'] = voters
    STORE['metadata'] = meta
    STORE['election_history'] = history
    STORE['filename'] = f"{value} ({len(ward_files)} wards)" if level != 'ward' else value
    STORE['upload_time'] = datetime.now().isoformat()

    return jsonify({
        'success': True,
        'level': level,
        'level_label': data.get('level_label', level),
        'value': value,
        'ward_count': len(ward_files),
        'total_voters': len(voters),
        'wards': ward_files,
        'metadata': meta,
    })


# ─── PDF Report ─────────────────────────────────────────────────────

@app.route('/api/report/pdf')
def download_report():
    """Generate and download comprehensive PDF report"""
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    from report_generator import generate_report
    meta = dict(STORE['metadata'])
    meta['_election_history'] = STORE.get('election_history', [])
    pdf_buf = generate_report(STORE['voters'], meta)
    ward = STORE['metadata'].get('assembly', 'Ward') or 'Ward'
    ward = re.sub(r'[^\w\s-]', '', ward)[:40].strip()
    fname = f"Election_Intel_{ward}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(
        pdf_buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=fname
    )


# ─── Voter CRUD ─────────────────────────────────────────────────────

@app.route('/api/voters')
def get_voters():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 200)
    search = request.args.get('search', '').strip().lower()
    booth = request.args.get('booth', '')
    classification = request.args.get('classification', '')
    tag_filter = request.args.get('tag', '').strip()
    sentiment_f = request.args.get('sentiment', '').strip().lower()
    party_f = request.args.get('party_lean', '').strip().lower()
    consent_f = request.args.get('whatsapp_consent', '').strip().lower()
    page_no_f = request.args.get('page_no', '').strip()
    custom_filters = {k[7:]: v for k, v in request.args.items() if k.startswith('custom:') and v}

    voters = _scoped_voters()
    if search:
        voters = [v for v in voters if search in v['name'].lower() or search in v.get('voter_id', '').lower()
                  or search in v.get('nqt_id', '').lower()]
    if booth:
        voters = [v for v in voters if str(v.get('part_no', '')) == booth]
    if classification:
        voters = [v for v in voters if v.get('classification', '').lower() == classification.lower()]
    if tag_filter:
        voters = [v for v in voters if tag_filter in (v.get('tags') or [])]
    if sentiment_f:
        voters = [v for v in voters if (v.get('sentiment') or '').lower() == sentiment_f]
    if party_f:
        voters = [v for v in voters if (v.get('party_lean') or '').lower() == party_f]
    if consent_f in ('1', 'true', 'yes'):
        voters = [v for v in voters if v.get('whatsapp_consent')]
    elif consent_f in ('0', 'false', 'no'):
        voters = [v for v in voters if not v.get('whatsapp_consent')]
    if page_no_f:
        try:
            target = int(page_no_f)
            voters = [v for v in voters if int(v.get('page_no') or 0) == target]
        except ValueError:
            pass
    for ck, cv in custom_filters.items():
        voters = [v for v in voters if str((v.get('custom_tags') or {}).get(ck) or '').lower() == cv.lower()]

    total = len(voters)
    start = (page - 1) * per_page
    end = start + per_page
    page_voters = voters[start:end]

    return jsonify({
        'voters': page_voters,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })


@app.route('/api/voter/<nqt_id>', methods=['GET'])
def get_voter(nqt_id):
    """Get full voter profile + per-field change history (from AuditLog)."""
    voter = next((v for v in STORE['voters'] if v.get('nqt_id') == nqt_id), None)
    if not voter:
        return jsonify({'error': 'Voter not found'}), 404
    if not voter_in_scope(voter):
        return jsonify({'error': 'Not authorized for this voter'}), 403
    history = (AuditLog.query
               .filter(AuditLog.voter_nqt_id == nqt_id)
               .order_by(AuditLog.timestamp.desc())
               .limit(200).all())
    user_cache = {}
    def _uname(uid):
        if not uid:
            return 'system'
        if uid not in user_cache:
            u = User.query.get(uid)
            user_cache[uid] = (u.display_name or u.username) if u else f'user#{uid}'
        return user_cache[uid]
    return jsonify({
        'voter': voter,
        'history': [{
            'timestamp': h.timestamp.isoformat() if h.timestamp else '',
            'user': _uname(h.user_id),
            'action': h.action,
            'field': h.field_name,
            'old_value': h.old_value,
            'new_value': h.new_value,
        } for h in history],
    })


# Role-based field permissions for editing a voter
_VOTER_EDIT_PERMS = {
    'admin':       {'*'},  # everything
    'manager':     {'*'},
    'candidate':   {'classification', 'sentiment', 'notes', 'tags', 'party_lean', 'custom_tags'},
    'booth_agent': {'classification', 'sentiment', 'voted', 'slip_delivered',
                    'contact_count', 'notes', 'phone', 'custom_tags'},
    'karyakarta':  {'contact_count', 'notes', 'phone', 'custom_tags'},
}
_ALWAYS_ALLOWED = {'classification', 'sentiment', 'influence_score', 'contact_count',
                   'is_beneficiary', 'is_migrated', 'slip_delivered', 'voted',
                   'notes', 'tags', 'caste', 'party_lean', 'phone', 'whatsapp',
                   'whatsapp_consent', 'socials',
                   'name', 'father_name', 'age', 'gender', 'house_no', 'address',
                   'voter_id', 'surname', 'community', 'part_no', 'sr_no',
                   'page_no', 'family_id', 'custom_tags'}


@app.route('/api/voter/<nqt_id>', methods=['PUT'])
def update_voter(nqt_id):
    """Update voter fields. Field set is gated by the caller's role.
    Unauthenticated calls are limited to the legacy curated subset for
    backward-compat with existing UI flows."""
    data = request.json
    if not data:
        return jsonify({'error': 'No data'}), 400

    voter = next((v for v in STORE['voters'] if v.get('nqt_id') == nqt_id), None)
    if not voter:
        return jsonify({'error': 'Voter not found'}), 404
    if not voter_in_scope(voter):
        return jsonify({'error': 'Not authorized for this voter'}), 403

    role = getattr(g, 'role', None)
    if role:
        perms = _VOTER_EDIT_PERMS.get(role, set())
        if '*' in perms:
            allowed = _ALWAYS_ALLOWED
        else:
            allowed = perms
    else:
        # Legacy unauthenticated path
        allowed = {'classification', 'sentiment', 'influence_score', 'contact_count',
                   'is_beneficiary', 'is_migrated', 'slip_delivered', 'voted',
                   'notes', 'tags', 'caste', 'party_lean'}

    rejected = []
    for key in data.keys():
        if key not in allowed and key in _ALWAYS_ALLOWED:
            rejected.append(key)

    for key in list(data.keys()):
        if key not in allowed:
            continue
        old_val = voter.get(key, '')
        if key == 'tags' and isinstance(data[key], list):
            voter[key] = [str(t).strip()[:50] for t in data[key] if str(t).strip()]
        elif key == 'socials' and isinstance(data[key], dict):
            current = voter.get('socials') if isinstance(voter.get('socials'), dict) else {}
            merged = dict(current)
            for sk, sv in data[key].items():
                if sv is None:
                    merged.pop(sk, None)
                else:
                    merged[str(sk).strip()] = str(sv).strip()
            voter['socials'] = merged
            for sk, sv in data[key].items():
                old_sv = current.get(sk)
                new_sv = merged.get(sk)
                if (old_sv or '') != (new_sv or ''):
                    _log_audit('update_voter', voter.get('nqt_id', ''),
                               f'social.{sk}', old_sv, new_sv)
            continue
        elif key == 'custom_tags' and isinstance(data[key], dict):
            # Merge custom_tags partial update; validate against TagDefinitions
            current = voter.get('custom_tags') if isinstance(voter.get('custom_tags'), dict) else {}
            defs = {d.key: d for d in TagDefinition.query.all()}
            merged = dict(current)
            for tk, tv in data[key].items():
                tdef = defs.get(tk)
                if not tdef:
                    continue  # silently drop unknown keys
                if tdef.field_type == 'dropdown' and tv not in tdef.options and tv not in ('', None):
                    continue
                if tdef.field_type == 'boolean':
                    tv = bool(tv)
                merged[tk] = tv
            voter['custom_tags'] = merged
            # Log per-key changes
            for tk, tv in data[key].items():
                old_tv = current.get(tk)
                if (old_tv or '') != (merged.get(tk) or ''):
                    _log_audit('update_voter_tag', voter.get('nqt_id', ''),
                               f'custom.{tk}', old_tv, merged.get(tk))
            continue  # skip generic logging below
        else:
            voter[key] = data[key]
        if (old_val or '') != (voter.get(key) or ''):
            _log_audit('update_voter', voter.get('nqt_id', ''), key, old_val, voter.get(key))
    STORE['source'] = 'edited'

    return jsonify({'success': True, 'voter': voter, 'rejected_fields': rejected})


@app.route('/api/voter/<nqt_id>/contact', methods=['POST'])
def log_contact(nqt_id):
    """Increment contact count for a voter"""
    voter = next((v for v in STORE['voters'] if v.get('nqt_id') == nqt_id), None)
    if not voter:
        return jsonify({'error': 'Voter not found'}), 404
    if not voter_in_scope(voter):
        return jsonify({'error': 'Not authorized for this voter'}), 403

    voter['contact_count'] = voter.get('contact_count', 0) + 1
    return jsonify({'success': True, 'contact_count': voter['contact_count']})


@app.route('/api/bulk-update', methods=['POST'])
def bulk_update():
    """Bulk update voter fields. Field allow-list is gated by caller role,
    and updates only apply to voters within the caller's scope."""
    data = request.json
    if not data or 'nqt_ids' not in data or 'updates' not in data:
        return jsonify({'error': 'Provide nqt_ids and updates'}), 400

    role = getattr(g, 'role', None)
    if role:
        perms = _VOTER_EDIT_PERMS.get(role, set())
        if '*' in perms:
            allowed = list(_ALWAYS_ALLOWED)
        else:
            allowed = list(perms)
    else:
        allowed = ['classification', 'sentiment', 'slip_delivered', 'voted', 'notes',
                   'caste', 'party_lean']

    nqt_ids = set(data['nqt_ids'])
    updates = {k: v for k, v in data['updates'].items() if k in allowed}
    rejected = [k for k in data['updates'].keys() if k not in allowed]
    count = 0

    for voter in STORE['voters']:
        if voter.get('nqt_id') in nqt_ids and voter_in_scope(voter):
            for k, v in updates.items():
                voter[k] = v
            count += 1

    return jsonify({'success': True, 'updated': count, 'rejected_fields': rejected})


@app.route('/api/mark-voted', methods=['POST'])
def mark_voted():
    """Mark voter(s) as voted (election day)"""
    data = request.json
    if not data or 'nqt_ids' not in data:
        return jsonify({'error': 'Provide nqt_ids array'}), 400

    nqt_ids = set(data['nqt_ids'])
    count = 0
    for voter in STORE['voters']:
        if voter.get('nqt_id') in nqt_ids and voter_in_scope(voter):
            voter['voted'] = True
            count += 1

    return jsonify({'success': True, 'marked': count})


# ─── Search ─────────────────────────────────────────────────────────

@app.route('/api/search')
def search():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    query = request.args.get('q', '')
    field = request.args.get('field', 'name')
    limit = request.args.get('limit', 100, type=int)
    results = get_analytics().search_voters(query, field, limit)
    return jsonify({'results': results, 'count': len(results)})


# ─── Export ─────────────────────────────────────────────────────────

@app.route('/api/export/csv')
def export_csv():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400

    import csv
    voters = _scoped_voters()
    output = io.StringIO()
    if voters:
        writer = csv.DictWriter(output, fieldnames=voters[0].keys())
        writer.writeheader()
        for voter in voters:
            writer.writerow(voter)

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='election_intel_export.csv'
    )


@app.route('/api/export/json')
def export_json():
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded'}), 400
    data = {'voters': _scoped_voters(), 'metadata': STORE['metadata']}
    return jsonify(data)


def _safe_ward_filename(name):
    """Sanitize ward name to safe filename"""
    return re.sub(r'[^a-zA-Z0-9_\- ]', '', name).strip()[:80]


def _active_ward_name():
    """Currently loaded ward name (matches User.assigned_ward).
    Pages and karyakartas must belong to the same ward; this is the
    canonical name used for that comparison."""
    return (STORE.get('filename') or '').strip()


def _wards_match(a, b):
    """Case/space-insensitive ward-name comparison."""
    return (a or '').strip().lower() == (b or '').strip().lower()


# ─── Ward Save / Load ──────────────────────────────────────────────

@app.route('/api/wards', methods=['GET'])
def list_wards():
    """List saved wards. Non-admin/manager users only see their assigned ward."""
    role = getattr(g, 'role', None)
    user_assigned = ''
    if role and role not in ('admin', 'manager'):
        u = User.query.get(getattr(g, 'user_id', None)) if getattr(g, 'user_id', None) else None
        user_assigned = (u.assigned_ward or '') if u else ''
    wards = []
    for fname in sorted(os.listdir(SAVE_DIR)):
        if fname.endswith('.json'):
            fpath = os.path.join(SAVE_DIR, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                ward_key = fname[:-5]
                if user_assigned and ward_key != user_assigned and data.get('ward_name', '') != user_assigned:
                    continue
                wards.append({
                    'name': data.get('ward_name', fname[:-5]),
                    'filename': data.get('source_filename', ''),
                    'total_voters': len(data.get('voters', [])),
                    'saved_at': data.get('saved_at', ''),
                })
            except Exception:
                pass
    return jsonify(wards)


def _aggregate_voters(voters, filters=None):
    """Compute aggregate metrics for a list of voter dicts with optional filters."""
    filters = filters or {}
    f_class = (filters.get('classification') or '').strip()
    f_gender = (filters.get('gender') or '').strip()
    f_booth = (filters.get('booth') or '').strip()
    f_age_bucket = (filters.get('age_bucket') or '').strip()  # 18-25 / 26-40 / 41-60 / 60+

    def _age_bucket_of(age):
        try:
            a = int(age)
        except Exception:
            return ''
        if a < 26: return '18-25'
        if a < 41: return '26-40'
        if a < 61: return '41-60'
        return '60+'

    filtered = []
    for v in voters:
        if f_class and (v.get('classification') or '') != f_class:
            continue
        if f_gender and (v.get('gender') or '') != f_gender:
            continue
        if f_booth and str(v.get('part_no') or '') != f_booth:
            continue
        if f_age_bucket and _age_bucket_of(v.get('age')) != f_age_bucket:
            continue
        filtered.append(v)

    total = len(filtered)
    by_classification = {}
    by_gender = {}
    by_party = {}
    by_age = {'18-25': 0, '26-40': 0, '41-60': 0, '60+': 0, 'unknown': 0}
    by_community = {}
    by_booth = {}
    pages_seen = set()
    contacted = 0
    voted = 0
    slip_delivered = 0
    with_phone = 0

    for v in filtered:
        cl = v.get('classification') or 'Unclassified'
        by_classification[cl] = by_classification.get(cl, 0) + 1
        g = v.get('gender') or 'Unknown'
        by_gender[g] = by_gender.get(g, 0) + 1
        pl = v.get('party_lean') or 'Unknown'
        by_party[pl] = by_party.get(pl, 0) + 1
        ab = _age_bucket_of(v.get('age')) or 'unknown'
        by_age[ab] = by_age.get(ab, 0) + 1
        comm = (v.get('community') or 'Unknown').strip() or 'Unknown'
        by_community[comm] = by_community.get(comm, 0) + 1
        booth = str(v.get('part_no') or '')
        if booth:
            by_booth[booth] = by_booth.get(booth, 0) + 1
        if v.get('contact_count'):
            contacted += 1
        if v.get('voted'):
            voted += 1
        if v.get('slip_delivered'):
            slip_delivered += 1
        if (v.get('phone') or '').strip():
            with_phone += 1
        try:
            pn = int(v.get('page_no') or 0)
            if pn:
                pages_seen.add(pn)
        except (TypeError, ValueError):
            pass

    top_communities = sorted(by_community.items(), key=lambda x: -x[1])[:10]

    return {
        'total': total,
        'by_classification': by_classification,
        'by_gender': by_gender,
        'by_party_lean': by_party,
        'by_age_bucket': by_age,
        'top_communities': [{'name': n, 'count': c} for n, c in top_communities],
        'by_booth_count': len(by_booth),
        'contacted': contacted,
        'voted': voted,
        'slip_delivered': slip_delivered,
        'with_phone': with_phone,
        'contact_pct': round(100 * contacted / total, 1) if total else 0,
        'voted_pct': round(100 * voted / total, 1) if total else 0,
        'phone_pct': round(100 * with_phone / total, 1) if total else 0,
        'pages_total': len(pages_seen),
    }


@app.route('/api/wards/compare', methods=['GET'])
def compare_wards():
    """Compare aggregate metrics across multiple saved wards.

    Query params:
      wards=A,B,C       (comma-separated ward names; default = all)
      classification, gender, booth, age_bucket  (optional filters)
    """
    requested = (request.args.get('wards') or '').strip()
    requested_set = set([w.strip() for w in requested.split(',') if w.strip()]) if requested else None
    filters = {
        'classification': request.args.get('classification', ''),
        'gender': request.args.get('gender', ''),
        'booth': request.args.get('booth', ''),
        'age_bucket': request.args.get('age_bucket', ''),
    }

    results = []
    insights = []
    # Pre-compute per-ward karyakarta page assignments
    karyakarta_pages_by_ward = {}
    for u in User.query.filter(User.role.in_(['karyakarta', 'booth_agent'])).all():
        if not u.assigned_ward:
            continue
        karyakarta_pages_by_ward.setdefault(u.assigned_ward, set()).update(u.assigned_pages or [])
    for fname in sorted(os.listdir(SAVE_DIR)):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(SAVE_DIR, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        name = data.get('ward_name', fname[:-5])
        if requested_set and name not in requested_set:
            continue
        agg = _aggregate_voters(data.get('voters', []), filters)
        agg['ward'] = name
        # Page coverage by karyakartas
        ward_key = fname[:-5]
        assigned = karyakarta_pages_by_ward.get(ward_key) or karyakarta_pages_by_ward.get(name) or set()
        ward_pages = set()
        for v in data.get('voters', []):
            try:
                pn = int(v.get('page_no') or 0)
                if pn:
                    ward_pages.add(pn)
            except (TypeError, ValueError):
                pass
        covered = ward_pages & assigned
        agg['pages_assigned'] = len(covered)
        agg['pages_unassigned'] = len(ward_pages - assigned)
        agg['page_coverage_pct'] = round(100 * len(covered) / len(ward_pages), 1) if ward_pages else 0
        results.append(agg)

    # Insights
    if results:
        biggest = max(results, key=lambda r: r['total'])
        smallest = min(results, key=lambda r: r['total'])
        most_pakka = max(results, key=lambda r: r['by_classification'].get('Pakka', 0))
        best_phone = max(results, key=lambda r: r['phone_pct'])
        best_contact = max(results, key=lambda r: r['contact_pct'])
        insights = [
            f"Largest ward by voters: {biggest['ward']} ({biggest['total']:,})",
            f"Smallest ward by voters: {smallest['ward']} ({smallest['total']:,})",
            f"Most Pakka voters: {most_pakka['ward']} ({most_pakka['by_classification'].get('Pakka', 0):,})",
            f"Best phone coverage: {best_phone['ward']} ({best_phone['phone_pct']}%)",
            f"Best contact rate: {best_contact['ward']} ({best_contact['contact_pct']}%)",
        ]

    return jsonify({
        'wards': results,
        'filters_applied': {k: v for k, v in filters.items() if v},
        'insights': insights,
    })


@app.route('/api/wards', methods=['POST'])
def save_ward():
    """Save current data as a named ward.

    On RE-SAVE of an existing ward (same name), performs an upsert keyed by
    `nqt_id` and records:
      - per-voter field-level diffs in AuditLog
      - one WardUploadHistory row summarizing added / updated / removed counts
        plus a snapshot of the PDF cover-page metadata
    The on-disk JSON snapshot is overwritten with the latest merged state.
    """
    if not STORE['voters']:
        return jsonify({'error': 'No data loaded to save'}), 400

    body = request.json or {}
    ward_name = (body.get('name') or '').strip()
    if not ward_name:
        return jsonify({'error': 'Ward name is required'}), 400

    hierarchy = {}
    for key in ('region', 'state', 'division', 'district', 'taluka', 'hobli', 'gram_panchayat', 'village'):
        val = (body.get(key) or '').strip()
        if val:
            hierarchy[key] = val

    safe_name = _safe_ward_filename(ward_name)
    if not safe_name:
        return jsonify({'error': 'Invalid ward name'}), 400

    fpath = os.path.join(SAVE_DIR, safe_name + '.json')

    # ── Diff against existing snapshot (if any) ──
    # EPIC (voter_id) is the canonical, globally-unique voter identity.
    # Match by EPIC first, then fall back to nqt_id for records that have
    # no EPIC printed in the PDF.
    prev_voters_by_nqt = {}
    prev_voters_by_epic = {}
    if os.path.isfile(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                prev = json.load(f)
            for pv in prev.get('voters', []):
                nqt = pv.get('nqt_id')
                epic = (pv.get('voter_id') or '').strip().upper()
                if nqt:
                    prev_voters_by_nqt[nqt] = pv
                if epic:
                    prev_voters_by_epic[epic] = pv
        except Exception:
            prev_voters_by_nqt, prev_voters_by_epic = {}, {}

    new_voters_by_nqt = {v['nqt_id']: v for v in STORE['voters'] if v.get('nqt_id')}

    # ── Cross-ward EPIC index ──
    # Scan every OTHER saved ward to detect voters that already exist
    # somewhere else by EPIC. Treat those as moves: bring curated fields
    # forward, log the move, and remove from the old ward.
    other_ward_files = {}   # safe_name -> {'path':..., 'data':..., 'idx': {epic: voter_pos}}
    epic_to_other_ward = {}  # epic -> safe_name
    try:
        for fn in os.listdir(SAVE_DIR):
            if not fn.endswith('.json') or fn[:-5] == safe_name:
                continue
            try:
                with open(os.path.join(SAVE_DIR, fn), 'r', encoding='utf-8') as f:
                    d = json.load(f)
            except Exception:
                continue
            idx = {}
            for i, ov in enumerate(d.get('voters', [])):
                e = (ov.get('voter_id') or '').strip().upper()
                if e and e not in epic_to_other_ward:  # first match wins
                    idx[e] = i
                    epic_to_other_ward[e] = fn[:-5]
            other_ward_files[fn[:-5]] = {
                'path': os.path.join(SAVE_DIR, fn),
                'data': d,
                'idx': idx,
            }
    except Exception:
        pass

    # Fields whose changes we record. User-curated fields (notes, sentiment,
    # tags...) are NEVER overwritten by a re-upload — they're preserved from
    # the previous record. PDF-sourced fields are refreshed.
    PDF_FIELDS = {'name', 'father_name', 'age', 'gender', 'house_no', 'sr_no',
                  'part_no', 'address', 'voter_id', 'surname', 'community',
                  'family_id', 'family_size', 'is_first_time', 'is_youth',
                  'is_senior', 'is_very_old'}
    CURATED_FIELDS = {'classification', 'sentiment', 'influence_score',
                      'contact_count', 'is_beneficiary', 'is_migrated',
                      'slip_delivered', 'voted', 'notes', 'caste', 'party_lean',
                      'tags', 'phone', 'whatsapp_consent'}

    added = updated = unchanged = moved_in = 0
    matched_prev_keys = set()   # nqt_ids in prev_voters_by_nqt that were matched
    dirty_other_wards = set()   # other-ward safe_names that need a rewrite
    user_id = getattr(g, 'user_id', None)
    # Only preserve curated fields from prev when STORE was just replaced by a
    # fresh PDF parse (otherwise prev would clobber in-memory edits the user
    # made via the dashboard since the last save).
    is_pdf_reupload = (STORE.get('source') == 'upload') and bool(prev_voters_by_nqt)

    # Find or create DB ward (so AuditLog rows have a real ward_id to filter on)
    db_ward = Ward.query.filter_by(file_key=safe_name).first()
    if not db_ward:
        db_ward = Ward(name=ward_name, file_key=safe_name)
        db_ward.hierarchy = hierarchy
        db.session.add(db_ward)
        db.session.flush()
    else:
        db_ward.hierarchy = hierarchy

    for nqt, new_v in new_voters_by_nqt.items():
        epic = (new_v.get('voter_id') or '').strip().upper()

        # ── 1. Try to match within current ward (EPIC first, then nqt_id) ──
        prev_v = None
        if epic and epic in prev_voters_by_epic:
            prev_v = prev_voters_by_epic[epic]
        elif nqt in prev_voters_by_nqt:
            prev_v = prev_voters_by_nqt[nqt]
        if prev_v is not None:
            old_nqt = prev_v.get('nqt_id')
            matched_prev_keys.add(old_nqt)
            # If EPIC matched but the printed nqt_id changed, re-key prior
            # audit history so the voter profile keeps showing the full trail.
            if old_nqt and old_nqt != nqt:
                try:
                    AuditLog.query.filter_by(voter_nqt_id=old_nqt).update(
                        {'voter_nqt_id': nqt[:40]}, synchronize_session=False)
                except Exception:
                    pass
            if is_pdf_reupload:
                for cf in CURATED_FIELDS:
                    if cf in prev_v:
                        new_v[cf] = prev_v[cf]
            changed = False
            for f in PDF_FIELDS:
                old_val = prev_v.get(f)
                new_val = new_v.get(f)
                if (old_val or '') != (new_val or ''):
                    changed = True
                    try:
                        db.session.add(AuditLog(
                            user_id=user_id, ward_id=db_ward.id, voter_nqt_id=nqt[:40],
                            action='pdf_reupload', field_name=f[:40],
                            old_value=str(old_val)[:500], new_value=str(new_val)[:500],
                        ))
                    except Exception:
                        pass
            if changed:
                updated += 1
            else:
                unchanged += 1
            continue

        # ── 2. Cross-ward EPIC match (voter moved from another ward) ──
        if epic and epic in epic_to_other_ward:
            other_safe = epic_to_other_ward[epic]
            other = other_ward_files[other_safe]
            old_pos = other['idx'][epic]
            old_v = other['data']['voters'][old_pos]
            old_nqt = old_v.get('nqt_id') if old_v else None
            # Re-key audit history to the new nqt_id so the move preserves trail
            if old_nqt and old_nqt != nqt:
                try:
                    AuditLog.query.filter_by(voter_nqt_id=old_nqt).update(
                        {'voter_nqt_id': nqt[:40]}, synchronize_session=False)
                except Exception:
                    pass
            # Always preserve curated fields on a cross-ward move
            for cf in CURATED_FIELDS:
                if cf in old_v:
                    new_v[cf] = old_v[cf]
            # Log per-field PDF diffs against the prior record
            for f in PDF_FIELDS:
                ov, nv = old_v.get(f), new_v.get(f)
                if (ov or '') != (nv or ''):
                    try:
                        db.session.add(AuditLog(
                            user_id=user_id, ward_id=db_ward.id, voter_nqt_id=nqt[:40],
                            action='pdf_reupload', field_name=f[:40],
                            old_value=str(ov)[:500], new_value=str(nv)[:500],
                        ))
                    except Exception:
                        pass
            # Log the ward move itself
            try:
                db.session.add(AuditLog(
                    user_id=user_id, ward_id=db_ward.id, voter_nqt_id=nqt[:40],
                    action='moved_ward', field_name='_ward',
                    old_value=other_safe[:500], new_value=safe_name[:500],
                ))
            except Exception:
                pass
            # Tombstone in the old ward; compacted before write
            other['data']['voters'][old_pos] = None
            dirty_other_wards.add(other_safe)
            moved_in += 1
            continue

        # ── 3. Truly new voter ──
        added += 1

    # Voters that were in the previous snapshot but did not match any new
    # row (by EPIC or nqt_id) are considered removed from this ward.
    removed_nqts = set(prev_voters_by_nqt.keys()) - matched_prev_keys

    # Log removals
    for nqt in removed_nqts:
        try:
            db.session.add(AuditLog(
                user_id=user_id, ward_id=db_ward.id, voter_nqt_id=nqt[:40],
                action='pdf_reupload_removed', field_name='_voter',
                old_value='present', new_value='removed',
            ))
        except Exception:
            pass

    # A "true" PDF re-upload (for upload-history bookkeeping) only happens
    # when STORE was just replaced by a fresh parse AND a prior snapshot exists.
    is_reupload = is_pdf_reupload
    # Only write an upload-history row for actual PDF uploads (initial parse
    # or re-upload). Saves that just persist in-app edits are skipped to avoid
    # cluttering the history.
    write_history = STORE.get('source') == 'upload'
    if write_history:
        history_row = WardUploadHistory(
            ward_id=db_ward.id,
            user_id=user_id,
            filename=STORE.get('filename') or '',
            voters_added=(added + moved_in) if is_reupload else len(new_voters_by_nqt),
            voters_updated=updated,
            voters_removed=len(removed_nqts),
            voters_unchanged=unchanged,
            metadata_json=json.dumps(STORE.get('metadata') or {}, ensure_ascii=False, default=str),
        )
        db.session.add(history_row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Persist JSON snapshot
    payload = {
        'ward_name': ward_name,
        'hierarchy': hierarchy,
        'source_filename': STORE['filename'],
        'saved_at': datetime.now().isoformat(),
        'metadata': STORE['metadata'],
        'voters': list(new_voters_by_nqt.values()),
        'election_history': STORE.get('election_history', []),
        'tag_definitions': [td.to_dict() for td in TagDefinition.query.order_by(TagDefinition.sort_order).all()],
    }
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)

    # Rewrite any ward files whose voters were moved into the current ward.
    for other_safe in dirty_other_wards:
        entry = other_ward_files[other_safe]
        entry['data']['voters'] = [v for v in entry['data']['voters'] if v is not None]
        try:
            with open(entry['path'], 'w', encoding='utf-8') as f:
                json.dump(entry['data'], f, ensure_ascii=False)
        except Exception:
            pass

    STORE['ward_id'] = db_ward.id
    # After persisting, current STORE is in sync with disk. Treat as 'loaded'
    # so a subsequent save without re-upload doesn't appear as a re-upload.
    STORE['source'] = 'loaded'

    return jsonify({
        'success': True,
        'name': ward_name,
        'total_voters': len(new_voters_by_nqt),
        'is_reupload': is_reupload,
        'diff': {
            'added': added,
            'updated': updated,
            'removed': len(removed_nqts),
            'unchanged': unchanged,
            'moved_in': moved_in,
            'moved_from_wards': sorted(dirty_other_wards),
        },
    })


@app.route('/api/wards/<name>/hierarchy', methods=['PUT'])
def update_ward_hierarchy(name):
    """Update hierarchy info for an existing saved ward"""
    safe_name = _safe_ward_filename(name)
    fpath = os.path.join(SAVE_DIR, safe_name + '.json')
    if not os.path.isfile(fpath):
        return jsonify({'error': 'Ward not found'}), 404

    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    body = request.json or {}
    hierarchy = {}
    for key in ('region', 'state', 'division', 'district', 'taluka', 'hobli', 'gram_panchayat', 'village'):
        val = (body.get(key) or '').strip()
        if val:
            hierarchy[key] = val
    data['hierarchy'] = hierarchy

    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    return jsonify({'success': True, 'name': name})


@app.route('/api/wards/<name>', methods=['GET'])
def load_ward(name):
    """Load a saved ward into memory"""
    safe_name = _safe_ward_filename(name)
    fpath = os.path.join(SAVE_DIR, safe_name + '.json')
    if not os.path.isfile(fpath):
        return jsonify({'error': 'Ward not found'}), 404

    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    STORE['voters'] = data.get('voters', [])
    STORE['metadata'] = data.get('metadata', {})
    STORE['filename'] = data.get('ward_name', '') or data.get('source_filename', '')
    STORE['upload_time'] = data.get('saved_at', '')
    STORE['election_history'] = data.get('election_history', [])
    STORE['source'] = 'loaded'

    # Re-hydrate any TagDefinitions that were active when this ward was
    # saved but have since been deleted from the live DB. Existing
    # definitions are left untouched.
    snapshot_defs = data.get('tag_definitions') or []
    if snapshot_defs:
        try:
            existing_keys = {td.key for td in TagDefinition.query.all()}
            for sd in snapshot_defs:
                if sd.get('key') and sd['key'] not in existing_keys:
                    td = TagDefinition(
                        key=sd['key'][:60],
                        label=(sd.get('label') or sd['key'])[:120],
                        field_type=sd.get('field_type') or 'text',
                        is_required=bool(sd.get('is_required')),
                        is_builtin=bool(sd.get('is_builtin')),
                        sort_order=int(sd.get('sort_order') or 0),
                    )
                    td.options = sd.get('options') or []
                    db.session.add(td)
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({
        'success': True,
        'name': data.get('ward_name', name),
        'filename': STORE['filename'],
        'total_voters': len(STORE['voters']),
        'metadata': STORE['metadata'],
    })


@app.route('/api/wards/<name>/history', methods=['GET'])
def ward_upload_history(name):
    """Return chronological upload history for a saved ward."""
    safe_name = _safe_ward_filename(name)
    db_ward = Ward.query.filter_by(file_key=safe_name).first()
    if not db_ward:
        return jsonify({'ward': name, 'history': []})
    rows = (WardUploadHistory.query
            .filter_by(ward_id=db_ward.id)
            .order_by(WardUploadHistory.uploaded_at.desc())
            .all())
    return jsonify({
        'ward': name,
        'ward_id': db_ward.id,
        'history': [r.to_dict() for r in rows],
    })


@app.route('/api/wards/<name>', methods=['DELETE'])
def delete_ward(name):
    """Delete a saved ward"""
    safe_name = _safe_ward_filename(name)
    fpath = os.path.join(SAVE_DIR, safe_name + '.json')
    if not os.path.isfile(fpath):
        return jsonify({'error': 'Ward not found'}), 404
    os.remove(fpath)
    return jsonify({'success': True})


# ─── Authentication ─────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    user = User.query.filter_by(username=username, is_active=True).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid credentials'}), 401

    user.last_login = datetime.now(timezone.utc)
    db.session.commit()

    token = create_token(user.id, user.username, user.role)
    return jsonify({
        'success': True,
        'token': token,
        'user': user.to_dict(),
    })


@app.route('/api/auth/me')
@require_auth
def auth_me():
    user = User.query.get(g.user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user.to_dict())


@app.route('/api/auth/password', methods=['PUT'])
@require_auth
def auth_change_password():
    data = request.json or {}
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')
    if not old_pw or not new_pw:
        return jsonify({'error': 'Old and new password required'}), 400
    if len(new_pw) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400

    user = User.query.get(g.user_id)
    if not check_password_hash(user.password_hash, old_pw):
        return jsonify({'error': 'Current password is incorrect'}), 401

    user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/auth/register', methods=['POST'])
@require_auth
@require_role('admin', 'manager')
def auth_register():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    role = data.get('role', 'karyakarta')
    display_name = (data.get('display_name') or username).strip()
    phone = (data.get('phone') or '').strip()
    whatsapp = (data.get('whatsapp') or '').strip()
    socials = data.get('socials') or {}
    if not isinstance(socials, dict): socials = {}
    assigned_ward = (data.get('assigned_ward') or '').strip()
    surname = (data.get('surname') or '').strip()
    location_details = (data.get('location_details') or '').strip()
    assigned_pages = data.get('assigned_pages') or []
    assigned_booths = data.get('assigned_booths') or []

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400
    if role not in User.ROLES:
        return jsonify({'error': f'Invalid role. Must be one of: {", ".join(User.ROLES)}'}), 400
    # Managers cannot create admins
    if g.role == 'manager' and role == 'admin':
        return jsonify({'error': 'Managers cannot create admin users'}), 403
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 409

    user = User(
        username=username,
        display_name=display_name,
        password_hash=generate_password_hash(password),
        role=role,
        phone=phone,
        whatsapp=whatsapp,
        assigned_ward=assigned_ward,
        surname=surname,
        location_details=location_details,
        home_state=(data.get('home_state') or '').strip()[:60],
        home_district=(data.get('home_district') or '').strip()[:60],
        home_taluka=(data.get('home_taluka') or '').strip()[:60],
        home_village=(data.get('home_village') or '').strip()[:60],
    )
    user.socials = socials
    if isinstance(assigned_pages, list) and assigned_pages:
        # Pages are ward-scoped — require assigned_ward and that the ward
        # snapshot actually contains the pages being assigned.
        if not assigned_ward:
            return jsonify({'error': 'Cannot assign pages without setting assigned_ward'}), 400
        safe = _safe_ward_filename(assigned_ward)
        fpath = os.path.join(SAVE_DIR, safe + '.json')
        valid_pages = None
        if os.path.isfile(fpath):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    snap = json.load(f)
                valid_pages = {v.get('page_no') for v in snap.get('voters', []) if v.get('page_no')}
            except Exception:
                pass
        elif _wards_match(assigned_ward, _active_ward_name()):
            valid_pages = {v.get('page_no') for v in STORE['voters'] if v.get('page_no')}
        if valid_pages is None:
            return jsonify({'error': f"No saved snapshot for ward '{assigned_ward}'. Save the ward first."}), 400
        invalid = [p for p in assigned_pages if p not in valid_pages]
        if invalid:
            return jsonify({'error': f"Pages not in ward '{assigned_ward}': {invalid[:10]}"}), 400
        user.assigned_pages = assigned_pages
    elif isinstance(assigned_pages, list):
        user.assigned_pages = assigned_pages  # empty list — OK
    if isinstance(assigned_booths, list):
        user.assigned_booths = assigned_booths
    db.session.add(user)
    db.session.commit()
    _log_audit('create_user', field='username', new_val=username)
    return jsonify({'success': True, 'user': user.to_dict()}), 201


@app.route('/api/auth/users')
@require_auth
@require_role('admin', 'manager')
def auth_list_users():
    users = User.query.order_by(User.created_at).all()
    return jsonify([u.to_dict() for u in users])


@app.route('/api/auth/users/<int:uid>', methods=['PUT'])
@require_auth
@require_role('admin', 'manager')
def auth_update_user(uid):
    user = User.query.get(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.json or {}
    if 'role' in data and data['role'] in User.ROLES:
        user.role = data['role']
    if 'is_active' in data:
        user.is_active = bool(data['is_active'])
    if 'display_name' in data:
        user.display_name = str(data['display_name']).strip()[:120]
    if 'phone' in data:
        user.phone = str(data['phone']).strip()[:15]
    if 'whatsapp' in data:
        user.whatsapp = str(data['whatsapp']).strip()[:15]
    if 'socials' in data and isinstance(data['socials'], dict):
        user.socials = data['socials']
    # Track ward change — changing ward must clear page assignments,
    # since pages belong to a specific ward.
    new_ward = data.get('assigned_ward', user.assigned_ward)
    if 'assigned_ward' in data:
        new_ward = str(data['assigned_ward'] or '').strip()[:120]
        if not _wards_match(new_ward, user.assigned_ward) and (user.assigned_pages or []):
            # Ward changed — only proceed if caller is also clearing/replacing pages
            if 'assigned_pages' not in data:
                return jsonify({
                    'error': f"Changing ward from '{user.assigned_ward}' to '{new_ward}' would orphan {len(user.assigned_pages)} page assignment(s). Send `assigned_pages: []` (or new pages for the new ward) in the same request."
                }), 400
        user.assigned_ward = new_ward
    if 'surname' in data:
        user.surname = str(data['surname'] or '').strip()[:60]
    if 'location_details' in data:
        user.location_details = str(data['location_details'] or '').strip()[:1000]
    for f in ('home_state', 'home_district', 'home_taluka', 'home_village'):
        if f in data:
            setattr(user, f, str(data[f] or '').strip()[:60])
    if 'assigned_pages' in data and isinstance(data['assigned_pages'], list):
        new_pages = data['assigned_pages']
        if new_pages:
            if not new_ward:
                return jsonify({'error': 'Cannot assign pages: user has no assigned_ward'}), 400
            safe = _safe_ward_filename(new_ward)
            fpath = os.path.join(SAVE_DIR, safe + '.json')
            valid_pages = None
            if os.path.isfile(fpath):
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        snap = json.load(f)
                    valid_pages = {v.get('page_no') for v in snap.get('voters', []) if v.get('page_no')}
                except Exception:
                    pass
            elif _wards_match(new_ward, _active_ward_name()):
                valid_pages = {v.get('page_no') for v in STORE['voters'] if v.get('page_no')}
            if valid_pages is None:
                return jsonify({'error': f"No saved snapshot for ward '{new_ward}'. Save the ward first."}), 400
            invalid = [p for p in new_pages if p not in valid_pages]
            if invalid:
                return jsonify({'error': f"Pages not in ward '{new_ward}': {invalid[:10]}"}), 400
        user.assigned_pages = new_pages
    if 'assigned_booths' in data and isinstance(data['assigned_booths'], list):
        user.assigned_booths = data['assigned_booths']
    if 'password' in data and len(data['password']) >= 4:
        user.password_hash = generate_password_hash(data['password'])

    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()})


@app.route('/api/auth/users/<int:uid>', methods=['DELETE'])
@require_auth
@require_role('admin')
def auth_delete_user(uid):
    user = User.query.get(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user.id == g.user_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    user.is_active = False
    db.session.commit()
    return jsonify({'success': True})


# ─── Server / runtime config (admin only) ──────────────────────────

def _mask_secret(val):
    if not val:
        return ''
    s = str(val)
    if len(s) <= 4:
        return '••••'
    return '••••' + s[-4:]


@app.route('/api/admin/server/settings', methods=['GET'])
@require_auth
@require_role('admin')
def admin_get_server_settings():
    """Return the catalog of known settings with current values. Secrets
    are masked unless ?reveal=1 is passed (and even then only for admin)."""
    from database import SETTING_DEFS, ServerSetting
    reveal = request.args.get('reveal') == '1'
    rows = {r.key: r for r in ServerSetting.query.all()}
    out = []
    for spec in SETTING_DEFS:
        row = rows.get(spec['key'])
        raw = (row.value if row else '') or ''
        from_env = (not raw) and bool(os.environ.get(spec['key']))
        display = raw
        if spec.get('is_secret') and raw and not reveal:
            display = _mask_secret(raw)
        out.append({
            'key': spec['key'],
            'group': spec.get('group', 'server'),
            'label': spec.get('label', spec['key']),
            'type': spec.get('type', 'text'),
            'options': spec.get('options', []),
            'help': spec.get('help', ''),
            'is_secret': bool(spec.get('is_secret')),
            'value': display,
            'has_value': bool(raw),
            'from_env_only': from_env,
            'updated_at': row.updated_at.isoformat() if row and row.updated_at else None,
        })
    return jsonify({'settings': out, 'reveal': reveal})


@app.route('/api/admin/server/settings', methods=['PUT'])
@require_auth
@require_role('admin')
def admin_update_server_settings():
    """Update one or more settings. Body: {settings: [{key, value}, ...]}
    or a flat {key: value} dict. Empty string clears the value."""
    from database import set_setting, SETTING_DEFS_BY_KEY
    data = request.get_json(silent=True) or {}
    items = data.get('settings')
    if items is None:
        # Accept flat {key:value}
        items = [{'key': k, 'value': v} for k, v in data.items()]
    saved, errors = [], []
    for item in items:
        key = (item.get('key') or '').strip()
        if key not in SETTING_DEFS_BY_KEY:
            errors.append({'key': key, 'error': 'unknown key'})
            continue
        val = item.get('value', '')
        # Don't overwrite with a mask value
        if isinstance(val, str) and val.startswith('••••'):
            continue
        try:
            set_setting(key, val, user_id=getattr(g, 'user_id', None))
            saved.append(key)
            _log_audit('server_setting_update', field=key,
                       new_val='(secret)' if SETTING_DEFS_BY_KEY[key].get('is_secret') else str(val)[:80])
        except Exception as e:
            errors.append({'key': key, 'error': str(e)})
    return jsonify({'success': len(errors) == 0, 'saved': saved, 'errors': errors})


@app.route('/api/admin/server/status', methods=['GET'])
@require_auth
@require_role('admin')
def admin_server_status():
    """Snapshot of runtime: DB engine, schema-managed flag, provider status,
    upload paths, version info. Useful for admins after cloud deploy."""
    from sqlalchemy import inspect as sa_inspect
    import sys, platform
    try:
        from whatsapp import get_provider_status
        wa = get_provider_status()
    except Exception as e:
        wa = {'provider': 'unknown', 'configured': False, 'error': str(e)}

    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    # Hide credentials in postgres URL
    safe_db_url = re.sub(r'://([^:]+):([^@]+)@', r'://\1:••••@', db_url)
    try:
        insp = sa_inspect(db.engine)
        table_count = len(insp.get_table_names())
        driver = db.engine.url.drivername
    except Exception:
        table_count = 0
        driver = 'unknown'

    return jsonify({
        'db': {
            'driver': driver,
            'url': safe_db_url,
            'tables': table_count,
            'auto_migrate': True,
        },
        'whatsapp': wa,
        'public_url': (request.host_url or '').rstrip('/'),
        'configured_public_url': '',  # filled by client from settings
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'uploads_dir': os.path.join(os.path.dirname(__file__), 'uploads'),
        'saved_wards_dir': SAVE_DIR,
    })


@app.route('/api/admin/server/test-whatsapp', methods=['POST'])
@require_auth
@require_role('admin')
def admin_test_whatsapp():
    """Send a test WhatsApp message to a single number using current settings."""
    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or '').strip()
    if not phone:
        return jsonify({'success': False, 'error': 'phone required'}), 400
    try:
        from whatsapp import send_rendered
        msg = (data.get('message')
               or 'Election Intelligence test message — your WhatsApp settings are working.')
        result = send_rendered(phone, msg)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── Karyakarta Management ─────────────────────────────────────────

@app.route('/api/karyakartas', methods=['GET'])
@require_auth
def list_karyakartas():
    """List all karyakartas (workers) with their page assignments and per-page
    voter counts pulled from the active ward STORE."""
    role_filter = request.args.get('role') or 'karyakarta'
    # Default: only karyakartas in the currently active ward (ward-scoped).
    # Pass ?ward=all to see everyone, or ?ward=<name> for a specific ward.
    ward_filter = request.args.get('ward')
    if ward_filter is None:
        ward_filter = _active_ward_name()
    q = User.query
    if role_filter and role_filter != 'all':
        q = q.filter(User.role == role_filter)
    users = q.order_by(User.display_name).all()
    if ward_filter and ward_filter != 'all':
        users = [u for u in users if _wards_match(u.assigned_ward, ward_filter)]
    # Map page_no -> voter count from active ward
    page_counts = {}
    for v in STORE['voters']:
        p = v.get('page_no') or 0
        if p:
            page_counts[p] = page_counts.get(p, 0) + 1
    out = []
    for u in users:
        d = u.to_dict()
        d['voter_count'] = sum(page_counts.get(p, 0) for p in d.get('assigned_pages', []))
        out.append(d)
    return jsonify({
        'karyakartas': out,
        'active_ward': STORE.get('filename', ''),
        'total_pages_in_ward': max((v.get('page_no') or 0) for v in STORE['voters']) if STORE['voters'] else 0,
        'total_voters_in_ward': len(STORE['voters']),
    })


@app.route('/api/karyakartas/pages', methods=['GET'])
@require_auth
def karyakarta_page_index():
    """Return per-page voter counts for a ward (default: active STORE)
    and which user (if any) is assigned each page. Used by the
    Karyakarta tab UI.

    Optional ?ward=<saved_ward_name> reads pages from a saved-ward JSON
    snapshot instead of the in-memory STORE so an admin can assign pages
    of any saved ward without first loading it.
    """
    requested_ward = (request.args.get('ward') or '').strip()
    if requested_ward:
        safe = _safe_ward_filename(requested_ward)
        fpath = os.path.join(SAVE_DIR, safe + '.json')
        if not os.path.isfile(fpath):
            return jsonify({'error': f"Ward '{requested_ward}' not found"}), 404
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                snap = json.load(f)
        except Exception as e:
            return jsonify({'error': f'Failed to read ward snapshot: {e}'}), 500
        ward_name_for_match = snap.get('ward_name') or requested_ward
        source_voters = snap.get('voters', [])
    else:
        ward_name_for_match = _active_ward_name()
        source_voters = STORE['voters']

    pages = {}
    for v in source_voters:
        p = v.get('page_no') or 0
        if not p:
            continue
        if p not in pages:
            pages[p] = {'page': p, 'voter_count': 0, 'assigned_to': None}
        pages[p]['voter_count'] += 1
    # Assigned mapping — only users whose assigned_ward matches the
    # requested/active ward, so page numbers aren't mis-attributed.
    users = User.query.filter(User.is_active.is_(True)).all()
    for u in users:
        if ward_name_for_match and not _wards_match(u.assigned_ward, ward_name_for_match):
            continue
        for p in u.assigned_pages:
            if p in pages:
                pages[p]['assigned_to'] = {
                    'id': u.id, 'name': u.display_name or u.username, 'role': u.role
                }
    return jsonify({
        'pages': sorted(pages.values(), key=lambda x: x['page']),
        'total_pages': max(pages.keys()) if pages else 0,
        'ward': ward_name_for_match,
    })


@app.route('/api/karyakartas/<int:uid>/pages', methods=['PUT'])
@require_auth
@require_role('admin', 'manager')
def karyakarta_assign_pages(uid):
    """Replace the assigned_pages list for a karyakarta.

    Body: {"pages": [1, 2, 3]}
    """
    user = User.query.get(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    data = request.json or {}
    pages = data.get('pages', [])
    if not isinstance(pages, list):
        return jsonify({'error': '`pages` must be a list of integers'}), 400
    # Pages are ward-scoped: the karyakarta must have an assigned_ward,
    # and that ward's saved snapshot must actually contain the page numbers
    # being assigned. We no longer require the ward to be "actively loaded"
    # in STORE — the UI fetches pages per-ward via /api/karyakartas/pages?ward=…
    if pages:
        if not user.assigned_ward:
            return jsonify({'error': f"Cannot assign pages: user '{user.display_name or user.username}' has no assigned_ward."}), 400
        safe = _safe_ward_filename(user.assigned_ward)
        fpath = os.path.join(SAVE_DIR, safe + '.json')
        if not os.path.isfile(fpath):
            # Fall back to active STORE if it matches the user's ward
            active = _active_ward_name()
            if not active or not _wards_match(user.assigned_ward, active):
                return jsonify({'error': f"No saved snapshot for ward '{user.assigned_ward}'. Save the ward first."}), 400
            valid_pages = {v.get('page_no') for v in STORE['voters'] if v.get('page_no')}
        else:
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    snap = json.load(f)
                valid_pages = {v.get('page_no') for v in snap.get('voters', []) if v.get('page_no')}
            except Exception:
                valid_pages = None
            if valid_pages is None:
                return jsonify({'error': f"Failed to read pages from ward '{user.assigned_ward}'"}), 500
        invalid = [p for p in pages if p not in valid_pages]
        if invalid:
            return jsonify({'error': f"Pages not in ward '{user.assigned_ward}': {invalid[:10]}{'…' if len(invalid)>10 else ''}"}), 400
    user.assigned_pages = pages
    db.session.commit()
    _log_audit('assign_pages', field=f'user.{user.id}.pages',
               new_val=','.join(str(p) for p in user.assigned_pages))
    return jsonify({'success': True, 'user': user.to_dict()})


# ─── Audit Log ──────────────────────────────────────────────────────

@app.route('/api/audit')
@require_auth
@require_role('admin', 'manager')
def get_audit_log():
    q = AuditLog.query.order_by(AuditLog.timestamp.desc())
    voter_nqt = request.args.get('voter', '')
    if voter_nqt:
        q = q.filter(AuditLog.voter_nqt_id == voter_nqt)
    user_id_f = request.args.get('user_id', type=int)
    if user_id_f:
        q = q.filter(AuditLog.user_id == user_id_f)
    action_f = (request.args.get('action') or '').strip()
    if action_f:
        q = q.filter(AuditLog.action == action_f)
    field_f = (request.args.get('field') or '').strip()
    if field_f:
        q = q.filter(AuditLog.field_name == field_f)
    from_dt = (request.args.get('from') or '').strip()
    to_dt = (request.args.get('to') or '').strip()
    if from_dt:
        try:
            q = q.filter(AuditLog.timestamp >= datetime.fromisoformat(from_dt))
        except ValueError:
            pass
    if to_dt:
        try:
            q = q.filter(AuditLog.timestamp <= datetime.fromisoformat(to_dt))
        except ValueError:
            pass
    limit = min(request.args.get('limit', 200, type=int), 1000)
    logs = q.limit(limit).all()
    user_cache = {}
    def _uname(uid):
        if not uid:
            return 'system'
        if uid not in user_cache:
            u = User.query.get(uid)
            user_cache[uid] = (u.display_name or u.username) if u else f'user#{uid}'
        return user_cache[uid]
    return jsonify([{
        'id': l.id,
        'user_id': l.user_id,
        'user': _uname(l.user_id),
        'ward_id': l.ward_id,
        'voter_nqt_id': l.voter_nqt_id,
        'action': l.action,
        'field': l.field_name,
        'old_value': l.old_value,
        'new_value': l.new_value,
        'timestamp': l.timestamp.isoformat() if l.timestamp else '',
    } for l in logs])


@app.route('/api/karyakartas/<int:uid>/metrics', methods=['GET'])
@require_auth
def karyakarta_metrics(uid):
    """Performance metrics for a single karyakarta over their assigned
    pages/booths in the active ward."""
    user = User.query.get(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    pages = set(user.assigned_pages or [])
    booths = set(user.assigned_booths or [])
    voters = []
    for v in STORE['voters']:
        try:
            pn = int(v.get('page_no') or 0)
        except (TypeError, ValueError):
            pn = 0
        booth = str(v.get('part_no') or '')
        if (pages and pn in pages) or (booths and booth in booths):
            voters.append(v)
    total = len(voters)
    contacted = sum(1 for v in voters if v.get('contact_count'))
    voted = sum(1 for v in voters if v.get('voted'))
    delivered = sum(1 for v in voters if v.get('slip_delivered'))
    pakka = sum(1 for v in voters if (v.get('classification') or '') == 'Pakka')
    by_page = {}
    for v in voters:
        try:
            pn = int(v.get('page_no') or 0)
        except (TypeError, ValueError):
            pn = 0
        if not pn:
            continue
        b = by_page.setdefault(pn, {'page': pn, 'voters': 0, 'contacted': 0, 'voted': 0, 'delivered': 0})
        b['voters'] += 1
        if v.get('contact_count'):
            b['contacted'] += 1
        if v.get('voted'):
            b['voted'] += 1
        if v.get('slip_delivered'):
            b['delivered'] += 1
    return jsonify({
        'user': user.to_dict(),
        'voter_count': total,
        'contacted': contacted,
        'voted': voted,
        'slip_delivered': delivered,
        'pakka': pakka,
        'contact_pct': round(100 * contacted / total, 1) if total else 0,
        'voted_pct': round(100 * voted / total, 1) if total else 0,
        'delivered_pct': round(100 * delivered / total, 1) if total else 0,
        'by_page': sorted(by_page.values(), key=lambda x: x['page']),
    })


@app.route('/api/voter/<nqt_id>/slip-pdf', methods=['GET'])
def voter_slip_pdf(nqt_id):
    """Generate a single-voter printable slip (name, EPIC, age, gender,
    booth, PDF page) as PDF."""
    voter = next((v for v in STORE['voters'] if v.get('nqt_id') == nqt_id), None)
    if not voter:
        return jsonify({'error': 'Voter not found'}), 404
    if not voter_in_scope(voter):
        return jsonify({'error': 'Not authorized for this voter'}), 403
    pdf_buf = _build_slip_pdf([voter], title=f"Voter Slip - {voter.get('name') or nqt_id}")
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f'slip_{nqt_id}.pdf')


@app.route('/api/karyakartas/<int:uid>/pages-pdf', methods=['GET'])
@require_auth
def karyakarta_packet_pdf(uid):
    """Generate a printable packet of all voter slips on the karyakarta's
    assigned pages, grouped by page."""
    user = User.query.get(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    pages = set(user.assigned_pages or [])
    if not pages:
        return jsonify({'error': 'No pages assigned to this user'}), 400
    voters = []
    for v in STORE['voters']:
        try:
            pn = int(v.get('page_no') or 0)
        except (TypeError, ValueError):
            pn = 0
        if pn in pages:
            voters.append(v)
    voters.sort(key=lambda v: (int(v.get('page_no') or 0), str(v.get('sr_no') or '')))
    pdf_buf = _build_slip_pdf(voters, title=f"{user.display_name or user.username} - Voter Packet")
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f'packet_{user.username}.pdf')


def _build_slip_pdf(voters, title='Voter Slip'):
    """Minimal voter-slip PDF builder using reportlab. One slip per voter,
    grouped header by page when multiple are present."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib import colors
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    h_style = ParagraphStyle('h', parent=styles['Heading2'], spaceAfter=6)
    sub_style = ParagraphStyle('sub', parent=styles['Normal'], fontSize=9, textColor=colors.grey)
    story = [Paragraph(title, h_style), Paragraph(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}", sub_style), Spacer(1, 8)]
    current_page = None
    for v in voters:
        pn = v.get('page_no') or '-'
        if pn != current_page:
            current_page = pn
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"<b>PDF Page {pn}</b>", styles['Heading3']))
        rows = [
            ['Name', v.get('name') or '-'],
            ['EPIC / Voter ID', v.get('voter_id') or '-'],
            ['NQT ID', v.get('nqt_id') or '-'],
            ['Father / Husband', v.get('father_name') or '-'],
            ['Age / Gender', f"{v.get('age') or '-'} / {v.get('gender') or '-'}"],
            ['House No', v.get('house_no') or '-'],
            ['Booth (Part No)', v.get('part_no') or '-'],
            ['Sr. No', v.get('sr_no') or '-'],
            ['Phone', v.get('phone') or '-'],
            ['Classification', v.get('classification') or '-'],
        ]
        t = Table(rows, colWidths=[110, 380])
        t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ('BACKGROUND', (0, 0), (0, -1), colors.whitesmoke),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))
    doc.build(story)
    buf.seek(0)
    return buf


# ─── Tag Definitions (admin-managed custom tag fields) ─────────────

@app.route('/api/tag-defs', methods=['GET'])
def list_tag_defs():
    """List all custom tag field definitions (visible to all auth'd users)."""
    defs = TagDefinition.query.order_by(TagDefinition.sort_order, TagDefinition.id).all()
    return jsonify([d.to_dict() for d in defs])


@app.route('/api/tag-defs', methods=['POST'])
@require_auth
@require_role('admin', 'manager')
def create_tag_def():
    data = request.json or {}
    key = (data.get('key') or '').strip().lower()
    label = (data.get('label') or '').strip()
    ft = data.get('field_type', 'dropdown')
    options = data.get('options', []) if isinstance(data.get('options'), list) else []

    if not key or not re.match(r'^[a-z][a-z0-9_]{0,40}$', key):
        return jsonify({'error': 'key must be lowercase letters/digits/underscore, start with a letter'}), 400
    if not label:
        return jsonify({'error': 'label is required'}), 400
    if ft not in TagDefinition.FIELD_TYPES:
        return jsonify({'error': f'field_type must be one of {TagDefinition.FIELD_TYPES}'}), 400
    if TagDefinition.query.filter_by(key=key).first():
        return jsonify({'error': 'key already exists'}), 409

    td = TagDefinition(
        key=key, label=label, field_type=ft,
        is_required=bool(data.get('is_required')),
        sort_order=int(data.get('sort_order') or 0),
        created_by=getattr(g, 'user_id', None),
    )
    td.options = [str(o).strip()[:60] for o in options if str(o).strip()]
    db.session.add(td)
    db.session.commit()
    _log_audit('create_tag_def', field='key', new_val=key)
    return jsonify({'success': True, 'tag_def': td.to_dict()}), 201


@app.route('/api/tag-defs/<int:tid>', methods=['PUT'])
@require_auth
@require_role('admin', 'manager')
def update_tag_def(tid):
    td = TagDefinition.query.get(tid)
    if not td:
        return jsonify({'error': 'Not found'}), 404
    data = request.json or {}
    if 'label' in data:
        td.label = str(data['label']).strip()[:120]
    if 'field_type' in data and data['field_type'] in TagDefinition.FIELD_TYPES and not td.is_builtin:
        td.field_type = data['field_type']
    if 'options' in data and isinstance(data['options'], list):
        td.options = [str(o).strip()[:60] for o in data['options'] if str(o).strip()]
    if 'is_required' in data:
        td.is_required = bool(data['is_required'])
    if 'sort_order' in data:
        td.sort_order = int(data['sort_order'] or 0)
    db.session.commit()
    return jsonify({'success': True, 'tag_def': td.to_dict()})


@app.route('/api/tag-defs/<int:tid>', methods=['DELETE'])
@require_auth
@require_role('admin')
def delete_tag_def(tid):
    td = TagDefinition.query.get(tid)
    if not td:
        return jsonify({'error': 'Not found'}), 404
    if td.is_builtin:
        return jsonify({'error': 'Built-in fields cannot be deleted'}), 400
    db.session.delete(td)
    db.session.commit()
    return jsonify({'success': True})


# ─── WhatsApp Integration ──────────────────────────────────────────

@app.route('/api/whatsapp/status')
def wa_status():
    import whatsapp as wa
    return jsonify(wa.get_provider_status())


@app.route('/api/whatsapp/templates')
def wa_templates():
    """Merge built-in templates from whatsapp.py with user-created
    MessageTemplate rows. Returns a flat list (for the outreach UI)."""
    import whatsapp as wa
    out = []
    seen = set()
    # DB rows take precedence (they include the built-ins seeded at startup)
    for t in MessageTemplate.query.order_by(MessageTemplate.is_builtin.desc(), MessageTemplate.label).all():
        seen.add(t.key)
        out.append(t.to_dict())
    # Any provider builtin not in DB yet (defensive)
    for k, v in wa.get_templates().items():
        if k in seen:
            continue
        out.append({'key': k, 'label': v.get('label', k), 'channel': 'whatsapp',
                    'body': '', 'params': v.get('params', []), 'is_builtin': True})
    return jsonify(out)


@app.route('/api/whatsapp/send', methods=['POST'])
@require_auth
@require_role('admin', 'manager')
def wa_send():
    import whatsapp as wa
    data = request.json or {}
    phone = data.get('phone', '')
    template = data.get('template', '')
    params = data.get('params', {})

    result = wa.send_message(phone, template, params)

    # Log message in DB
    if result.get('success'):
        msg = WhatsAppMessage(
            voter_id=data.get('voter_db_id', 0),
            phone=phone,
            template=template,
            message_id=result.get('message_id', ''),
            status='sent',
            sent_at=datetime.now(timezone.utc),
        )
        db.session.add(msg)
        db.session.commit()

    return jsonify(result)


@app.route('/api/whatsapp/campaign', methods=['POST'])
@require_auth
@require_role('admin', 'manager')
def wa_campaign():
    import whatsapp as wa
    data = request.json or {}
    template = data.get('template', '')
    common_params = data.get('params', {})
    filters = data.get('filters', {})
    campaign_name = data.get('name', f'Campaign {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    # Build recipient list from current STORE voters
    voters = STORE.get('voters', [])
    recipients = []
    for v in voters:
        phone = v.get('phone', '')
        if not wa.validate_phone(phone):
            continue
        if not v.get('whatsapp_consent', False) and not filters.get('skip_consent'):
            continue
        # Apply filters
        if filters.get('booth') and str(v.get('part_no', '')) != filters['booth']:
            continue
        if filters.get('classification') and v.get('classification', '').lower() != filters['classification'].lower():
            continue
        if filters.get('community') and v.get('community', '').lower() != filters['community'].lower():
            continue
        if filters.get('tag') and filters['tag'] not in (v.get('tags') or []):
            continue
        recipients.append({
            'phone': phone,
            'name': v.get('name', ''),
            'booth_no': str(v.get('part_no', '')),
        })

    if not recipients:
        return jsonify({'error': 'No recipients match filters (need phone + consent)'}), 400

    # Create campaign record
    campaign = WhatsAppCampaign(
        name=campaign_name,
        template=template,
        target_count=len(recipients),
        status='sending',
        created_by=getattr(g, 'user_id', None),
    )
    campaign.filters_json = json.dumps(filters, ensure_ascii=False)
    db.session.add(campaign)
    db.session.commit()

    # Send messages
    result = wa.send_bulk(recipients, template, common_params)

    # Update campaign stats
    campaign.sent = result.get('sent', 0)
    campaign.failed = result.get('failed', 0)
    campaign.status = 'completed'
    db.session.commit()

    _log_audit('whatsapp_campaign', field='template', new_val=f'{template} → {len(recipients)} recipients')

    return jsonify({
        'success': True,
        'campaign_id': campaign.id,
        'target_count': len(recipients),
        'sent': result.get('sent', 0),
        'failed': result.get('failed', 0),
        'errors': result.get('errors', []),
    })


@app.route('/api/whatsapp/campaigns')
@require_auth
@require_role('admin', 'manager', 'candidate')
def wa_campaigns():
    campaigns = WhatsAppCampaign.query.order_by(WhatsAppCampaign.created_at.desc()).limit(50).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'template': c.template,
        'target_count': c.target_count,
        'sent': c.sent,
        'delivered': c.delivered,
        'read': c.read,
        'failed': c.failed,
        'status': c.status,
        'created_at': c.created_at.isoformat() if c.created_at else '',
    } for c in campaigns])


@app.route('/api/whatsapp/webhook', methods=['POST'])
def wa_webhook():
    """Webhook for WhatsApp delivery status updates."""
    data = request.json or {}
    # Handle Meta/Twilio webhook payload
    statuses = data.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('statuses', [])
    for s in statuses:
        msg_id = s.get('id', '')
        status = s.get('status', '')
        msg = WhatsAppMessage.query.filter_by(message_id=msg_id).first()
        if msg:
            msg.status = status
            if status == 'delivered':
                msg.delivered_at = datetime.now(timezone.utc)
            elif status == 'read':
                msg.read_at = datetime.now(timezone.utc)
            elif status == 'failed':
                msg.error = s.get('errors', [{}])[0].get('message', '')
    db.session.commit()

    # Update campaign counters
    for s in statuses:
        msg = WhatsAppMessage.query.filter_by(message_id=s.get('id', '')).first()
        if msg and msg.campaign_id:
            camp = WhatsAppCampaign.query.get(msg.campaign_id)
            if camp:
                camp.delivered = WhatsAppMessage.query.filter_by(campaign_id=camp.id, status='delivered').count()
                camp.read = WhatsAppMessage.query.filter_by(campaign_id=camp.id, status='read').count()
                camp.failed = WhatsAppMessage.query.filter_by(campaign_id=camp.id, status='failed').count()
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/whatsapp/stats')
def wa_stats():
    total = WhatsAppMessage.query.count()
    sent = WhatsAppMessage.query.filter_by(status='sent').count()
    delivered = WhatsAppMessage.query.filter_by(status='delivered').count()
    read = WhatsAppMessage.query.filter_by(status='read').count()
    failed = WhatsAppMessage.query.filter_by(status='failed').count()
    campaigns = WhatsAppCampaign.query.count()
    return jsonify({
        'total_messages': total,
        'sent': sent,
        'delivered': delivered,
        'read': read,
        'failed': failed,
        'total_campaigns': campaigns,
    })


# ─── Message Templates (user-creatable) ────────────────────────────

def _render_template_body(tpl, params):
    """Render a MessageTemplate body with params dict. Missing keys render as ''."""
    body = tpl.body or ''
    try:
        class _D(dict):
            def __missing__(self, k):
                return ''
        return body.format_map(_D(params or {}))
    except Exception:
        return body


@app.route('/api/templates', methods=['GET'])
@require_auth
def templates_list():
    channel = request.args.get('channel')
    q = MessageTemplate.query
    if channel:
        q = q.filter_by(channel=channel)
    rows = q.order_by(MessageTemplate.is_builtin.desc(), MessageTemplate.label).all()
    return jsonify([t.to_dict() for t in rows])


@app.route('/api/templates', methods=['POST'])
@require_auth
@require_role('admin', 'manager')
def templates_create():
    data = request.json or {}
    key = (data.get('key') or '').strip().lower()
    label = (data.get('label') or '').strip()
    body = (data.get('body') or '').strip()
    channel = (data.get('channel') or 'whatsapp').strip().lower()
    params = data.get('params') or []
    if not key or not label or not body:
        return jsonify({'error': 'key, label and body are required'}), 400
    if not re.match(r'^[a-z0-9_]{2,40}$', key):
        return jsonify({'error': 'key must be 2-40 chars, lowercase/digits/underscore'}), 400
    if MessageTemplate.query.filter_by(key=key).first():
        return jsonify({'error': f"Template key '{key}' already exists"}), 409
    # Auto-extract placeholders if params not given
    if not params:
        params = sorted(set(re.findall(r'\{(\w+)\}', body)))
    t = MessageTemplate(
        key=key, label=label, channel=channel, body=body,
        is_builtin=False, created_by=getattr(g, 'user_id', None),
    )
    t.params = params if isinstance(params, list) else []
    db.session.add(t)
    db.session.commit()
    _log_audit('create_template', field='key', new_val=key)
    return jsonify({'success': True, 'template': t.to_dict()}), 201


@app.route('/api/templates/<int:tid>', methods=['PUT'])
@require_auth
@require_role('admin', 'manager')
def templates_update(tid):
    t = MessageTemplate.query.get(tid)
    if not t:
        return jsonify({'error': 'Template not found'}), 404
    data = request.json or {}
    if 'label' in data: t.label = str(data['label']).strip()[:120]
    if 'body' in data: t.body = str(data['body'])
    if 'channel' in data: t.channel = str(data['channel']).strip().lower()[:20]
    if 'params' in data and isinstance(data['params'], list):
        t.params = data['params']
    else:
        t.params = sorted(set(re.findall(r'\{(\w+)\}', t.body or '')))
    db.session.commit()
    _log_audit('update_template', field='key', new_val=t.key)
    return jsonify({'success': True, 'template': t.to_dict()})


@app.route('/api/templates/<int:tid>', methods=['DELETE'])
@require_auth
@require_role('admin', 'manager')
def templates_delete(tid):
    t = MessageTemplate.query.get(tid)
    if not t:
        return jsonify({'error': 'Template not found'}), 404
    if t.is_builtin:
        return jsonify({'error': 'Cannot delete built-in template'}), 400
    key = t.key
    db.session.delete(t)
    db.session.commit()
    _log_audit('delete_template', field='key', old_val=key)
    return jsonify({'success': True})


# ─── Outreach (Voters + Karyakartas) ───────────────────────────────

def _load_voters_for_hierarchy(hier_filters, ward_name=None):
    """Walk saved_wards/*.json and return (ward_name, voters_list) for wards
    whose hierarchy matches all provided filters. If ward_name is given, only
    that ward is included. If no filters at all, falls back to the active STORE."""
    hier_filters = {k: v for k, v in (hier_filters or {}).items() if v}
    if not hier_filters and not ward_name:
        return [(_active_ward_name() or 'active', STORE.get('voters', []))]
    results = []
    if not os.path.isdir(SAVE_DIR):
        return results
    for fname in os.listdir(SAVE_DIR):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(SAVE_DIR, fname), 'r', encoding='utf-8') as f:
                snap = json.load(f)
        except Exception:
            continue
        snap_name = snap.get('name') or fname[:-5]
        if ward_name and snap_name.strip().lower() != ward_name.strip().lower():
            continue
        h = snap.get('hierarchy', {}) or {}
        if not all(str(h.get(k, '')).strip().lower() == str(v).strip().lower()
                   for k, v in hier_filters.items()):
            continue
        results.append((snap_name, snap.get('voters', [])))
    return results


def _filter_voters(voters, f):
    """Apply non-hierarchy voter filters: booth, classification, community,
    tag, has_phone, has_whatsapp, consent."""
    out = []
    for v in voters:
        if f.get('booth') and str(v.get('part_no', '')) != str(f['booth']):
            continue
        if f.get('classification') and (v.get('classification', '') or '').lower() != f['classification'].lower():
            continue
        if f.get('community') and (v.get('community', '') or '').lower() != f['community'].lower():
            continue
        if f.get('tag') and f['tag'] not in (v.get('tags') or []):
            continue
        if f.get('require_phone') and not (v.get('whatsapp') or v.get('phone')):
            continue
        if f.get('require_consent') and not v.get('whatsapp_consent'):
            continue
        out.append(v)
    return out


@app.route('/api/outreach/audience', methods=['POST'])
@require_auth
@require_role('admin', 'manager', 'candidate')
def outreach_audience():
    """Preview the audience for a given target_type + filters. Does NOT send."""
    data = request.json or {}
    target = (data.get('target_type') or 'voters').strip().lower()
    filters = data.get('filters') or {}
    hier = filters.get('hierarchy') or {}

    if target == 'karyakartas':
        q = User.query.filter_by(is_active=True)
        if filters.get('role'):
            q = q.filter_by(role=filters['role'])
        if filters.get('assigned_ward'):
            q = q.filter(User.assigned_ward.ilike(filters['assigned_ward']))
        users = q.all()
        # Hierarchy filter — match via the user's ward snapshot
        if hier:
            ward_hier_by_name = {}
            if os.path.isdir(SAVE_DIR):
                for fname in os.listdir(SAVE_DIR):
                    if fname.endswith('.json'):
                        try:
                            with open(os.path.join(SAVE_DIR, fname), 'r', encoding='utf-8') as f:
                                snap = json.load(f)
                            ward_hier_by_name[(snap.get('name') or '').lower()] = snap.get('hierarchy', {}) or {}
                        except Exception:
                            pass
            def _user_matches(u):
                h = ward_hier_by_name.get((u.assigned_ward or '').lower(), {})
                return all(str(h.get(k, '')).strip().lower() == str(v).strip().lower()
                           for k, v in hier.items() if v)
            users = [u for u in users if _user_matches(u)]
        # Reachability counts
        with_phone = sum(1 for u in users if u.whatsapp or u.phone)
        return jsonify({
            'target_type': 'karyakartas',
            'total': len(users),
            'reachable': with_phone,
            'sample': [{
                'id': u.id, 'username': u.username, 'display_name': u.display_name,
                'role': u.role, 'assigned_ward': u.assigned_ward,
                'phone': u.phone, 'whatsapp': u.whatsapp,
            } for u in users[:25]],
        })

    # target == voters
    ward_groups = _load_voters_for_hierarchy(hier, filters.get('assigned_ward'))
    total = 0
    reachable = 0
    by_ward = []
    sample = []
    for ward_name, voters in ward_groups:
        matched = _filter_voters(voters, filters)
        total += len(matched)
        r = sum(1 for v in matched if (v.get('whatsapp') or v.get('phone')))
        reachable += r
        by_ward.append({'ward': ward_name, 'count': len(matched), 'reachable': r})
        for v in matched:
            if len(sample) >= 25:
                break
            sample.append({
                'nqt_id': v.get('nqt_id'), 'name': v.get('name'),
                'part_no': v.get('part_no'), 'phone': v.get('phone'),
                'whatsapp': v.get('whatsapp'), 'consent': v.get('whatsapp_consent'),
                '_ward': ward_name,
            })
    return jsonify({
        'target_type': 'voters',
        'total': total,
        'reachable': reachable,
        'by_ward': by_ward,
        'sample': sample,
    })


@app.route('/api/outreach/send', methods=['POST'])
@require_auth
@require_role('admin', 'manager')
def outreach_send():
    """Send an outreach campaign to voters or karyakartas matching filters.
    Uses a MessageTemplate (by id or key). Stores a WhatsAppCampaign record."""
    import whatsapp as wa
    data = request.json or {}
    target = (data.get('target_type') or 'voters').strip().lower()
    filters = data.get('filters') or {}
    hier = filters.get('hierarchy') or {}
    campaign_name = (data.get('name') or f'Outreach {datetime.now().strftime("%Y-%m-%d %H:%M")}').strip()
    common_params = data.get('params') or {}

    # Resolve template
    tpl = None
    if data.get('template_id'):
        tpl = MessageTemplate.query.get(int(data['template_id']))
    elif data.get('template'):
        tpl = MessageTemplate.query.filter_by(key=str(data['template']).strip().lower()).first()
    if not tpl:
        return jsonify({'error': 'Template not found (pass template_id or template key)'}), 400

    # Build recipients
    recipients = []
    if target == 'karyakartas':
        q = User.query.filter_by(is_active=True)
        if filters.get('role'):
            q = q.filter_by(role=filters['role'])
        if filters.get('assigned_ward'):
            q = q.filter(User.assigned_ward.ilike(filters['assigned_ward']))
        users = q.all()
        if hier:
            ward_hier_by_name = {}
            if os.path.isdir(SAVE_DIR):
                for fname in os.listdir(SAVE_DIR):
                    if fname.endswith('.json'):
                        try:
                            with open(os.path.join(SAVE_DIR, fname), 'r', encoding='utf-8') as f:
                                snap = json.load(f)
                            ward_hier_by_name[(snap.get('name') or '').lower()] = snap.get('hierarchy', {}) or {}
                        except Exception:
                            pass
            def _um(u):
                h = ward_hier_by_name.get((u.assigned_ward or '').lower(), {})
                return all(str(h.get(k, '')).strip().lower() == str(v).strip().lower()
                           for k, v in hier.items() if v)
            users = [u for u in users if _um(u)]
        for u in users:
            phone = u.whatsapp or u.phone
            if not wa.validate_phone(phone):
                continue
            recipients.append({
                '_phone': phone, '_label': u.display_name or u.username,
                'name': u.display_name or u.username,
                'ward': u.assigned_ward or '', 'role': u.role,
            })
    else:
        # voters across selected hierarchy
        ward_groups = _load_voters_for_hierarchy(hier, filters.get('assigned_ward'))
        for ward_name, voters in ward_groups:
            matched = _filter_voters(voters, {**filters, 'require_phone': True})
            for v in matched:
                phone = v.get('whatsapp') or v.get('phone') or ''
                if not wa.validate_phone(phone):
                    continue
                if not v.get('whatsapp_consent') and not filters.get('skip_consent'):
                    continue
                recipients.append({
                    '_phone': phone, '_label': v.get('name', ''),
                    'name': v.get('name', ''),
                    'booth_no': str(v.get('part_no', '')),
                    'ward': ward_name,
                })

    if not recipients:
        return jsonify({'error': 'No recipients match filters (need phone, plus consent for voters unless skip_consent=true)'}), 400

    # Dry run mode — return list without sending
    if data.get('dry_run'):
        return jsonify({
            'success': True, 'dry_run': True,
            'target_count': len(recipients),
            'sample': recipients[:25],
        })

    # Create campaign record
    campaign = WhatsAppCampaign(
        name=campaign_name, template=tpl.key,
        target_count=len(recipients), status='sending',
        created_by=getattr(g, 'user_id', None),
    )
    campaign.filters_json = json.dumps({'target_type': target, **filters}, ensure_ascii=False)
    db.session.add(campaign)
    db.session.commit()

    sent = 0; failed = 0; errors = []
    for i, r in enumerate(recipients):
        body = _render_template_body(tpl, {**common_params, **{k: v for k, v in r.items() if not k.startswith('_')}})
        result = wa.send_rendered(r['_phone'], body)
        if result.get('success'):
            sent += 1
        else:
            failed += 1
            if len(errors) < 10:
                errors.append({'to': r['_label'], 'error': result.get('error', '')})

    campaign.sent = sent
    campaign.failed = failed
    campaign.status = 'completed'
    db.session.commit()
    _log_audit('outreach_campaign', field='template',
               new_val=f"{tpl.key} → {target} × {len(recipients)} ({sent} sent / {failed} failed)")
    return jsonify({
        'success': True, 'campaign_id': campaign.id,
        'target_count': len(recipients), 'sent': sent, 'failed': failed,
        'errors': errors,
    })


# ─── Work Assignments ──────────────────────────────────────────────

WORK_TYPES = ('page_coverage', 'voter_contact', 'slip_delivery', 'survey', 'event', 'custom')


def _work_to_dict(w, include_metrics=True):
    d = w.to_dict()
    user = User.query.get(w.karyakarta_id)
    d['karyakarta'] = {
        'id': user.id, 'username': user.username,
        'display_name': user.display_name or user.username,
        'role': user.role, 'phone': user.phone, 'whatsapp': user.whatsapp,
    } if user else None
    if include_metrics and w.work_type in ('page_coverage', 'voter_contact', 'slip_delivery'):
        # Pull voter_count + observed metrics from saved snapshot
        voters = []
        if w.ward_name:
            safe = _safe_ward_filename(w.ward_name)
            fpath = os.path.join(SAVE_DIR, safe + '.json')
            if os.path.isfile(fpath):
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        voters = json.load(f).get('voters', [])
                except Exception:
                    pass
        elif _wards_match(w.ward_name, _active_ward_name()):
            voters = STORE.get('voters', [])
        page_set = set(w.pages)
        scope = [v for v in voters if not page_set or v.get('page_no') in page_set]
        total_voters = len(scope)
        contacted = sum(1 for v in scope if (v.get('contact_count') or 0) > 0)
        slip = sum(1 for v in scope if v.get('slip_delivered'))
        voted = sum(1 for v in scope if v.get('voted'))
        d['metrics'] = {
            'voters_in_scope': total_voters,
            'contacted': contacted,
            'slip_delivered': slip,
            'voted': voted,
            'percent_contacted': round(100 * contacted / total_voters, 1) if total_voters else 0,
            'percent_slip': round(100 * slip / total_voters, 1) if total_voters else 0,
            'percent_voted': round(100 * voted / total_voters, 1) if total_voters else 0,
        }
        # Auto-completion check
        if w.target_count and (w.progress_count >= w.target_count or contacted >= w.target_count):
            d['target_met'] = True
    return d


@app.route('/api/work', methods=['GET'])
@require_auth
def work_list():
    """List work items. Filters: karyakarta_id, status, work_type, ward."""
    q = WorkAssignment.query
    if request.args.get('karyakarta_id'):
        q = q.filter_by(karyakarta_id=int(request.args['karyakarta_id']))
    if request.args.get('status'):
        q = q.filter_by(status=request.args['status'])
    if request.args.get('work_type'):
        q = q.filter_by(work_type=request.args['work_type'])
    if request.args.get('ward'):
        q = q.filter(WorkAssignment.ward_name.ilike(request.args['ward']))
    # Karyakarta role: only see their own assignments
    if g.role in ('karyakarta', 'booth_agent'):
        q = q.filter_by(karyakarta_id=g.user_id)
    items = q.order_by(WorkAssignment.created_at.desc()).all()
    return jsonify([_work_to_dict(w) for w in items])


@app.route('/api/work', methods=['POST'])
@require_auth
@require_role('admin', 'manager')
def work_create():
    data = request.json or {}
    karyakarta_id = data.get('karyakarta_id')
    if not karyakarta_id:
        return jsonify({'error': 'karyakarta_id required'}), 400
    user = User.query.get(int(karyakarta_id))
    if not user:
        return jsonify({'error': 'Karyakarta not found'}), 404
    work_type = (data.get('work_type') or 'page_coverage').strip()
    if work_type not in WORK_TYPES:
        return jsonify({'error': f'work_type must be one of: {", ".join(WORK_TYPES)}'}), 400
    ward_name = (data.get('ward_name') or '').strip()
    pages = data.get('pages') or []
    # Validate pages exist in the saved ward snapshot for page-based work
    if work_type in ('page_coverage', 'voter_contact', 'slip_delivery') and pages and ward_name:
        safe = _safe_ward_filename(ward_name)
        fpath = os.path.join(SAVE_DIR, safe + '.json')
        valid_pages = None
        if os.path.isfile(fpath):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    valid_pages = {v.get('page_no') for v in json.load(f).get('voters', []) if v.get('page_no')}
            except Exception:
                pass
        elif _wards_match(ward_name, _active_ward_name()):
            valid_pages = {v.get('page_no') for v in STORE['voters'] if v.get('page_no')}
        if valid_pages is None:
            return jsonify({'error': f"No saved snapshot for ward '{ward_name}'."}), 400
        invalid = [p for p in pages if p not in valid_pages]
        if invalid:
            return jsonify({'error': f"Pages not in ward '{ward_name}': {invalid[:10]}"}), 400

    deadline = None
    if data.get('deadline'):
        try:
            deadline = datetime.fromisoformat(str(data['deadline']).replace('Z', '+00:00'))
        except Exception:
            return jsonify({'error': 'deadline must be ISO datetime'}), 400

    w = WorkAssignment(
        karyakarta_id=int(karyakarta_id),
        work_type=work_type,
        title=(data.get('title') or '').strip()[:200],
        description=(data.get('description') or '').strip(),
        ward_name=ward_name,
        target_count=int(data.get('target_count') or 0),
        deadline=deadline,
        status='assigned',
        assigned_by=getattr(g, 'user_id', None),
    )
    if isinstance(pages, list):
        w.pages = pages
    db.session.add(w)
    db.session.commit()
    _log_audit('create_work', field='work_type',
               new_val=f'{work_type} → user#{karyakarta_id} ({len(pages)} pages)')
    return jsonify({'success': True, 'work': _work_to_dict(w)}), 201


@app.route('/api/work/<int:wid>', methods=['PUT'])
@require_auth
def work_update(wid):
    """Karyakartas can update progress fields on their own work; admin/manager
    can edit anything."""
    w = WorkAssignment.query.get(wid)
    if not w:
        return jsonify({'error': 'Work not found'}), 404
    is_owner = (g.user_id == w.karyakarta_id)
    is_admin = g.role in ('admin', 'manager')
    if not (is_owner or is_admin):
        return jsonify({'error': 'Not authorized'}), 403

    data = request.json or {}
    own_fields = {'status', 'progress_count', 'progress_notes'}
    admin_fields = {'title', 'description', 'work_type', 'ward_name', 'target_count',
                    'deadline', 'pages'}
    allowed = (own_fields | admin_fields) if is_admin else own_fields

    for k in list(data.keys()):
        if k not in allowed:
            continue
        if k == 'status':
            v = str(data[k]).strip()
            if v not in ('assigned', 'in_progress', 'completed', 'cancelled'):
                continue
            w.status = v
            if v == 'completed' and not w.completed_at:
                w.completed_at = datetime.now(timezone.utc)
        elif k == 'progress_count':
            try: w.progress_count = int(data[k])
            except Exception: pass
        elif k == 'pages' and isinstance(data[k], list):
            w.pages = data[k]
        elif k == 'target_count':
            try: w.target_count = int(data[k])
            except Exception: pass
        elif k == 'deadline':
            try: w.deadline = datetime.fromisoformat(str(data[k]).replace('Z', '+00:00')) if data[k] else None
            except Exception: pass
        elif k == 'work_type':
            v = str(data[k]).strip()
            if v in WORK_TYPES: w.work_type = v
        else:
            setattr(w, k, str(data[k]) if data[k] is not None else '')
    db.session.commit()
    _log_audit('update_work', field='id', new_val=str(wid))
    return jsonify({'success': True, 'work': _work_to_dict(w)})


@app.route('/api/work/<int:wid>', methods=['DELETE'])
@require_auth
@require_role('admin', 'manager')
def work_delete(wid):
    w = WorkAssignment.query.get(wid)
    if not w:
        return jsonify({'error': 'Work not found'}), 404
    db.session.delete(w)
    db.session.commit()
    _log_audit('delete_work', field='id', old_val=str(wid))
    return jsonify({'success': True})


@app.route('/api/work/summary', methods=['GET'])
@require_auth
@require_role('admin', 'manager', 'candidate')
def work_summary():
    """Roll-up across all work items, plus per-karyakarta progress rows."""
    items = WorkAssignment.query.all()
    by_status = {s: 0 for s in ('assigned', 'in_progress', 'completed', 'cancelled')}
    by_type = {}
    for w in items:
        by_status[w.status] = by_status.get(w.status, 0) + 1
        by_type[w.work_type] = by_type.get(w.work_type, 0) + 1
    # Per-karyakarta roll-up
    rows = []
    user_ids = sorted({w.karyakarta_id for w in items})
    for uid in user_ids:
        u = User.query.get(uid)
        if not u: continue
        u_items = [w for w in items if w.karyakarta_id == uid]
        completed = sum(1 for w in u_items if w.status == 'completed')
        in_prog = sum(1 for w in u_items if w.status == 'in_progress')
        target_total = sum(w.target_count for w in u_items)
        progress_total = sum(w.progress_count for w in u_items)
        rows.append({
            'karyakarta_id': uid,
            'name': u.display_name or u.username,
            'role': u.role,
            'assigned_ward': u.assigned_ward,
            'total_work': len(u_items),
            'completed': completed,
            'in_progress': in_prog,
            'target_total': target_total,
            'progress_total': progress_total,
            'percent': round(100 * progress_total / target_total, 1) if target_total else 0,
        })
    rows.sort(key=lambda r: r['percent'], reverse=True)
    return jsonify({
        'total': len(items), 'by_status': by_status, 'by_type': by_type,
        'per_karyakarta': rows,
    })


# ─── Offline Sync (PWA) ────────────────────────────────────────────

@app.route('/api/sync', methods=['POST'])
def sync_offline_changes():
    """Sync queued offline changes from PWA."""
    data = request.json or {}
    changes = data.get('changes', [])
    synced = 0
    errors = []

    for change in changes:
        try:
            action = change.get('action', '')
            nqt_id = change.get('nqt_id', '')

            voter = next((v for v in STORE['voters'] if v.get('nqt_id') == nqt_id), None)
            if not voter:
                errors.append(f'Voter {nqt_id} not found')
                continue

            if action == 'update':
                updates = change.get('updates', {})
                allowed = ['classification', 'sentiment', 'contact_count', 'slip_delivered',
                           'voted', 'notes', 'caste', 'party_lean']
                for key in allowed:
                    if key in updates:
                        voter[key] = updates[key]
                synced += 1
            elif action == 'contact':
                voter['contact_count'] = voter.get('contact_count', 0) + 1
                synced += 1
            elif action == 'voted':
                voter['voted'] = True
                synced += 1
        except Exception as e:
            errors.append(str(e))

    return jsonify({
        'success': True,
        'synced': synced,
        'failed': len(errors),
        'errors': errors[:10],
    })


# ─── DB Ward Operations ────────────────────────────────────────────

@app.route('/api/db/wards')
def db_list_wards():
    """List wards from database."""
    wards = Ward.query.order_by(Ward.name).all()
    return jsonify([w.to_summary() for w in wards])


@app.route('/api/db/ward/<int:ward_id>/voters')
def db_ward_voters(ward_id):
    """Get voters from a DB ward."""
    ward = Ward.query.get(ward_id)
    if not ward:
        return jsonify({'error': 'Ward not found'}), 404
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    voters_q = Voter.query.filter_by(ward_id=ward_id)

    search = request.args.get('search', '').strip().lower()
    if search:
        voters_q = voters_q.filter(
            db.or_(Voter.name.ilike(f'%{search}%'), Voter.voter_id.ilike(f'%{search}%'))
        )

    total = voters_q.count()
    voters = voters_q.offset((page-1)*per_page).limit(per_page).all()
    return jsonify({
        'voters': [v.to_dict() for v in voters],
        'total': total,
        'page': page,
        'per_page': per_page,
    })


# ─── Main ───────────────────────────────────────────────────────────

if __name__ == '__main__':
    host = os.environ.get('EI_HOST', '127.0.0.1')
    port = int(os.environ.get('EI_PORT', '5001'))
    debug = os.environ.get('EI_DEBUG', '1') == '1'
    print(f"\n  Election Intelligence Tool")
    print(f"  http://{host}:{port}\n")
    app.run(host=host, port=port, debug=debug)
