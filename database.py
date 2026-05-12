"""
Election Intelligence - Database Models (SQLAlchemy)
SQLite by default, PostgreSQL via DATABASE_URL env var.
"""

import os
import json
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ── Models ───────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(120), nullable=False, default='')
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='karyakarta')
    is_active = db.Column(db.Boolean, default=True)
    phone = db.Column(db.String(15), default='')
    whatsapp = db.Column(db.String(15), default='')
    socials_json = db.Column(db.Text, default='{}')  # {facebook,instagram,twitter,telegram,youtube,other}
    surname = db.Column(db.String(60), default='')
    location_details = db.Column(db.Text, default='')  # free-form (street, booth, GPS, etc.)
    home_state = db.Column(db.String(60), default='')
    home_district = db.Column(db.String(60), default='')
    home_taluka = db.Column(db.String(60), default='')
    home_village = db.Column(db.String(60), default='')
    assigned_ward = db.Column(db.String(120), default='')  # ward file_key the user is responsible for
    assigned_pages_json = db.Column(db.Text, default='[]')  # list[int] PDF page numbers
    assigned_booths_json = db.Column(db.Text, default='[]')  # list[str] part_no values
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime, nullable=True)

    ROLES = ('admin', 'candidate', 'manager', 'booth_agent', 'karyakarta')

    @property
    def assigned_pages(self):
        try:
            v = json.loads(self.assigned_pages_json or '[]')
            return [int(x) for x in v if str(x).strip()]
        except Exception:
            return []

    @assigned_pages.setter
    def assigned_pages(self, val):
        cleaned = []
        for x in (val or []):
            try:
                cleaned.append(int(x))
            except (TypeError, ValueError):
                continue
        self.assigned_pages_json = json.dumps(sorted(set(cleaned)), ensure_ascii=False)

    @property
    def assigned_booths(self):
        try:
            v = json.loads(self.assigned_booths_json or '[]')
            return [str(x).strip() for x in v if str(x).strip()]
        except Exception:
            return []

    @assigned_booths.setter
    def assigned_booths(self, val):
        cleaned = []
        for x in (val or []):
            s = str(x).strip()
            if s:
                cleaned.append(s)
        self.assigned_booths_json = json.dumps(sorted(set(cleaned)), ensure_ascii=False)

    @property
    def socials(self):
        try:
            v = json.loads(self.socials_json or '{}')
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    @socials.setter
    def socials(self, val):
        if not isinstance(val, dict):
            val = {}
        # keep only string values for known keys + arbitrary extras
        clean = {k: str(v).strip() for k, v in val.items() if v is not None}
        self.socials_json = json.dumps(clean, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'display_name': self.display_name,
            'role': self.role,
            'is_active': self.is_active,
            'phone': self.phone,
            'whatsapp': self.whatsapp,
            'socials': self.socials,
            'surname': self.surname,
            'location_details': self.location_details,
            'home_state': self.home_state,
            'home_district': self.home_district,
            'home_taluka': self.home_taluka,
            'home_village': self.home_village,
            'assigned_ward': self.assigned_ward,
            'assigned_pages': self.assigned_pages,
            'assigned_booths': self.assigned_booths,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }


class Ward(db.Model):
    __tablename__ = 'wards'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    file_key = db.Column(db.String(120), unique=True, nullable=False)
    hierarchy_json = db.Column(db.Text, default='{}')
    source_filename = db.Column(db.String(200), default='')
    metadata_json = db.Column(db.Text, default='{}')
    saved_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    voters = db.relationship('Voter', backref='ward', lazy='dynamic', cascade='all,delete-orphan')
    history = db.relationship('ElectionHistory', backref='ward', lazy='dynamic', cascade='all,delete-orphan')

    @property
    def hierarchy(self):
        try:
            return json.loads(self.hierarchy_json or '{}')
        except Exception:
            return {}

    @hierarchy.setter
    def hierarchy(self, val):
        self.hierarchy_json = json.dumps(val, ensure_ascii=False)

    @property
    def ward_metadata(self):
        try:
            return json.loads(self.metadata_json or '{}')
        except Exception:
            return {}

    @ward_metadata.setter
    def ward_metadata(self, val):
        self.metadata_json = json.dumps(val, ensure_ascii=False)

    def to_summary(self):
        return {
            'name': self.name,
            'file': self.file_key,
            'hierarchy': self.hierarchy,
            'total_voters': self.voters.count(),
            'saved_at': self.saved_at.isoformat() if self.saved_at else '',
        }


