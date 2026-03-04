"""
Role & Permission Routes
Handles: Role_Master, Role_Permission_Mapping, Permission_Catalog, User_Role_Mapping

Schema alignment (StreemLyne_MT):
  Role_Master:
    role_id (PK), role_name (UNIQUE, NOT NULL), role_description,
    is_system (NOT NULL), created_at

  Role_Permission_Mapping:
    role_permission_mapping_id (PK), role_id (FK→Role_Master, NOT NULL),
    permission_id (FK→Permission_Catalog, NOT NULL), created_at, edited_at (DATE)

  Permission_Catalog:
    permission_id (PK), permission_code (UNIQUE, NOT NULL),
    description, created_at

  User_Role_Mapping:
    user_id (PK composite), role_id (PK composite)
    — no surrogate key, no created_at in schema
"""

from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy.exc import IntegrityError
from database import db
from models import RoleMaster, RolePermissionMapping, PermissionCatalog, UserRoleMapping
from middleware import auth_required, permission_required

role_bp = Blueprint('role', __name__, url_prefix='/api/roles')


# ─────────────────────────────────────────
# Roles – CRUD
# ─────────────────────────────────────────

@role_bp.route('', methods=['GET'])
@auth_required
def list_roles():
    """
    List all roles.
    GET /api/roles
    """
    roles = RoleMaster.query.order_by(RoleMaster.role_name).all()
    return jsonify([_role_dict(r) for r in roles]), 200


@role_bp.route('', methods=['POST'])
@auth_required
@permission_required('role.create')
def create_role():
    """
    Create a new role.
    POST /api/roles
    Body: { "role_name": "Billing Manager", "role_description": "...", "is_system": false }
    """
    data = request.get_json() or {}

    if not (data.get('role_name') or '').strip():
        return jsonify({'error': 'role_name is required'}), 400

    role = RoleMaster(
        role_name=data['role_name'].strip(),
        role_description=data.get('role_description'),
        is_system=bool(data.get('is_system', False))
    )

    try:
        db.session.add(role)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Role name already exists'}), 409

    return jsonify({'message': 'Role created', 'role': _role_dict(role)}), 201


@role_bp.route('/<int:role_id>', methods=['GET'])
@auth_required
def get_role(role_id: int):
    """
    Retrieve a role with its assigned permissions.
    GET /api/roles/<role_id>
    """
    role = _role_or_404(role_id)

    permissions = (
        db.session.query(PermissionCatalog)
        .join(RolePermissionMapping,
              RolePermissionMapping.permission_id == PermissionCatalog.permission_id)
        .filter(RolePermissionMapping.role_id == role_id)
        .order_by(PermissionCatalog.permission_code)
        .all()
    )

    result = _role_dict(role)
    result['permissions'] = [_permission_dict(p) for p in permissions]
    return jsonify(result), 200


@role_bp.route('/<int:role_id>', methods=['PUT'])
@auth_required
@permission_required('role.update')
def update_role(role_id: int):
    """
    Update a non-system role.
    PUT /api/roles/<role_id>
    Body: { "role_name": "...", "role_description": "..." }
    System roles (is_system=true) are protected and cannot be renamed.
    """
    role = _role_or_404(role_id)

    if role.is_system:
        return jsonify({'error': 'System roles cannot be modified'}), 403

    data = request.get_json() or {}

    if 'role_name' in data:
        role.role_name = data['role_name'].strip()
    if 'role_description' in data:
        role.role_description = data['role_description']

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Role name already exists'}), 409

    return jsonify({'message': 'Role updated', 'role': _role_dict(role)}), 200


@role_bp.route('/<int:role_id>', methods=['DELETE'])
@auth_required
@permission_required('role.delete')
def delete_role(role_id: int):
    """
    Delete a non-system role.
    DELETE /api/roles/<role_id>
    Returns 403 for system roles, 409 if users are still assigned this role.
    """
    role = _role_or_404(role_id)

    if role.is_system:
        return jsonify({'error': 'System roles cannot be deleted'}), 403

    try:
        db.session.delete(role)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete role — users are still assigned to it'
        }), 409

    return jsonify({'message': 'Role deleted'}), 200


# ─────────────────────────────────────────
# Role ↔ Permission Mapping
# ─────────────────────────────────────────

@role_bp.route('/<int:role_id>/permissions', methods=['GET'])
@auth_required
def get_role_permissions(role_id: int):
    """
    List all permissions assigned to a role.
    GET /api/roles/<role_id>/permissions
    """
    _role_or_404(role_id)

    permissions = (
        db.session.query(PermissionCatalog)
        .join(RolePermissionMapping,
              RolePermissionMapping.permission_id == PermissionCatalog.permission_id)
        .filter(RolePermissionMapping.role_id == role_id)
        .order_by(PermissionCatalog.permission_code)
        .all()
    )
    return jsonify([_permission_dict(p) for p in permissions]), 200


