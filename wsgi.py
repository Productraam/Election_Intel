"""WSGI entrypoint for production servers (gunicorn, uWSGI, Waitress)."""
from app import app as application  # noqa: F401

# Compatibility alias
app = application
