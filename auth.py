"""
Election Intelligence - Authentication & RBAC
JWT tokens + role-based access decorators.
"""

import os
import jwt
import functools
from datetime import datetime, timedelta, timezone
from flask import request, g, jsonify

SECRET_KEY = os.environ.get('EI_SECRET_KEY', 'election-intel-secret-2026-change-in-prod')
TOKEN_EXPIRY_HOURS = 72

# ── Role hierarchy (higher index = more permissions) ─────────────────
ROLE_RANK = {
    'karyakarta': 0,
    'booth_agent': 1,
    'candidate': 2,
    'manager': 3,
    'admin': 4,
}


def create_token(user_id, username, role):
    """Create a JWT token for authenticated user."""
    payload = {
        'user_id': user_id,
        'username': username,
        'role': role,
        'exp': datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
        'iat': datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')


def decode_token(token):
    """Decode and verify a JWT token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_auth(f):
    """Decorator: require valid JWT token."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authentication required'}), 401

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        g.user_id = payload['user_id']
        g.username = payload['username']
        g.role = payload['role']
        return f(*args, **kwargs)
    return decorated


def require_role(*roles):
    """Decorator: require specific role(s). Must be used AFTER require_auth."""
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, 'role'):
                return jsonify({'error': 'Authentication required'}), 401
            if g.role not in roles and g.role != 'admin':
                return jsonify({'error': 'Insufficient permissions'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def optional_auth(f):
    """Decorator: decode bearer token if present (sets g.user_id/g.role),
    but never rejects the request. Used for endpoints that should apply
    role-based scoping when a user is logged in but stay accessible to
    legacy / unauthenticated callers."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            payload = decode_token(auth_header[7:])
            if payload:
                g.user_id = payload['user_id']
                g.username = payload['username']
                g.role = payload['role']
        return f(*args, **kwargs)
    return decorated


def get_user_id():
    """Get current user ID from request context, or None."""
    return getattr(g, 'user_id', None)


# ── Role-based voter scoping ─────────────────────────────────────────
# karyakarta sees only voters on their assigned PDF pages.
# booth_agent sees only voters in their assigned booths (part_no values).
# All other roles (candidate, manager, admin) see everything.
_SCOPED_ROLES = {'karyakarta', 'booth_agent'}


def _current_user_record():
    """Look up the User row for the authenticated request, or None.
    Imported lazily to avoid circular imports."""
    uid = get_user_id()
    if not uid:
        return None
    try:
        from database import User
        return User.query.get(uid)
    except Exception:
        return None


def voter_in_scope(voter, user=None):
    """Return True if `voter` (dict or model with .page_no/.part_no) is
    visible to the current authenticated user. Unauthenticated callers
    are treated as unrestricted (legacy behaviour for public endpoints)."""
    role = getattr(g, 'role', None)
    if role not in _SCOPED_ROLES:
        return True
    u = user or _current_user_record()
    if not u:
        return True
    if role == 'karyakarta':
        pages = set(u.assigned_pages or [])
        if not pages:
            return False  # unassigned karyakarta sees nothing
        try:
            pn = int(voter.get('page_no') if isinstance(voter, dict) else getattr(voter, 'page_no', 0) or 0)
        except (TypeError, ValueError):
            pn = 0
        return pn in pages
    if role == 'booth_agent':
        booths = set(u.assigned_booths or [])
        if not booths:
            return False
        pn = voter.get('part_no') if isinstance(voter, dict) else getattr(voter, 'part_no', '')
        return str(pn or '').strip() in booths
    return True


def restrict_voters_for(voters):
    """Filter a list of voter dicts to those visible to the current user.
    No-op when no role restriction applies."""
    role = getattr(g, 'role', None)
    if role not in _SCOPED_ROLES:
        return voters
    u = _current_user_record()
    if not u:
        return voters
    return [v for v in voters if voter_in_scope(v, u)]