@role_bp.route('/<int:role_id>/permissions', methods=['POST'])
@auth_required
@permission_required('role.assign_permission')
def assign_permission(role_id: int):
    """
    Assign a permission to a role.
    POST /api/roles/<role_id>/permissions
    Body: { "permission_code": "client.create" }
    """
    _role_or_404(role_id)
    data = request.get_json() or {}

    if not data.get('permission_code'):
        return jsonify({'error': 'permission_code is required'}), 400

    permission = PermissionCatalog.query.filter_by(
        permission_code=data['permission_code']
    ).first()
    if not permission:
        return jsonify({'error': 'Permission not found'}), 404

    if RolePermissionMapping.query.filter_by(
        role_id=role_id, permission_id=permission.permission_id
    ).first():
        return jsonify({'error': 'Permission already assigned to this role'}), 409

    mapping = RolePermissionMapping(
        role_id=role_id,
        permission_id=permission.permission_id
    )

    try:
        db.session.add(mapping)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Permission already assigned to this role'}), 409

    return jsonify({'message': 'Permission assigned'}), 201


@role_bp.route('/<int:role_id>/permissions/bulk', methods=['POST'])
@auth_required
@permission_required('role.assign_permission')
def bulk_assign_permissions(role_id: int):
    """
    Replace all permissions on a role in one call.
    POST /api/roles/<role_id>/permissions/bulk
    Body: { "permission_codes": ["client.create", "client.update", ...] }

    Existing mappings are removed and the supplied set is applied atomically.
    Useful for the role editor UI — avoids many individual assign/revoke calls.
    """
    _role_or_404(role_id)
    data = request.get_json() or {}

    codes = data.get('permission_codes', [])
    if not isinstance(codes, list):
        return jsonify({'error': 'permission_codes must be a list'}), 400

    # Resolve codes → permission_id list
    permissions = PermissionCatalog.query.filter(
        PermissionCatalog.permission_code.in_(codes)
    ).all()
    found_codes = {p.permission_code for p in permissions}
    missing = [c for c in codes if c not in found_codes]
    if missing:
        return jsonify({'error': f'Unknown permission codes: {missing}'}), 400

    try:
        # Remove all existing mappings for this role
        RolePermissionMapping.query.filter_by(role_id=role_id).delete()

        # Insert the new set
        for perm in permissions:
            db.session.add(RolePermissionMapping(
                role_id=role_id,
                permission_id=perm.permission_id
            ))

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Failed to update permissions'}), 409

    return jsonify({
        'message': f'{len(permissions)} permission(s) applied to role',
        'permission_codes': codes
    }), 200


@role_bp.route('/<int:role_id>/permissions/<int:permission_id>', methods=['DELETE'])
@auth_required
@permission_required('role.revoke_permission')
def revoke_permission(role_id: int, permission_id: int):
    """
    Remove a permission from a role.
    DELETE /api/roles/<role_id>/permissions/<permission_id>
    """
    mapping = RolePermissionMapping.query.filter_by(
        role_id=role_id, permission_id=permission_id
    ).first()
    if not mapping:
        abort(404, description='Permission mapping not found')

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({'message': 'Permission revoked'}), 200


# ─────────────────────────────────────────
# Permission Catalogue – CRUD
# ─────────────────────────────────────────

@role_bp.route('/permissions', methods=['GET'])
@auth_required
def list_permissions():
    """
    List all available permissions.
    GET /api/roles/permissions
    """
    permissions = (
        PermissionCatalog.query
        .order_by(PermissionCatalog.permission_code)
        .all()
    )
    return jsonify([_permission_dict(p) for p in permissions]), 200


@role_bp.route('/permissions', methods=['POST'])
@auth_required
@permission_required('role.manage_permissions')
def create_permission():
    """
    Register a new permission in the catalogue.
    POST /api/roles/permissions
    Body: { "permission_code": "report.export", "description": "Can export reports" }
    """
    data = request.get_json() or {}

    if not (data.get('permission_code') or '').strip():
        return jsonify({'error': 'permission_code is required'}), 400

    perm = PermissionCatalog(
        permission_code=data['permission_code'].strip(),
        description=data.get('description')
    )

    try:
        db.session.add(perm)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Permission code already exists'}), 409

    return jsonify({
        'message': 'Permission created',
        'permission': _permission_dict(perm)
    }), 201