class Voter(db.Model):
    __tablename__ = 'voters'
    id = db.Column(db.Integer, primary_key=True)
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False, index=True)
    nqt_id = db.Column(db.String(40), nullable=False, index=True)
    voter_id = db.Column(db.String(30), default='')
    name = db.Column(db.String(120), default='')
    father_name = db.Column(db.String(120), default='')
    age = db.Column(db.Integer, default=0)
    gender = db.Column(db.String(10), default='')
    house_no = db.Column(db.String(30), default='')
    sr_no = db.Column(db.String(10), default='')
    part_no = db.Column(db.String(10), default='')
    address = db.Column(db.String(300), default='')
    surname = db.Column(db.String(60), default='')
    community = db.Column(db.String(60), default='')
    family_id = db.Column(db.String(40), default='')
    family_size = db.Column(db.Integer, default=0)
    is_first_time = db.Column(db.Boolean, default=False)
    is_youth = db.Column(db.Boolean, default=False)
    is_senior = db.Column(db.Boolean, default=False)
    is_very_old = db.Column(db.Boolean, default=False)
    needs_transport = db.Column(db.Boolean, default=False)
    classification = db.Column(db.String(20), default='Unclassified')
    sentiment = db.Column(db.String(20), default='')
    influence_score = db.Column(db.Float, default=0.0)
    contact_count = db.Column(db.Integer, default=0)
    is_beneficiary = db.Column(db.Boolean, default=False)
    is_migrated = db.Column(db.Boolean, default=False)
    slip_delivered = db.Column(db.Boolean, default=False)
    voted = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text, default='')
    caste = db.Column(db.String(60), default='')
    party_lean = db.Column(db.String(30), default='')
    tags_json = db.Column(db.Text, default='[]')
    phone = db.Column(db.String(15), default='')
    whatsapp = db.Column(db.String(15), default='')
    whatsapp_consent = db.Column(db.Boolean, default=False)
    socials_json = db.Column(db.Text, default='{}')  # {facebook,instagram,twitter,telegram,youtube,other}

    # Unique within a ward
    __table_args__ = (db.UniqueConstraint('ward_id', 'nqt_id', name='uq_ward_voter'),)

    # All voter dict keys for import/export
    _DICT_FIELDS = [
        'nqt_id', 'voter_id', 'name', 'father_name', 'age', 'gender', 'house_no',
        'sr_no', 'part_no', 'address', 'surname', 'community', 'family_id', 'family_size',
        'is_first_time', 'is_youth', 'is_senior', 'is_very_old', 'needs_transport',
        'classification', 'sentiment', 'influence_score', 'contact_count',
        'is_beneficiary', 'is_migrated', 'slip_delivered', 'voted', 'notes',
        'caste', 'party_lean', 'phone', 'whatsapp', 'whatsapp_consent',
    ]

    @property
    def tags(self):
        try:
            return json.loads(self.tags_json or '[]')
        except Exception:
            return []

    @tags.setter
    def tags(self, val):
        self.tags_json = json.dumps(val, ensure_ascii=False)

    @property
    def socials(self):
        try:
            v = json.loads(self.socials_json or '{}')
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    @socials.setter
    def socials(self, val):
        if not isinstance(val, dict):
            val = {}
        clean = {k: str(v).strip() for k, v in val.items() if v is not None}
        self.socials_json = json.dumps(clean, ensure_ascii=False)

    def to_dict(self, include_ward=False):
        d = {}
        for f in self._DICT_FIELDS:
            d[f] = getattr(self, f, '')
        d['tags'] = self.tags
        d['socials'] = self.socials
        if include_ward and self.ward:
            d['_ward'] = self.ward.name
        return d

    @classmethod
    def from_dict(cls, d, ward_id):
        v = cls(ward_id=ward_id)
        for f in cls._DICT_FIELDS:
            if f in d:
                setattr(v, f, d[f])
        if 'tags' in d:
            v.tags = d['tags'] if isinstance(d['tags'], list) else []
        if 'socials' in d and isinstance(d['socials'], dict):
            v.socials = d['socials']
        return v


