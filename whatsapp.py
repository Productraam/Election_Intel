"""
Election Intelligence - WhatsApp Business Integration
Provider abstraction for Meta Cloud API / Twilio WhatsApp.
"""

import os
import re
import time
import requests as http_requests
from datetime import datetime, timezone


# ── Configuration ────────────────────────────────────────────────────

WHATSAPP_PROVIDER = os.environ.get('WA_PROVIDER', 'meta')  # 'meta' or 'twilio'
META_TOKEN = os.environ.get('WA_META_TOKEN', '')
META_PHONE_ID = os.environ.get('WA_META_PHONE_ID', '')
TWILIO_SID = os.environ.get('WA_TWILIO_SID', '')
TWILIO_TOKEN = os.environ.get('WA_TWILIO_TOKEN', '')
TWILIO_FROM = os.environ.get('WA_TWILIO_FROM', '')  # whatsapp:+14155238886

RATE_LIMIT = 20  # messages per second


# ── Templates ────────────────────────────────────────────────────────

TEMPLATES = {
    'polling_reminder': {
        'name': 'polling_reminder',
        'label': 'Polling Day Reminder',
        'text': 'Namaste {name}, your polling booth is Booth {booth_no}. '
                'Please vote on {date}. Your vote matters!',
        'params': ['name', 'booth_no', 'date'],
    },
    'scheme_notification': {
        'name': 'scheme_notification',
        'label': 'Scheme Eligibility',
        'text': '{name}, you may be eligible for {scheme}. '
                'Visit your local center with Aadhaar for enrollment.',
        'params': ['name', 'scheme'],
    },
    'birthday_greeting': {
        'name': 'birthday_greeting',
        'label': 'Birthday Greeting',
        'text': 'Happy Birthday {name}! Wishing you a wonderful year ahead.',
        'params': ['name'],
    },
    'thank_you': {
        'name': 'thank_you',
        'label': 'Thank You for Voting',
        'text': 'Thank you {name} for exercising your democratic right today! '
                'Your vote shapes the future of {area}.',
        'params': ['name', 'area'],
    },
    'rally_invite': {
        'name': 'rally_invite',
        'label': 'Rally Invitation',
        'text': '{name}, you are invited to a public gathering at {venue} '
                'on {date} at {time}. Your presence matters!',
        'params': ['name', 'venue', 'date', 'time'],
    },
    'slip_delivery': {
        'name': 'slip_delivery',
        'label': 'Polling Slip Delivered',
        'text': '{name}, your polling slip for Booth {booth_no} has been delivered. '
                'Please keep it safe for election day.',
        'params': ['name', 'booth_no'],
    },
    'custom': {
        'name': 'custom',
        'label': 'Custom Message',
        'text': '{message}',
        'params': ['message'],
    },
}


def get_templates():
    """Return available templates."""
    return {k: {'name': v['name'], 'label': v['label'], 'params': v['params']}
            for k, v in TEMPLATES.items()}


# ── Phone validation ─────────────────────────────────────────────────

def validate_phone(phone):
    """Validate Indian mobile number. Returns cleaned number or None."""
    if not phone:
        return None
    clean = re.sub(r'[\s\-\(\)]+', '', str(phone))
    if clean.startswith('+91'):
        clean = clean[3:]
    elif clean.startswith('91') and len(clean) == 12:
        clean = clean[2:]
    elif clean.startswith('0'):
        clean = clean[1:]
    if re.match(r'^[6-9]\d{9}$', clean):
        return clean
    return None


def format_phone_e164(phone):
    """Format to E.164 for WhatsApp API."""
    clean = validate_phone(phone)
    return f'+91{clean}' if clean else None


# ── Message rendering ────────────────────────────────────────────────

def render_message(template_key, params):
    """Render a template with given parameters."""
    tpl = TEMPLATES.get(template_key)
    if not tpl:
        return None
    try:
        return tpl['text'].format(**params)
    except KeyError:
        return None


# ── Provider: Meta Cloud API ────────────────────────────────────────