@role_bp.route('/permissions/<int:permission_id>', methods=['DELETE'])
@auth_required
@permission_required('role.manage_permissions')
def delete_permission(permission_id: int):
    """
    Delete a permission from the catalogue.
    DELETE /api/roles/permissions/<permission_id>
    Returns 409 if any role still uses this permission.
    """
    perm = PermissionCatalog.query.get(permission_id)
    if not perm:
        abort(404, description='Permission not found')

    try:
        db.session.delete(perm)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete permission — it is still assigned to one or more roles'
        }), 409

    return jsonify({'message': 'Permission deleted'}), 200


# ─────────────────────────────────────────
# User ↔ Role Mapping
# ─────────────────────────────────────────

@role_bp.route('/users/<int:user_id>', methods=['GET'])
@auth_required
def get_user_roles(user_id: int):
    """
    Get all roles assigned to a user.
    GET /api/roles/users/<user_id>
    """
    mappings = UserRoleMapping.query.filter_by(user_id=user_id).all()
    role_ids  = [m.role_id for m in mappings]
    roles     = RoleMaster.query.filter(RoleMaster.role_id.in_(role_ids)).all() if role_ids else []
    return jsonify([_role_dict(r) for r in roles]), 200


@role_bp.route('/users/<int:user_id>', methods=['POST'])
@auth_required
@permission_required('role.assign_user')
def assign_role_to_user(user_id: int):
    """
    Assign a role to a user.
    POST /api/roles/users/<user_id>
    Body: { "role_id": 3 }
    """
    data = request.get_json() or {}

    role_id = data.get('role_id')
    if not role_id:
        return jsonify({'error': 'role_id is required'}), 400

    if not RoleMaster.query.get(int(role_id)):
        return jsonify({'error': 'Role not found'}), 404

    if UserRoleMapping.query.filter_by(user_id=user_id, role_id=role_id).first():
        return jsonify({'error': 'Role already assigned to this user'}), 409

    mapping = UserRoleMapping(user_id=user_id, role_id=int(role_id))

    try:
        db.session.add(mapping)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Role already assigned to this user'}), 409

    return jsonify({'message': 'Role assigned to user'}), 201


@role_bp.route('/users/<int:user_id>/bulk', methods=['POST'])
@auth_required
@permission_required('role.assign_user')
def bulk_assign_user_roles(user_id: int):
    """
    Replace all roles for a user in one atomic call.
    POST /api/roles/users/<user_id>/bulk
    Body: { "role_ids": [1, 3, 5] }
    """
    data = request.get_json() or {}
    role_ids = data.get('role_ids', [])

    if not isinstance(role_ids, list):
        return jsonify({'error': 'role_ids must be a list'}), 400

    # Validate all role_ids exist
    if role_ids:
        found = RoleMaster.query.filter(RoleMaster.role_id.in_(role_ids)).count()
        if found != len(set(role_ids)):
            return jsonify({'error': 'One or more role_ids are invalid'}), 400

    try:
        UserRoleMapping.query.filter_by(user_id=user_id).delete()
        for rid in set(role_ids):
            db.session.add(UserRoleMapping(user_id=user_id, role_id=rid))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Failed to update user roles'}), 409

    return jsonify({
        'message': f'{len(set(role_ids))} role(s) applied to user',
        'role_ids': list(set(role_ids))
    }), 200


@role_bp.route('/users/<int:user_id>/<int:role_id>', methods=['DELETE'])
@auth_required
@permission_required('role.revoke_user')
def revoke_role_from_user(user_id: int, role_id: int):
    """
    Remove a role from a user.
    DELETE /api/roles/users/<user_id>/<role_id>
    """
    mapping = UserRoleMapping.query.filter_by(
        user_id=user_id, role_id=role_id
    ).first()
    if not mapping:
        abort(404, description='Role assignment not found')

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({'message': 'Role revoked from user'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _role_or_404(role_id: int) -> RoleMaster:
    role = RoleMaster.query.get(role_id)
    if not role:
        abort(404, description='Role not found')
    return role


def _role_dict(r: RoleMaster) -> dict:
    return {
        'role_id':          r.role_id,
        'role_name':        r.role_name,
        'role_description': r.role_description,
        'is_system':        r.is_system,
        'created_at':       r.created_at.isoformat() if r.created_at else None,
    }


def _permission_dict(p: PermissionCatalog) -> dict:
    return {
        'permission_id':   p.permission_id,
        'permission_code': p.permission_code,
        'description':     p.description,
        'created_at':      p.created_at.isoformat() if p.created_at else None,
    }