class ElectionHistory(db.Model):
    __tablename__ = 'election_history'
    id = db.Column(db.Integer, primary_key=True)
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False, index=True)
    year = db.Column(db.Integer, default=0)
    election_type = db.Column(db.String(50), default='')
    parties_json = db.Column(db.Text, default='[]')
    total_votes = db.Column(db.Integer, default=0)
    turnout_pct = db.Column(db.Float, default=0.0)
    winner = db.Column(db.String(100), default='')

    def to_dict(self):
        return {
            'year': self.year,
            'election_type': self.election_type,
            'parties': json.loads(self.parties_json or '[]'),
            'total_votes': self.total_votes,
            'turnout_pct': self.turnout_pct,
            'winner': self.winner,
        }

    @classmethod
    def from_dict(cls, d, ward_id):
        return cls(
            ward_id=ward_id,
            year=d.get('year', 0),
            election_type=d.get('election_type', ''),
            parties_json=json.dumps(d.get('parties', []), ensure_ascii=False),
            total_votes=d.get('total_votes', 0),
            turnout_pct=d.get('turnout_pct', 0.0),
            winner=d.get('winner', ''),
        )


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ward_id = db.Column(db.Integer, nullable=True)
    voter_nqt_id = db.Column(db.String(40), default='')
    action = db.Column(db.String(40), default='')
    field_name = db.Column(db.String(40), default='')
    old_value = db.Column(db.Text, default='')
    new_value = db.Column(db.Text, default='')
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class WardUploadHistory(db.Model):
    """One row per PDF upload that updated a ward."""
    __tablename__ = 'ward_upload_history'
    id = db.Column(db.Integer, primary_key=True)
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    filename = db.Column(db.String(200), default='')
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    voters_added = db.Column(db.Integer, default=0)
    voters_updated = db.Column(db.Integer, default=0)
    voters_removed = db.Column(db.Integer, default=0)
    voters_unchanged = db.Column(db.Integer, default=0)
    metadata_json = db.Column(db.Text, default='{}')  # full PDF page-1 metadata snapshot

    def to_dict(self):
        try:
            meta = json.loads(self.metadata_json or '{}')
        except Exception:
            meta = {}
        user = User.query.get(self.user_id) if self.user_id else None
        return {
            'id': self.id,
            'filename': self.filename,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else '',
            'uploaded_by': user.display_name or user.username if user else 'system',
            'voters_added': self.voters_added,
            'voters_updated': self.voters_updated,
            'voters_removed': self.voters_removed,
            'voters_unchanged': self.voters_unchanged,
            'metadata': meta,
        }


class TagDefinition(db.Model):
    """Admin-defined custom tag fields applied to all voters.

    Each definition has:
      - key: machine name (e.g. 'religion')
      - label: display label (e.g. 'Religion')
      - field_type: 'dropdown' | 'text' | 'boolean'
      - options_json: list of allowed values for dropdown type
    Voter values are stored under voter.custom_tags_json (a key->value dict).
    """
    __tablename__ = 'tag_definitions'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True, nullable=False, index=True)
    label = db.Column(db.String(120), nullable=False, default='')
    field_type = db.Column(db.String(20), nullable=False, default='dropdown')  # dropdown|text|boolean
    options_json = db.Column(db.Text, default='[]')
    is_required = db.Column(db.Boolean, default=False)
    is_builtin = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    FIELD_TYPES = ('dropdown', 'text', 'boolean')

    @property
    def options(self):
        try:
            return json.loads(self.options_json or '[]')
        except Exception:
            return []

    @options.setter
    def options(self, val):
        self.options_json = json.dumps(val or [], ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'label': self.label,
            'field_type': self.field_type,
            'options': self.options,
            'is_required': self.is_required,
            'is_builtin': self.is_builtin,
            'sort_order': self.sort_order,
        }


