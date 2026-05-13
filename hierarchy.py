"""
Hierarchy manager for Election Intelligence.
Organizes ward data across administrative levels:
Ward < Village < Gram Panchayat < Hobli < Taluka < District < Division < State < Region
"""

import os
import json

LEVELS = ['region', 'state', 'division', 'district', 'taluka', 'hobli', 'gram_panchayat', 'village']
LEVEL_LABELS = {
    'root': 'All Data',
    'region': 'Region',
    'state': 'State',
    'division': 'Division',
    'district': 'District',
    'taluka': 'Taluka',
    'hobli': 'Hobli',
    'gram_panchayat': 'Gram Panchayat',
    'village': 'Village',
    'ward': 'Ward',
}

SAVE_DIR = os.path.join(os.path.dirname(__file__), 'saved_wards')


def get_all_wards():
    """Load summary info from all saved wards (DB first, then JSON files fallback)."""
    # Try database first
    try:
        from database import Ward
        db_wards = Ward.query.all()
        if db_wards:
            return [w.to_summary() for w in db_wards]
    except Exception:
        pass

    # Fallback: read from saved_wards/ JSON files
    wards = []
    if not os.path.isdir(SAVE_DIR):
        return wards
    for fname in sorted(os.listdir(SAVE_DIR)):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(SAVE_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            wards.append({
                'name': data.get('ward_name', fname[:-5]),
                'file': fname[:-5],
                'hierarchy': data.get('hierarchy', {}),
                'total_voters': len(data.get('voters', [])),
                'saved_at': data.get('saved_at', ''),
            })
        except Exception:
            pass
    return wards


def build_tree():
    """Build hierarchy tree from all saved wards."""
    wards = get_all_wards()
    tree = {
        'name': 'All Data', 'level': 'root',
        'children': {}, 'ward_count': 0, 'voter_count': 0,
    }

    for w in wards:
        h = w.get('hierarchy', {})
        node = tree
        for level in LEVELS:
            val = (h.get(level) or '').strip()
            if not val:
                continue
            if val not in node['children']:
                node['children'][val] = {
                    'name': val, 'level': level,
                    'children': {}, 'ward_count': 0, 'voter_count': 0,
                }
            node = node['children'][val]

        # Add ward as leaf
        ward_name = w['name']
        node['children'][ward_name] = {
            'name': ward_name, 'level': 'ward',
            'file': w['file'], 'total_voters': w['total_voters'],
            'saved_at': w['saved_at'],
            'children': {}, 'ward_count': 1, 'voter_count': w['total_voters'],
        }

    _rollup_counts(tree)
    return _serialize(tree)


def _rollup_counts(node):
    """Recursively compute ward_count and voter_count."""
    if node['level'] == 'ward':
        return node.get('ward_count', 1), node.get('voter_count', 0)
    total_w, total_v = 0, 0
    for child in node['children'].values():
        w, v = _rollup_counts(child)
        total_w += w
        total_v += v
    node['ward_count'] = total_w
    node['voter_count'] = total_v
    return total_w, total_v


def _serialize(node):
    """Convert tree to JSON-serializable format."""
    result = {
        'name': node['name'],
        'level': node['level'],
        'level_label': LEVEL_LABELS.get(node['level'], node['level'].replace('_', ' ').title()),
        'ward_count': node['ward_count'],
        'voter_count': node['voter_count'],
    }
    if node['level'] == 'ward':
        result['file'] = node.get('file', '')
        result['saved_at'] = node.get('saved_at', '')
    children = sorted(node['children'].values(),
                      key=lambda c: (0 if c['level'] != 'ward' else 1, c['name']))
    result['children'] = [_serialize(c) for c in children]
    return result


def find_ward_files(level, value, path=None):
    """Find all ward files matching a hierarchy filter.

    level: 'state', 'district', ..., 'ward', or 'root'
    value: the name to match at that level
    path: dict of ancestor levels e.g. {'state':'Karnataka','district':'Kalaburagi'}
    """
    wards = get_all_wards()
    matching = []

    for w in wards:
        h = w.get('hierarchy', {})

        # Check that all ancestor levels match
        if path:
            ok = True
            for k, v in path.items():
                if (h.get(k) or '').strip() != v:
                    ok = False
                    break
            if not ok:
                continue

        if level == 'root':
            matching.append(w['file'])
        elif level == 'ward':
            if w['name'] == value or w['file'] == value:
                matching.append(w['file'])
        else:
            if (h.get(level) or '').strip() == value:
                matching.append(w['file'])

    return matching


def load_combined_voters(ward_files):
    """Load and combine voters from multiple ward files.
    Returns (voters_list, combined_metadata, combined_election_history).
    """
    all_voters = []
    all_history = []
    combined_meta = {}
    ward_names = []

    for wf in ward_files:
        voters = []
        meta = {}
        ward_name = wf
        hierarchy = {}
        election_history = []

        # Try JSON file first
        fpath = os.path.join(SAVE_DIR, wf + '.json')
        if os.path.isfile(fpath):
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            voters = data.get('voters', [])
            meta = data.get('metadata', {})
            ward_name = data.get('ward_name', wf)
            hierarchy = data.get('hierarchy', {})
            election_history = data.get('election_history', [])
        else:
            # Fallback: load from database
            try:
                from database import Ward as WardModel
                db_ward = WardModel.query.filter_by(file_key=wf).first()
                if db_ward:
                    voters = [v.to_dict() for v in db_ward.voters.all()]
                    meta = db_ward.ward_metadata
                    ward_name = db_ward.name
                    hierarchy = db_ward.hierarchy
                    election_history = [h.to_dict() for h in db_ward.history.all()]
                else:
                    continue
            except Exception:
                continue

        ward_names.append(ward_name)

        # Tag each voter with their ward source
        for v in voters:
            v['_ward'] = ward_name

        all_voters.extend(voters)
        all_history.extend(election_history)

        # Merge metadata (keep first non-empty value for each key)
        for k, val in meta.items():
            if k not in combined_meta or not combined_meta[k]:
                combined_meta[k] = val

        # Merge hierarchy info into metadata for reporting
        for k, val in hierarchy.items():
            meta_key = f'_h_{k}'
            if meta_key not in combined_meta or not combined_meta[meta_key]:
                combined_meta[meta_key] = val

    combined_meta['_ward_names'] = ward_names
    combined_meta['_ward_count'] = len(ward_names)

    return all_voters, combined_meta, all_history
