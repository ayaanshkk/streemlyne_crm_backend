"""
Tenant Routes
Handles: Tenant_Master
Two access levels:
  1. Self-service  (/api/tenant/info)      – any authenticated user reads/updates own tenant
  2. Super-admin   (/api/tenant and /api/tenant/<id>)  – requires explicit permissions
Schema alignment (StreemLyne_MT):
  Tenant_Master:
    tenant_id (PK, UNIQUE, character varying), tenant_company_name (UNIQUE),
    tenant_contact_name, onboarding_Date (date), is_active (boolean),
    created_at, updated_at, stripe_customer_id (UNIQUE),
    -- Profile/branding columns (added via migration):
    logo_url, tagline, company_email, company_phone, company_address,
    company_postcode, company_website, registration_no, vat_reg_no,
    bank_name, account_name, sort_code, account_number, payment_reference,
    default_vat_rate, default_currency, quote_validity_days, default_notes

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[TNT-001] All <int:tenant_id> URL converters changed to <string:tenant_id>.
[TNT-002] create_tenant delegates to TenantService.create_tenant() so that
          trial provisioning is always handled in one place.
[TNT-003] _tenant_dict now includes stripe_customer_id.
[TNT-004] get_tenant_info / update_tenant_info use g.tenant_id (now a string).
[TNT-005] H1 FIX — Restored all @permission_required decorators on super-admin
          endpoints (list_tenants, create_tenant, get_tenant, update_tenant,
          deactivate_tenant, activate_tenant). Self-service endpoints
          (GET/PATCH /info) remain open to all authenticated users as intended.
[TNT-006] Added profile/branding fields to _tenant_dict and update_tenant_info.
[TNT-007] Added POST /tenant/logo for Vercel Blob logo upload.
[TNT-008] Added GET /tenant/me alias for /tenant/info (used by frontend).
─────────────────────────────────────────────────────────────────────────────
"""
from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import TenantMaster
from middleware import auth_required, permission_required
from datetime import datetime
import re
import uuid
import os
import requests as http_requests

tenant_bp = Blueprint('tenant', __name__, url_prefix='/tenant')

VERCEL_BLOB_TOKEN = os.getenv('BLOB_READ_WRITE_TOKEN')


# ─────────────────────────────────────────
# Self-service (own tenant) — open to all authenticated users
# ─────────────────────────────────────────

@tenant_bp.route('/me', methods=['GET'])
@tenant_bp.route('/info', methods=['GET'])
@auth_required
def get_tenant_info():
    """
    Get the calling user's own tenant details including profile/branding.
    GET /api/tenant/me  (or /api/tenant/info)
    """
    tenant = db.session.get(TenantMaster, g.tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    return jsonify(_tenant_dict(tenant)), 200


@tenant_bp.route('/info', methods=['PATCH'])
@tenant_bp.route('/me', methods=['PATCH'])
@auth_required
def update_tenant_info():
    """
    Update own tenant's display details and company profile.
    PATCH /api/tenant/me  (or /api/tenant/info)
    Body: any subset of profile fields
    """
    tenant = db.session.get(TenantMaster, g.tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404

    data = request.get_json() or {}

    # ── Core fields ───────────────────────────────────────────────────────────
    if 'tenant_company_name' in data:
        tenant.tenant_company_name = (data['tenant_company_name'] or '').strip() or None
    if 'tenant_contact_name' in data:
        tenant.tenant_contact_name = data['tenant_contact_name']

    # ── Branding ──────────────────────────────────────────────────────────────
    for field in ['logo_url', 'tagline']:
        if field in data:
            setattr(tenant, field, data[field])

    # ── Business details ──────────────────────────────────────────────────────
    for field in [
        'company_email', 'company_phone', 'company_address',
        'company_postcode', 'company_website',
        'registration_no', 'vat_reg_no',
    ]:
        if field in data:
            setattr(tenant, field, data[field])

    # ── Payment details ───────────────────────────────────────────────────────
    for field in ['bank_name', 'account_name', 'sort_code', 'account_number', 'payment_reference']:
        if field in data:
            setattr(tenant, field, data[field])

    # ── Document defaults ─────────────────────────────────────────────────────
    if 'default_vat_rate' in data:
        try:
            tenant.default_vat_rate = float(data['default_vat_rate'])
        except (TypeError, ValueError):
            return jsonify({'error': 'default_vat_rate must be a number'}), 400
    if 'default_currency'    in data: tenant.default_currency    = data['default_currency']
    if 'quote_validity_days' in data: tenant.quote_validity_days = int(data['quote_validity_days'])
    if 'default_notes'       in data: tenant.default_notes       = data['default_notes']

    tenant.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'tenant_company_name is already in use'}), 409

    return jsonify({'message': 'Profile updated successfully', 'tenant': _tenant_dict(tenant)}), 200