class Contact(db.Model):
    __tablename__ = 'contacts'
    id = db.Column(db.Integer, primary_key=True)
    voter_id = db.Column(db.Integer, db.ForeignKey('voters.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    contact_number = db.Column(db.Integer, default=1)
    notes = db.Column(db.Text, default='')
    sentiment = db.Column(db.String(20), default='')
    gps_lat = db.Column(db.Float, nullable=True)
    gps_lon = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class WhatsAppCampaign(db.Model):
    __tablename__ = 'whatsapp_campaigns'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), default='')
    template = db.Column(db.String(60), default='')
    filters_json = db.Column(db.Text, default='{}')
    target_count = db.Column(db.Integer, default=0)
    sent = db.Column(db.Integer, default=0)
    delivered = db.Column(db.Integer, default=0)
    read = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='draft')  # draft, sending, completed, failed
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class MessageTemplate(db.Model):
    """User-creatable message templates for WhatsApp / SMS / social outreach.
    `body` may contain {placeholders} matching `params` list. Built-in templates
    seeded from whatsapp.py have is_builtin=True and cannot be deleted.
    """
    __tablename__ = 'message_templates'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True, nullable=False, index=True)
    label = db.Column(db.String(120), nullable=False, default='')
    channel = db.Column(db.String(20), default='whatsapp')  # whatsapp|sms|social
    body = db.Column(db.Text, default='')
    params_json = db.Column(db.Text, default='[]')
    is_builtin = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def params(self):
        try:
            return json.loads(self.params_json or '[]')
        except Exception:
            return []

    @params.setter
    def params(self, val):
        self.params_json = json.dumps(val or [], ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'label': self.label,
            'channel': self.channel,
            'body': self.body,
            'params': self.params,
            'is_builtin': self.is_builtin,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class WhatsAppMessage(db.Model):
    __tablename__ = 'whatsapp_messages'
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('whatsapp_campaigns.id'), nullable=True, index=True)
    voter_id = db.Column(db.Integer, db.ForeignKey('voters.id'), nullable=False, index=True)
    phone = db.Column(db.String(15), default='')
    template = db.Column(db.String(60), default='')
    message_id = db.Column(db.String(80), default='')  # provider message ID
    status = db.Column(db.String(20), default='pending')  # pending, sent, delivered, read, failed
    error = db.Column(db.Text, default='')
    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)


class WorkAssignment(db.Model):
    """Work assigned to a karyakarta. Type can be page-coverage, voter-contact,
    slip-delivery, survey, event-attendance, custom. Pages are stored in
    pages_json + ward_name; status tracks progress; metrics are computed on
    demand from the active ward voter store."""
    __tablename__ = 'work_assignments'
    id = db.Column(db.Integer, primary_key=True)
    karyakarta_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    work_type = db.Column(db.String(40), default='page_coverage')  # page_coverage|voter_contact|slip_delivery|survey|event|custom
    title = db.Column(db.String(200), default='')
    description = db.Column(db.Text, default='')
    ward_name = db.Column(db.String(120), default='')
    pages_json = db.Column(db.Text, default='[]')   # list[int]
    target_count = db.Column(db.Integer, default=0)  # e.g. # voters expected
    deadline = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='assigned')  # assigned|in_progress|completed|cancelled
    progress_count = db.Column(db.Integer, default=0)  # manually-reported progress
    progress_notes = db.Column(db.Text, default='')
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)

    @property
    def pages(self):
        try:
            v = json.loads(self.pages_json or '[]')
            return [int(x) for x in v if str(x).strip()]
        except Exception:
            return []

    @pages.setter
    def pages(self, val):
        cleaned = []
        for x in (val or []):
            try:
                cleaned.append(int(x))
            except (TypeError, ValueError):
                continue
        self.pages_json = json.dumps(sorted(set(cleaned)), ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'karyakarta_id': self.karyakarta_id,
            'work_type': self.work_type,
            'title': self.title,
            'description': self.description,
            'ward_name': self.ward_name,
            'pages': self.pages,
            'target_count': self.target_count,
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'status': self.status,
            'progress_count': self.progress_count,
            'progress_notes': self.progress_notes,
            'assigned_by': self.assigned_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


# ── Init helper ──────────────────────────────────────────────────────

def init_db(app):
    """Initialize database and create tables."""
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(os.path.dirname(__file__), 'election_intel.db'))
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate_schema()
        _seed_admin(app)
        _seed_builtin_field_defs()
        _seed_builtin_templates()
        _seed_server_settings()