def _send_meta(phone_e164, template_key, rendered_text):
    """Send via Meta WhatsApp Business Cloud API."""
    if not META_TOKEN or not META_PHONE_ID:
        return {'success': False, 'error': 'Meta API not configured (set WA_META_TOKEN, WA_META_PHONE_ID)'}

    url = f'https://graph.facebook.com/v18.0/{META_PHONE_ID}/messages'
    headers = {
        'Authorization': f'Bearer {META_TOKEN}',
        'Content-Type': 'application/json',
    }
    payload = {
        'messaging_product': 'whatsapp',
        'to': phone_e164.lstrip('+'),
        'type': 'text',
        'text': {'body': rendered_text},
    }

    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and 'messages' in data:
            return {
                'success': True,
                'message_id': data['messages'][0].get('id', ''),
                'status': 'sent',
            }
        return {'success': False, 'error': data.get('error', {}).get('message', str(data))}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── Provider: Twilio ────────────────────────────────────────────────

def _send_twilio(phone_e164, template_key, rendered_text):
    """Send via Twilio WhatsApp."""
    if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_FROM:
        return {'success': False, 'error': 'Twilio not configured (set WA_TWILIO_SID, WA_TWILIO_TOKEN, WA_TWILIO_FROM)'}

    url = f'https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json'
    payload = {
        'From': TWILIO_FROM,
        'To': f'whatsapp:{phone_e164}',
        'Body': rendered_text,
    }

    try:
        resp = http_requests.post(url, data=payload, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=10)
        data = resp.json()
        if resp.status_code in (200, 201):
            return {
                'success': True,
                'message_id': data.get('sid', ''),
                'status': 'sent',
            }
        return {'success': False, 'error': data.get('message', str(data))}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── Unified send ─────────────────────────────────────────────────────

def send_rendered(phone, rendered_text):
    """Send an already-rendered message body. Used by outreach endpoints
    that resolve templates from the DB before calling the provider."""
    phone_e164 = format_phone_e164(phone)
    if not phone_e164:
        return {'success': False, 'error': f'Invalid phone: {phone}'}
    if not rendered_text:
        return {'success': False, 'error': 'Empty message body'}
    if WHATSAPP_PROVIDER == 'twilio':
        return _send_twilio(phone_e164, '', rendered_text)
    return _send_meta(phone_e164, '', rendered_text)


def send_message(phone, template_key, params):
    """Send a single WhatsApp message.
    Returns dict with success, message_id, error.
    """
    phone_e164 = format_phone_e164(phone)
    if not phone_e164:
        return {'success': False, 'error': f'Invalid phone: {phone}'}

    rendered = render_message(template_key, params)
    if not rendered:
        return {'success': False, 'error': f'Invalid template or params: {template_key}'}

    if WHATSAPP_PROVIDER == 'twilio':
        return _send_twilio(phone_e164, template_key, rendered)
    return _send_meta(phone_e164, template_key, rendered)


def send_bulk(recipients, template_key, common_params=None):
    """Send bulk messages with rate limiting.
    recipients = [{'phone': '...', 'name': '...', 'booth_no': '...', ...}, ...]
    Returns summary dict.
    """
    results = {'sent': 0, 'failed': 0, 'errors': [], 'message_ids': []}
    common_params = common_params or {}

    for i, r in enumerate(recipients):
        params = {**common_params, **r}
        result = send_message(r.get('phone', ''), template_key, params)

        if result.get('success'):
            results['sent'] += 1
            results['message_ids'].append(result.get('message_id', ''))
        else:
            results['failed'] += 1
            if len(results['errors']) < 10:
                results['errors'].append(result.get('error', 'Unknown error'))

        # Rate limiting
        if (i + 1) % RATE_LIMIT == 0:
            time.sleep(1)

    return results


def get_provider_status():
    """Check if WhatsApp provider is configured."""
    if WHATSAPP_PROVIDER == 'meta':
        configured = bool(META_TOKEN and META_PHONE_ID)
    elif WHATSAPP_PROVIDER == 'twilio':
        configured = bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM)
    else:
        configured = False

    return {
        'provider': WHATSAPP_PROVIDER,
        'configured': configured,
        'templates': list(TEMPLATES.keys()),
    }