@tenant_bp.route('/logo', methods=['POST'])
@auth_required
def upload_logo():
    """
    Upload company logo to Vercel Blob.
    POST /api/tenant/logo
    Multipart form: file (image)
    Returns: { logo_url: "https://..." }
    """
    if not VERCEL_BLOB_TOKEN:
        return jsonify({'error': 'Blob storage not configured on server'}), 500

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file provided'}), 400

    # Validate image type
    allowed = {'image/jpeg', 'image/png', 'image/webp', 'image/svg+xml'}
    if file.content_type not in allowed:
        return jsonify({'error': 'File must be JPEG, PNG, WebP, or SVG'}), 400

    # Limit to 2MB
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({'error': 'File must be under 2MB'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower()
    filename = f"logos/{g.tenant_id}/logo.{ext}"

    try:
        resp = http_requests.put(
            f"https://blob.vercel-storage.com/{filename}",
            headers={
                'Authorization':  f'Bearer {VERCEL_BLOB_TOKEN}',
                'Content-Type':   file.content_type,
                'x-api-version':  '7',
            },
            data=file.read(),
            timeout=30,
        )

        if resp.status_code not in (200, 201):
            return jsonify({'error': f'Blob upload failed: {resp.text[:200]}'}), 500

        blob_data = resp.json()
        logo_url  = blob_data.get('url') or blob_data.get('downloadUrl')

        if not logo_url:
            return jsonify({'error': 'No URL returned from blob storage'}), 500

        # Save to tenant
        tenant = db.session.get(TenantMaster, g.tenant_id)
        if tenant:
            tenant.logo_url   = logo_url
            tenant.updated_at = datetime.utcnow()
            db.session.commit()

        return jsonify({'logo_url': logo_url, 'message': 'Logo uploaded successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# Super-admin: all tenants — requires explicit permissions
# ─────────────────────────────────────────

@tenant_bp.route('', methods=['GET'])
@auth_required
@permission_required('tenant.view')
def list_tenants():
    """
    List all tenants (super-admin only).
    GET /api/tenant
    """
    query = TenantMaster.query
    is_active = request.args.get('is_active')
    if is_active is not None:
        query = query.filter_by(is_active=is_active.lower() == 'true')
    tenants = query.order_by(TenantMaster.created_at.desc()).all()
    return jsonify([_tenant_dict(t) for t in tenants]), 200


@tenant_bp.route('', methods=['POST'])
@auth_required
@permission_required('tenant.create')
def create_tenant():
    """
    Create a new tenant and automatically provision a 7-day trial subscription.
    POST /api/tenant
    """
    data = request.get_json() or {}
    name = (data.get('tenant_company_name') or '').strip()
    if not name:
        return jsonify({'error': 'tenant_company_name is required'}), 400

    onboarding = _parse_date(data.get('onboarding_date'))
    try:
        from services.tenant_service import TenantService
        svc    = TenantService()
        tenant = svc.create_tenant(
            company_name=name,
            contact_name=data.get('tenant_contact_name'),
            onboarding_date=onboarding,
        )
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A tenant with this company name already exists'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'message': 'Tenant created successfully with 7-day trial',
        'tenant':  _tenant_dict(tenant),
    }), 201


@tenant_bp.route('/<string:tenant_id>', methods=['GET'])
@auth_required
@permission_required('tenant.view')
def get_tenant(tenant_id: str):
    """GET /api/tenant/<tenant_id>"""
    tenant = db.session.get(TenantMaster, tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')

    result = _tenant_dict(tenant)
    try:
        from models import ClientMaster, EmployeeMaster, OpportunityDetails, TenantSubscription
        result['stats'] = {
            'client_count':     ClientMaster.query.filter_by(tenant_id=tenant_id).count(),
            'employee_count':   EmployeeMaster.query.filter_by(tenant_id=tenant_id).count(),
            'opportunity_count': OpportunityDetails.query.filter_by(
                tenant_id=tenant_id
            ).filter(OpportunityDetails.deleted_at.is_(None)).count(),
            'has_active_subscription': TenantSubscription.query.filter_by(
                tenant_id=tenant_id, is_active=True
            ).first() is not None,
        }
    except Exception:
        result['stats'] = {}

    return jsonify(result), 200


@tenant_bp.route('/<string:tenant_id>', methods=['PUT'])
@auth_required
@permission_required('tenant.update')
def update_tenant(tenant_id: str):
    """PUT /api/tenant/<tenant_id>"""
    tenant = db.session.get(TenantMaster, tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')

    data = request.get_json() or {}
    if 'tenant_company_name' in data:
        tenant.tenant_company_name = (data['tenant_company_name'] or '').strip() or None
    if 'tenant_contact_name' in data:
        tenant.tenant_contact_name = data['tenant_contact_name']
    if 'is_active'       in data: tenant.is_active       = bool(data['is_active'])
    if 'onboarding_date' in data: tenant.onboarding_Date = _parse_date(data['onboarding_date'])

    tenant.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'tenant_company_name is already in use'}), 409

    return jsonify({'message': 'Tenant updated successfully', 'tenant': _tenant_dict(tenant)}), 200


@tenant_bp.route('/<string:tenant_id>/deactivate', methods=['POST'])
@auth_required
@permission_required('tenant.deactivate')
def deactivate_tenant(tenant_id: str):
    """POST /api/tenant/<tenant_id>/deactivate"""
    tenant = db.session.get(TenantMaster, tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')
    if not tenant.is_active:
        return jsonify({'message': 'Tenant is already inactive'}), 200

    tenant.is_active  = False
    tenant.updated_at = datetime.utcnow()
    try:
        from models import TenantSubscription
        TenantSubscription.query.filter_by(
            tenant_id=tenant_id, is_active=True
        ).update({'is_active': False, 'auto_renew': False, 'status': 'canceled',
                  'updated_at': datetime.utcnow()})
    except Exception:
        pass

    db.session.commit()
    return jsonify({'message': 'Tenant deactivated successfully'}), 200


@tenant_bp.route('/<string:tenant_id>/activate', methods=['POST'])
@auth_required
@permission_required('tenant.deactivate')
def activate_tenant(tenant_id: str):
    """POST /api/tenant/<tenant_id>/activate"""
    tenant = db.session.get(TenantMaster, tenant_id)
    if not tenant:
        abort(404, description='Tenant not found')

    tenant.is_active  = True
    tenant.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Tenant activated successfully', 'tenant': _tenant_dict(tenant)}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _generate_tenant_id(company_name: str) -> str:
    slug   = re.sub(r'[^a-z0-9]+', '-', company_name.lower()).strip('-')[:24]
    suffix = uuid.uuid4().hex[:6]
    return f"{slug}-{suffix}"


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _tenant_dict(t: TenantMaster) -> dict:
    return {
        # ── Core ──────────────────────────────────────────────────────────────
        'tenant_id':           t.tenant_id,
        'tenant_company_name': t.tenant_company_name,
        'tenant_contact_name': t.tenant_contact_name,
        'onboarding_date':     t.onboarding_Date.isoformat() if t.onboarding_Date else None,
        'is_active':           t.is_active,
        'stripe_customer_id':  t.stripe_customer_id,
        'created_at':          t.created_at.isoformat() if t.created_at else None,
        'updated_at':          t.updated_at.isoformat() if t.updated_at else None,
        # ── Branding ──────────────────────────────────────────────────────────
        'logo_url':            getattr(t, 'logo_url',  None),
        'tagline':             getattr(t, 'tagline',   None),
        # ── Business details ──────────────────────────────────────────────────
        'company_email':       getattr(t, 'company_email',    None),
        'company_phone':       getattr(t, 'company_phone',    None),
        'company_address':     getattr(t, 'company_address',  None),
        'company_postcode':    getattr(t, 'company_postcode', None),
        'company_website':     getattr(t, 'company_website',  None),
        'registration_no':     getattr(t, 'registration_no',  None),
        'vat_reg_no':          getattr(t, 'vat_reg_no',       None),
        # ── Payment details ───────────────────────────────────────────────────
        'bank_name':           getattr(t, 'bank_name',          None),
        'account_name':        getattr(t, 'account_name',       None),
        'sort_code':           getattr(t, 'sort_code',          None),
        'account_number':      getattr(t, 'account_number',     None),
        'payment_reference':   getattr(t, 'payment_reference',  None),
        # ── Document defaults ─────────────────────────────────────────────────
        'default_vat_rate':    float(t.default_vat_rate)  if getattr(t, 'default_vat_rate',  None) is not None else 20.0,
        'default_currency':    getattr(t, 'default_currency',    'GBP'),
        'quote_validity_days': getattr(t, 'quote_validity_days', 30),
        'default_notes':       getattr(t, 'default_notes',       None),
    }