def _migrate_schema():
    """Best-effort SQLite schema migrations for columns added after first
    deployment. db.create_all() does not ALTER existing tables, so any new
    columns must be added explicitly here."""
    from sqlalchemy import text, inspect
    insp = inspect(db.engine)
    try:
        existing = {c['name'] for c in insp.get_columns('users')}
        if 'assigned_ward' not in existing:
            db.session.execute(text("ALTER TABLE users ADD COLUMN assigned_ward VARCHAR(120) DEFAULT ''"))
            db.session.commit()
        if 'surname' not in existing:
            db.session.execute(text("ALTER TABLE users ADD COLUMN surname VARCHAR(60) DEFAULT ''"))
            db.session.commit()
        if 'location_details' not in existing:
            db.session.execute(text("ALTER TABLE users ADD COLUMN location_details TEXT DEFAULT ''"))
            db.session.commit()
        if 'assigned_pages_json' not in existing:
            db.session.execute(text("ALTER TABLE users ADD COLUMN assigned_pages_json TEXT DEFAULT '[]'"))
            db.session.commit()
        if 'assigned_booths_json' not in existing:
            db.session.execute(text("ALTER TABLE users ADD COLUMN assigned_booths_json TEXT DEFAULT '[]'"))
            db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        td_cols = {c['name'] for c in insp.get_columns('tag_definitions')}
        if 'is_builtin' not in td_cols:
            db.session.execute(text("ALTER TABLE tag_definitions ADD COLUMN is_builtin BOOLEAN DEFAULT 0"))
            db.session.commit()
    except Exception:
        db.session.rollback()
    # User: whatsapp + socials_json
    try:
        u_cols = {c['name'] for c in insp.get_columns('users')}
        if 'whatsapp' not in u_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN whatsapp VARCHAR(15) DEFAULT ''"))
            db.session.commit()
        if 'socials_json' not in u_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN socials_json TEXT DEFAULT '{}'"))
            db.session.commit()
        for col in ('home_state', 'home_district', 'home_taluka', 'home_village'):
            if col not in u_cols:
                db.session.execute(text(f"ALTER TABLE users ADD COLUMN {col} VARCHAR(60) DEFAULT ''"))
                db.session.commit()
    except Exception:
        db.session.rollback()
    # Voter: whatsapp + socials_json
    try:
        v_cols = {c['name'] for c in insp.get_columns('voters')}
        if 'whatsapp' not in v_cols:
            db.session.execute(text("ALTER TABLE voters ADD COLUMN whatsapp VARCHAR(15) DEFAULT ''"))
            db.session.commit()
        if 'socials_json' not in v_cols:
            db.session.execute(text("ALTER TABLE voters ADD COLUMN socials_json TEXT DEFAULT '{}'"))
            db.session.commit()
    except Exception:
        db.session.rollback()


# ── Server settings (admin-managed runtime config) ───────────────────

class ServerSetting(db.Model):
    """Admin-managed runtime configuration. Stores API tokens, provider
    choices, public URLs, org branding etc. so the deployment can be
    configured from the UI without redeploying / editing env vars."""
    __tablename__ = 'server_settings'
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, default='')
    is_secret = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)


# Catalog of known settings: shown to the admin even if unset in DB.
SETTING_DEFS = [
    # WhatsApp
    {'key': 'WA_PROVIDER',      'group': 'whatsapp', 'label': 'Provider',
     'type': 'select', 'options': ['meta', 'twilio'], 'default': 'meta', 'is_secret': False,
     'help': 'Choose Meta Cloud API or Twilio for WhatsApp delivery.'},
    {'key': 'WA_META_TOKEN',    'group': 'whatsapp', 'label': 'Meta Cloud API Token',
     'type': 'password', 'is_secret': True,
     'help': 'Bearer token from Meta WhatsApp Business → System Users.'},
    {'key': 'WA_META_PHONE_ID', 'group': 'whatsapp', 'label': 'Meta Phone Number ID',
     'type': 'text', 'is_secret': False,
     'help': 'Numeric ID of the WhatsApp Business phone number.'},
    {'key': 'WA_TWILIO_SID',    'group': 'whatsapp', 'label': 'Twilio Account SID',
     'type': 'text', 'is_secret': False},
    {'key': 'WA_TWILIO_TOKEN',  'group': 'whatsapp', 'label': 'Twilio Auth Token',
     'type': 'password', 'is_secret': True},
    {'key': 'WA_TWILIO_FROM',   'group': 'whatsapp', 'label': 'Twilio WhatsApp From',
     'type': 'text', 'is_secret': False,
     'help': 'e.g. whatsapp:+14155238886'},
    # SMS (optional second channel)
    {'key': 'SMS_PROVIDER',     'group': 'sms', 'label': 'SMS Provider',
     'type': 'select', 'options': ['', 'twilio', 'msg91', 'textlocal'], 'default': '', 'is_secret': False},
    {'key': 'SMS_API_KEY',      'group': 'sms', 'label': 'SMS API Key',
     'type': 'password', 'is_secret': True},
    {'key': 'SMS_SENDER_ID',    'group': 'sms', 'label': 'SMS Sender ID',
     'type': 'text', 'is_secret': False},
    # Server / branding
    {'key': 'EI_PUBLIC_URL',    'group': 'server', 'label': 'Public URL',
     'type': 'text', 'is_secret': False,
     'help': 'External URL where this app is reachable (used in share links).'},
    {'key': 'EI_ORG_NAME',      'group': 'server', 'label': 'Organisation Name',
     'type': 'text', 'is_secret': False},
    {'key': 'EI_SUPPORT_EMAIL', 'group': 'server', 'label': 'Support Email',
     'type': 'text', 'is_secret': False},
]
SETTING_DEFS_BY_KEY = {d['key']: d for d in SETTING_DEFS}


