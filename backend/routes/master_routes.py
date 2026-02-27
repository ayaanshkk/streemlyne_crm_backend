"""
Master Data Routes
Handles: Country_Master, Currency_Master, UOM_Master,
         Services_Master, Supplier_Master, Module_Master,
         Tenant_Module_Mapping

Schema alignment (StreemLyne_MT):
  Country_Master  : country_id, country_name (UNIQUE), country_isd_code, created_at
  Currency_Master : currency_id, currency_name, currency_code, created_at
  UOM_Master      : uom_id, uom_description, created_at
  Services_Master : service_id, tenant_id, service_code (NOT NULL), service_title,
                    service_description, service_rate, currency_id, supplier_id,
                    date_from, date_to, created_at
  Supplier_Master : supplier_id, supplier_company_name, supplier_contact_name,
                    supplier_provisions (smallint), created_at
  Module_Master   : module_id, module_code (UNIQUE), module_name (UNIQUE),
                    description, is_core, is_active, created_at, updated_at
  Tenant_Module_Mapping : tenant_module_mapping_id, tenant_id, module_id, created_at
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import (
    CountryMaster, CurrencyMaster, UOMMaster,
    ServicesMaster, SupplierMaster, ModuleMaster,
    TenantModuleMapping
)
from middleware import auth_required, permission_required
from datetime import datetime

master_bp = Blueprint('master', __name__, url_prefix='/api/master')


# ─────────────────────────────────────────
# Countries
# ─────────────────────────────────────────

@master_bp.route('/countries', methods=['GET'])
@auth_required
def list_countries():
    """
    List all countries.
    GET /api/master/countries
    """
    countries = CountryMaster.query.order_by(CountryMaster.country_name).all()
    return jsonify([_country_dict(c) for c in countries]), 200


@master_bp.route('/countries', methods=['POST'])
@auth_required
@permission_required('master.manage')
def create_country():
    """
    Create a country.
    POST /api/master/countries
    Body: { "country_name": "United Kingdom", "country_isd_code": "+44" }
    """
    data = request.get_json() or {}
    if not data.get('country_name') or not data.get('country_isd_code'):
        return jsonify({'error': 'country_name and country_isd_code are required'}), 400

    c = CountryMaster(
        country_name=data['country_name'].strip(),
        country_isd_code=data['country_isd_code'].strip()
    )
    try:
        db.session.add(c)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Country already exists'}), 409

    return jsonify({'message': 'Country created', 'country': _country_dict(c)}), 201


@master_bp.route('/countries/<int:country_id>', methods=['PUT'])
@auth_required
@permission_required('master.manage')
def update_country(country_id: int):
    """
    Update a country's ISD code (name is unique and rarely changes).
    PUT /api/master/countries/<country_id>
    """
    c = CountryMaster.query.get(country_id)
    if not c:
        abort(404, description='Country not found')

    data = request.get_json() or {}
    if 'country_isd_code' in data:
        c.country_isd_code = data['country_isd_code']
    if 'country_name' in data:
        c.country_name = data['country_name']

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Country name already exists'}), 409

    return jsonify({'message': 'Country updated', 'country': _country_dict(c)}), 200


# ─────────────────────────────────────────
# Currencies
# ─────────────────────────────────────────

@master_bp.route('/currencies', methods=['GET'])
@auth_required
def list_currencies():
    """GET /api/master/currencies"""
    currencies = CurrencyMaster.query.order_by(CurrencyMaster.currency_name).all()
    return jsonify([_currency_dict(c) for c in currencies]), 200


@master_bp.route('/currencies', methods=['POST'])
@auth_required
@permission_required('master.manage')
def create_currency():
    """
    POST /api/master/currencies
    Body: { "currency_name": "Pound Sterling", "currency_code": "GBP" }
    """
    data = request.get_json() or {}
    if not data.get('currency_name') or not data.get('currency_code'):
        return jsonify({'error': 'currency_name and currency_code are required'}), 400

    c = CurrencyMaster(
        currency_name=data['currency_name'].strip(),
        currency_code=data['currency_code'].strip().upper()
    )
    try:
        db.session.add(c)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Currency already exists'}), 409

    return jsonify({'message': 'Currency created', 'currency': _currency_dict(c)}), 201


@master_bp.route('/currencies/<int:currency_id>', methods=['PUT'])
@auth_required
@permission_required('master.manage')
def update_currency(currency_id: int):
    """PUT /api/master/currencies/<currency_id>"""
    c = CurrencyMaster.query.get(currency_id)
    if not c:
        abort(404, description='Currency not found')

    data = request.get_json() or {}
    if 'currency_name' in data:
        c.currency_name = data['currency_name']
    if 'currency_code' in data:
        c.currency_code = data['currency_code'].strip().upper()

    db.session.commit()
    return jsonify({'message': 'Currency updated', 'currency': _currency_dict(c)}), 200


# ─────────────────────────────────────────
# Units of Measure
# ─────────────────────────────────────────

@master_bp.route('/uoms', methods=['GET'])
@auth_required
def list_uoms():
    """GET /api/master/uoms"""
    uoms = UOMMaster.query.order_by(UOMMaster.uom_description).all()
    return jsonify([_uom_dict(u) for u in uoms]), 200


@master_bp.route('/uoms', methods=['POST'])
@auth_required
@permission_required('master.manage')
def create_uom():
    """
    POST /api/master/uoms
    Body: { "uom_description": "kWh" }
    """
    data = request.get_json() or {}
    if not (data.get('uom_description') or '').strip():
        return jsonify({'error': 'uom_description is required'}), 400

    u = UOMMaster(uom_description=data['uom_description'].strip())
    try:
        db.session.add(u)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'UOM already exists'}), 409

    return jsonify({'message': 'UOM created', 'uom': _uom_dict(u)}), 201


@master_bp.route('/uoms/<int:uom_id>', methods=['DELETE'])
@auth_required
@permission_required('master.manage')
def delete_uom(uom_id: int):
    """DELETE /api/master/uoms/<uom_id>"""
    u = UOMMaster.query.get(uom_id)
    if not u:
        abort(404, description='UOM not found')
    try:
        db.session.delete(u)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete UOM — it is referenced by invoice or proposal lines'}), 409
    return jsonify({'message': 'UOM deleted'}), 200


# ─────────────────────────────────────────
# Services
# ─────────────────────────────────────────

@master_bp.route('/services', methods=['GET'])
@auth_required
def list_services():
    """
    List services for the current tenant.
    GET /api/master/services
    Query params: supplier_id
    """
    query = ServicesMaster.query.filter_by(tenant_id=g.tenant_id)

    supplier_id = request.args.get('supplier_id', type=int)
    if supplier_id:
        query = query.filter_by(supplier_id=supplier_id)

    services = query.order_by(ServicesMaster.service_title).all()
    return jsonify([_service_dict(s) for s in services]), 200


@master_bp.route('/services', methods=['POST'])
@auth_required
@permission_required('master.manage_services')
def create_service():
    """
    Create a service.
    POST /api/master/services
    Body:
    {
        "service_code": "GAS-FIX",          (required, NOT NULL in schema)
        "service_title": "Gas Fixed Rate",   (required)
        "service_description": "...",
        "service_rate": 0.12,
        "currency_id": 1,
        "supplier_id": 2,
        "date_from": "2025-01-01",
        "date_to": "2025-12-31"
    }
    """
    data = request.get_json() or {}

    if not data.get('service_code') or not data.get('service_title'):
        return jsonify({'error': 'service_code and service_title are required'}), 400

    s = ServicesMaster(
        tenant_id=g.tenant_id,
        service_code=data['service_code'].strip(),
        service_title=data['service_title'].strip(),
        service_description=data.get('service_description'),
        service_rate=data.get('service_rate'),
        currency_id=data.get('currency_id'),
        supplier_id=data.get('supplier_id'),
        date_from=_parse_date(data.get('date_from')),
        date_to=_parse_date(data.get('date_to'))
    )

    try:
        db.session.add(s)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Service code already exists or invalid FK reference'}), 409

    return jsonify(_service_dict(s)), 201


@master_bp.route('/services/<int:service_id>', methods=['PUT'])
@auth_required
@permission_required('master.manage_services')
def update_service(service_id: int):
    """
    Update a service.
    PUT /api/master/services/<service_id>
    """
    s = ServicesMaster.query.filter_by(
        service_id=service_id, tenant_id=g.tenant_id
    ).first()
    if not s:
        abort(404, description='Service not found')

    data = request.get_json() or {}

    for field in ['service_title', 'service_description', 'service_rate', 'currency_id', 'supplier_id']:
        if field in data:
            setattr(s, field, data[field])

    if 'date_from' in data:
        s.date_from = _parse_date(data['date_from'])
    if 'date_to' in data:
        s.date_to = _parse_date(data['date_to'])

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid currency_id or supplier_id'}), 409

    return jsonify({'message': 'Service updated', 'service': _service_dict(s)}), 200


@master_bp.route('/services/<int:service_id>', methods=['DELETE'])
@auth_required
@permission_required('master.manage_services')
def delete_service(service_id: int):
    """DELETE /api/master/services/<service_id>"""
    s = ServicesMaster.query.filter_by(
        service_id=service_id, tenant_id=g.tenant_id
    ).first()
    if not s:
        abort(404, description='Service not found')

    try:
        db.session.delete(s)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete service — it is referenced by contracts, proposals, or invoices'}), 409

    return jsonify({'message': 'Service deleted'}), 200


# ─────────────────────────────────────────
# Suppliers
# ─────────────────────────────────────────

@master_bp.route('/suppliers', methods=['GET'])
@auth_required
def list_suppliers():
    """GET /api/master/suppliers"""
    suppliers = SupplierMaster.query.order_by(SupplierMaster.supplier_company_name).all()
    return jsonify([_supplier_dict(s) for s in suppliers]), 200


@master_bp.route('/suppliers', methods=['POST'])
@auth_required
@permission_required('master.manage')
def create_supplier():
    """
    POST /api/master/suppliers
    Body: { "supplier_company_name": "British Gas", "supplier_contact_name": "...", "supplier_provisions": 1 }
    """
    data = request.get_json() or {}
    if not (data.get('supplier_company_name') or '').strip():
        return jsonify({'error': 'supplier_company_name is required'}), 400

    s = SupplierMaster(
        supplier_company_name=data['supplier_company_name'].strip(),
        supplier_contact_name=data.get('supplier_contact_name'),
        supplier_provisions=data.get('supplier_provisions')
    )
    db.session.add(s)
    db.session.commit()
    return jsonify({'message': 'Supplier created', 'supplier': _supplier_dict(s)}), 201


@master_bp.route('/suppliers/<int:supplier_id>', methods=['PUT'])
@auth_required
@permission_required('master.manage')
def update_supplier(supplier_id: int):
    """PUT /api/master/suppliers/<supplier_id>"""
    s = SupplierMaster.query.get(supplier_id)
    if not s:
        abort(404, description='Supplier not found')

    data = request.get_json() or {}
    for field in ['supplier_company_name', 'supplier_contact_name', 'supplier_provisions']:
        if field in data:
            setattr(s, field, data[field])

    db.session.commit()
    return jsonify({'message': 'Supplier updated', 'supplier': _supplier_dict(s)}), 200


@master_bp.route('/suppliers/<int:supplier_id>', methods=['DELETE'])
@auth_required
@permission_required('master.manage')
def delete_supplier(supplier_id: int):
    """DELETE /api/master/suppliers/<supplier_id>"""
    s = SupplierMaster.query.get(supplier_id)
    if not s:
        abort(404, description='Supplier not found')
    try:
        db.session.delete(s)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete supplier — it is referenced by services or contracts'}), 409
    return jsonify({'message': 'Supplier deleted'}), 200


# ─────────────────────────────────────────
# Modules
# ─────────────────────────────────────────

@master_bp.route('/modules', methods=['GET'])
@auth_required
def list_modules():
    """
    List all active modules in the catalogue.
    GET /api/master/modules
    """
    modules = (
        ModuleMaster.query
        .filter_by(is_active=True)
        .order_by(ModuleMaster.module_name)
        .all()
    )
    return jsonify([_module_dict(m) for m in modules]), 200


@master_bp.route('/modules/tenant', methods=['GET'])
@auth_required
def get_tenant_modules():
    """
    Get modules currently enabled for the current tenant.
    GET /api/master/modules/tenant
    """
    mappings = TenantModuleMapping.query.filter_by(tenant_id=g.tenant_id).all()
    module_ids = [m.module_id for m in mappings]

    modules = ModuleMaster.query.filter(
        ModuleMaster.module_id.in_(module_ids)
    ).all() if module_ids else []

    return jsonify({
        'tenant_id':  g.tenant_id,
        'module_ids': module_ids,
        'modules':    [_module_dict(m) for m in modules],
    }), 200


@master_bp.route('/modules/tenant/<int:module_id>', methods=['POST'])
@auth_required
@permission_required('module.assign')
def enable_tenant_module(module_id: int):
    """
    Enable a module for the current tenant.
    POST /api/master/modules/tenant/<module_id>
    """
    module = ModuleMaster.query.filter_by(module_id=module_id, is_active=True).first()
    if not module:
        return jsonify({'error': 'Module not found or inactive'}), 404

    existing = TenantModuleMapping.query.filter_by(
        tenant_id=g.tenant_id, module_id=module_id
    ).first()
    if existing:
        return jsonify({'error': 'Module is already enabled for this tenant'}), 409

    mapping = TenantModuleMapping(tenant_id=g.tenant_id, module_id=module_id)
    db.session.add(mapping)
    db.session.commit()
    return jsonify({'message': f'Module {module.module_name!r} enabled'}), 201


@master_bp.route('/modules/tenant/<int:module_id>', methods=['DELETE'])
@auth_required
@permission_required('module.revoke')
def disable_tenant_module(module_id: int):
    """
    Disable a module for the current tenant.
    DELETE /api/master/modules/tenant/<module_id>
    """
    mapping = TenantModuleMapping.query.filter_by(
        tenant_id=g.tenant_id, module_id=module_id
    ).first()
    if not mapping:
        return jsonify({'error': 'Module is not currently enabled for this tenant'}), 404

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({'message': 'Module disabled'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _country_dict(c: CountryMaster) -> dict:
    return {
        'country_id':       c.country_id,
        'country_name':     c.country_name,
        'country_isd_code': c.country_isd_code,
        'created_at':       c.created_at.isoformat() if c.created_at else None,
    }


def _currency_dict(c: CurrencyMaster) -> dict:
    return {
        'currency_id':   c.currency_id,
        'currency_name': c.currency_name,
        'currency_code': c.currency_code,
        'created_at':    c.created_at.isoformat() if c.created_at else None,
    }


def _uom_dict(u: UOMMaster) -> dict:
    return {
        'uom_id':          u.uom_id,
        'uom_description': u.uom_description,
        'created_at':      u.created_at.isoformat() if u.created_at else None,
    }


def _service_dict(s: ServicesMaster) -> dict:
    return {
        'service_id':          s.service_id,
        'tenant_id':           s.tenant_id,
        'service_code':        s.service_code,
        'service_title':       s.service_title,
        'service_description': s.service_description,
        'service_rate':        s.service_rate,
        'currency_id':         s.currency_id,
        'supplier_id':         s.supplier_id,
        'date_from':           s.date_from.isoformat() if s.date_from else None,
        'date_to':             s.date_to.isoformat()   if s.date_to   else None,
        'created_at':          s.created_at.isoformat() if s.created_at else None,
    }


def _supplier_dict(s: SupplierMaster) -> dict:
    return {
        'supplier_id':            s.supplier_id,
        'supplier_company_name':  s.supplier_company_name,
        'supplier_contact_name':  s.supplier_contact_name,
        'supplier_provisions':    s.supplier_provisions,
        'created_at':             s.created_at.isoformat() if s.created_at else None,
    }


def _module_dict(m: ModuleMaster) -> dict:
    return {
        'module_id':   m.module_id,
        'module_code': m.module_code,
        'module_name': m.module_name,
        'description': m.description,
        'is_core':     m.is_core,
        'is_active':   m.is_active,
        'created_at':  m.created_at.isoformat() if m.created_at else None,
    }