"""
Form Routes
Handles: customer-facing form token generation and submission.

Schema alignment (StreemLyne_MT):
  Uses Client_Master to validate client ownership before token issuance.

  CustomerFormData is NOT part of the core StreemLyne_MT schema — it is an
  app-level model. All references are guarded so the app starts cleanly
  even if the table hasn't been migrated yet.

  Token store: in-memory dict (suitable for single-process dev only).
  For production replace with a Redis cache or a proper DB table.
"""

from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import SQLAlchemyError
from database import db
from models import ClientMaster
from middleware import auth_required
from datetime import datetime, timedelta
import secrets
import string
import json

form_bp = Blueprint('form', __name__, url_prefix='/forms')

# ── In-memory token store ──────────────────────────────────────────────────────
# Replace with Redis or a DB-backed token table in production.
# Structure: { token: { client_id, tenant_id, form_type, created_at, expires_at, used } }
_form_tokens: dict = {}


def _generate_token(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _get_valid_token(token: str) -> dict | None:
    """Return token payload if it exists, is unexpired, and unused. Purges stale entries."""
    data = _form_tokens.get(token)
    if not data:
        return None
    if datetime.now() > data['expires_at']:
        _form_tokens.pop(token, None)
        return None
    if data.get('used'):
        return None
    return data


# ─────────────────────────────────────────
# Token Management  (staff-facing)
# ─────────────────────────────────────────

@form_bp.route('/clients/<int:client_id>/generate-link', methods=['POST'])
@auth_required
def generate_form_link(client_id: int):
    """
    Issue a one-time form link for a specific client.
    POST /api/forms/clients/<client_id>/generate-link
    Body: { "form_type": "bedroom", "ttl_hours": 24 }

    The link expires after ttl_hours (default 24, max 168 / 7 days).
    """
    client = ClientMaster.query.filter_by(
        client_id=client_id, tenant_id=g.tenant_id
    ).first()

    if not client:
        return jsonify({'error': 'Client not found'}), 404

    data = request.get_json(silent=True) or {}
    form_type = data.get('form_type', 'general')
    ttl_hours = min(int(data.get('ttl_hours', 24)), 168)

    token = _generate_token()
    now = datetime.now()
    expires_at = now + timedelta(hours=ttl_hours)

    _form_tokens[token] = {
        'client_id':  client_id,
        'tenant_id':  g.tenant_id,
        'form_type':  form_type,
        'created_at': now,
        'expires_at': expires_at,
        'used':       False,
    }

    return jsonify({
        'success':    True,
        'token':      token,
        'form_type':  form_type,
        'client_id':  client_id,
        'expires_at': expires_at.isoformat(),
    }), 200


@form_bp.route('/validate-token/<string:token>', methods=['GET'])
def validate_token(token: str):
    """
    Validate a form token (called by the customer-facing form page).
    GET /api/forms/validate-token/<token>
    Does NOT consume the token — consumption happens on /submit.
    """
    token_data = _get_valid_token(token)

    if not token_data:
        return jsonify({'valid': False, 'error': 'Invalid or expired token'}), 400

    return jsonify({
        'valid':      True,
        'client_id':  token_data['client_id'],
        'form_type':  token_data['form_type'],
        'expires_at': token_data['expires_at'].isoformat(),
    }), 200


@form_bp.route('/tokens', methods=['GET'])
@auth_required
def list_active_tokens():
    """
    List currently active (unexpired, unused) tokens for the current tenant.
    GET /api/forms/tokens
    Useful for staff dashboards — shows pending client form links.
    """
    now = datetime.now()
    active = [
        {
            'token':      tok,
            'client_id':  d['client_id'],
            'form_type':  d['form_type'],
            'created_at': d['created_at'].isoformat(),
            'expires_at': d['expires_at'].isoformat(),
        }
        for tok, d in _form_tokens.items()
        if d['tenant_id'] == g.tenant_id
        and not d['used']
        and now <= d['expires_at']
    ]
    return jsonify({'count': len(active), 'tokens': active}), 200


@form_bp.route('/cleanup-tokens', methods=['POST'])
@auth_required
def cleanup_tokens():
    """
    Purge expired tokens from memory.
    POST /api/forms/cleanup-tokens
    """
    now = datetime.now()
    expired = [t for t, d in _form_tokens.items() if now > d['expires_at']]
    for t in expired:
        _form_tokens.pop(t, None)

    return jsonify({
        'cleaned':   len(expired),
        'remaining': len(_form_tokens),
    }), 200


# ─────────────────────────────────────────
# Form Submission  (customer-facing)
# ─────────────────────────────────────────

@form_bp.route('/submit', methods=['POST'])
def submit_form():
    """
    Submit a customer form.
    POST /api/forms/submit
    Body:
    {
        "token": "abc123...",      (preferred — ties submission to client securely)
        "form_data": { ... }       (required)
    }
    Fallback (embedded forms): include "client_id" inside form_data instead of token.

    On success, marks the token as consumed so it cannot be reused.
    """
    data      = request.get_json(silent=True) or {}
    token     = data.get('token')
    form_data = data.get('form_data', {})

    if not form_data:
        return jsonify({'error': 'form_data is required'}), 400

    client_id  = None
    tenant_id  = None

    if token:
        token_data = _get_valid_token(token)
        if not token_data:
            return jsonify({'error': 'Invalid or expired token'}), 400

        client_id = token_data['client_id']
        tenant_id = token_data['tenant_id']

        client = ClientMaster.query.filter_by(
            client_id=client_id, tenant_id=tenant_id
        ).first()
        if not client:
            return jsonify({'error': 'Associated client not found'}), 404

        _form_tokens[token]['used'] = True

    else:
        client_id = form_data.get('client_id')
        if not client_id:
            return jsonify({'error': 'A token or client_id in form_data is required'}), 400

        client = ClientMaster.query.get(client_id)
        if not client:
            return jsonify({'error': 'Client not found'}), 404

        tenant_id = client.tenant_id

    try:
        from models import CustomerFormData

        submission = CustomerFormData(
            client_id=client_id,
            tenant_id=tenant_id,
            form_data=json.dumps(form_data),
            token_used=token or '',
            submitted_at=datetime.utcnow()
        )
        db.session.add(submission)
        db.session.commit()

        return jsonify({
            'success':            True,
            'form_submission_id': submission.id,
            'client_id':          client_id,
            'message':            'Form submitted successfully',
        }), 201

    except ImportError:
        # CustomerFormData model doesn't exist yet — return success anyway
        # so the customer journey isn't broken during migration.
        return jsonify({
            'success':   True,
            'client_id': client_id,
            'message':   'Form received (persistence pending schema migration)',
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# Submission Retrieval  (staff-facing)
# ─────────────────────────────────────────

@form_bp.route('/submissions', methods=['GET'])
@auth_required
def list_submissions():
    """
    List all form submissions for the current tenant.
    GET /api/forms/submissions
    Query params:
      client_id – filter by client
    """
    try:
        from models import CustomerFormData
    except ImportError:
        return jsonify({'submissions': [], 'warning': 'CustomerFormData table not yet available'}), 200

    query = CustomerFormData.query.filter_by(tenant_id=g.tenant_id)

    client_id = request.args.get('client_id', type=int)
    if client_id:
        query = query.filter_by(client_id=client_id)

    submissions = query.order_by(CustomerFormData.submitted_at.desc()).all()

    return jsonify([
        {
            'id':           s.id,
            'client_id':    s.client_id,
            'tenant_id':    s.tenant_id,
            'submitted_at': s.submitted_at.isoformat() if s.submitted_at else None,
            'form_data':    _safe_json(s.form_data),
            'token_used':   s.token_used,
        }
        for s in submissions
    ]), 200


@form_bp.route('/submissions/<int:submission_id>', methods=['GET'])
@auth_required
def get_submission(submission_id: int):
    """
    Get a single form submission.
    GET /api/forms/submissions/<submission_id>
    """
    try:
        from models import CustomerFormData
    except ImportError:
        return jsonify({'error': 'CustomerFormData table not yet available'}), 503

    submission = CustomerFormData.query.filter_by(
        id=submission_id, tenant_id=g.tenant_id
    ).first()

    if not submission:
        return jsonify({'error': 'Submission not found'}), 404

    return jsonify({
        'id':           submission.id,
        'client_id':    submission.client_id,
        'tenant_id':    submission.tenant_id,
        'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None,
        'form_data':    _safe_json(submission.form_data),
        'token_used':   submission.token_used,
    }), 200


@form_bp.route('/submissions/<int:submission_id>', methods=['DELETE'])
@auth_required
def delete_submission(submission_id: int):
    """
    Delete a form submission.
    DELETE /api/forms/submissions/<submission_id>
    """
    try:
        from models import CustomerFormData
    except ImportError:
        return jsonify({'error': 'CustomerFormData table not yet available'}), 503

    submission = CustomerFormData.query.filter_by(
        id=submission_id, tenant_id=g.tenant_id
    ).first()

    if not submission:
        return jsonify({'error': 'Submission not found'}), 404

    db.session.delete(submission)
    db.session.commit()
    return jsonify({'message': 'Submission deleted'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _safe_json(value):
    """Parse a JSON string; return a raw wrapper on failure."""
    try:
        return json.loads(value)
    except Exception:
        return {'raw': value}