def get_setting(key, default=''):
    """Get a runtime setting: DB value > env var > default. Safe to call
    outside an app context (returns env/default in that case)."""
    try:
        row = ServerSetting.query.filter_by(key=key).first()
        if row and row.value not in (None, ''):
            return row.value
    except Exception:
        pass
    env = os.environ.get(key)
    if env not in (None, ''):
        return env
    spec = SETTING_DEFS_BY_KEY.get(key) or {}
    return spec.get('default', default)


def set_setting(key, value, user_id=None):
    """Upsert a server setting. Returns the row."""
    spec = SETTING_DEFS_BY_KEY.get(key)
    if not spec:
        raise ValueError(f'Unknown setting key: {key}')
    row = ServerSetting.query.filter_by(key=key).first()
    if row is None:
        row = ServerSetting(key=key, is_secret=bool(spec.get('is_secret')))
        db.session.add(row)
    row.value = '' if value is None else str(value)
    row.is_secret = bool(spec.get('is_secret'))
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return row


def _seed_server_settings():
    """Ensure every known setting key has a row (empty value if unset).
    Backfills value from env on first run so existing env-based deployments
    keep working without manual entry."""
    changed = False
    for spec in SETTING_DEFS:
        key = spec['key']
        row = ServerSetting.query.filter_by(key=key).first()
        if row is None:
            env_val = os.environ.get(key, '')
            row = ServerSetting(
                key=key,
                value=str(env_val) if env_val else '',
                is_secret=bool(spec.get('is_secret')),
            )
            db.session.add(row)
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _seed_admin(app):
    """Create default admin user if none exists."""
    from werkzeug.security import generate_password_hash
    if User.query.count() == 0:
        admin = User(
            username='admin',
            display_name='Administrator',
            password_hash=generate_password_hash('admin123'),
            role='admin',
        )
        db.session.add(admin)
        db.session.commit()
        print("  Default admin created: admin / admin123")


def _seed_builtin_templates():
    """Seed built-in WhatsApp templates from whatsapp.py into the DB so they
    appear alongside user-created templates and can be edited per deployment."""
    try:
        from whatsapp import TEMPLATES as WA_TEMPLATES
    except Exception:
        return
    changed = False
    for key, t in WA_TEMPLATES.items():
        existing = MessageTemplate.query.filter_by(key=key).first()
        if existing is None:
            mt = MessageTemplate(
                key=key,
                label=t.get('label', key),
                channel='whatsapp',
                body=t.get('text', ''),
                is_builtin=True,
            )
            mt.params = t.get('params', [])
            db.session.add(mt)
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _seed_builtin_field_defs():
    """Seed standard editable voter fields as TagDefinitions so they appear
    in the Field Management UI alongside admin-created fields. Built-ins
    cannot be deleted, but their label/options can be edited."""
    builtins = [
        # (key, label, field_type, options, sort_order)
        ('classification', 'Classification', 'dropdown',
         ['Unclassified', 'Pakka', 'Virodhi', 'Swing', 'Doubtful'], 10),
        ('sentiment', 'Sentiment', 'dropdown',
         ['', 'Positive', 'Neutral', 'Negative', 'Hostile'], 20),
        ('party_lean', 'Party Lean', 'dropdown',
         ['', 'BJP', 'INC', 'JDS', 'Other'], 30),
        ('caste', 'Caste', 'text', [], 40),
        ('phone', 'Phone', 'text', [], 50),
        ('notes', 'Notes', 'text', [], 60),
        ('voted', 'Voted', 'boolean', [], 70),
        ('slip_delivered', 'Slip Delivered', 'boolean', [], 80),
        ('is_beneficiary', 'Beneficiary', 'boolean', [], 90),
        ('is_migrated', 'Migrated', 'boolean', [], 100),
    ]
    changed = False
    for key, label, ftype, options, order in builtins:
        td = TagDefinition.query.filter_by(key=key).first()
        if td is None:
            td = TagDefinition(
                key=key, label=label, field_type=ftype,
                is_builtin=True, sort_order=order,
            )
            td.options = options
            db.session.add(td)
            changed = True
        elif not td.is_builtin:
            td.is_builtin = True
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
