
"""
Team Routes — team members, roles, invitations, and salesperson statistics.

Uses existing tables only:
Employee_Master, User_Master, User_Role_Mapping, Role_Master.
"""

import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from database import db
from middleware import CAN_INVITE_TEAM, CAN_MANAGE_ROLES, role_required
from models import (
    EmployeeMaster,
    OpportunityDetails,
    RoleMaster,
    UserMaster,
    UserRoleMapping,
)
from services.usage_service import check_limit


team_bp = Blueprint("team", __name__, url_prefix="/teams")

INVITE_EXPIRY_HOURS = 72
FRONTEND_BASE_URL = os.environ.get(
    "FRONTEND_BASE_URL",
    "http://localhost:3000",
)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _get_user_role(user):
    if user and user.roles:
        return user.roles[0]
    return None


def _team_member_dict(employee):
    user = employee.user
    role = _get_user_role(user)

    return {
        "user_id": user.user_id if user else None,
        "employee_id": employee.employee_id,
        "name": employee.employee_name,
        "email": employee.email,
        "phone": employee.phone,
        "username": getattr(user, "user_name", None) if user else None,
        "role_id": role.role_id if role else None,
        "role": role.role_name if role else None,
        "is_active": bool(user.is_active) if user else False,
        "invite_pending": bool(user.is_invite_pending) if user else False,
        "has_account": user is not None,
    }


def _salesperson_dict(employee, opp_stats):
    stats = opp_stats.get(employee.employee_id, {})
    role = _get_user_role(employee.user)

    return {
        "employee_id": employee.employee_id,
        "name": employee.employee_name,
        "email": employee.email,
        "phone": employee.phone,
        "designation": (
            employee.designation.designation_description
            if employee.designation else None
        ),
        "role": role.role_name if role else None,
        "total_opps": stats.get("total", 0),
        "won_opps": stats.get("won", 0),
        "active_opps": stats.get("active", 0),
        "pipeline_value": stats.get("value", 0.0),
        "has_account": employee.user is not None,
        "invite_pending": (
            bool(employee.user.is_invite_pending)
            if employee.user else False
        ),
    }


def _build_opp_stats(tenant_id):
    opportunities = (
        OpportunityDetails.query
        .filter_by(tenant_id=tenant_id)
        .filter(OpportunityDetails.deleted_at.is_(None))
        .all()
    )

    stats = {}

    for opportunity in opportunities:
        employee_id = opportunity.opportunity_owner_employee_id
        if not employee_id:
            continue

        row = stats.setdefault(
            employee_id,
            {"total": 0, "won": 0, "active": 0, "value": 0.0},
        )
        row["total"] += 1

        if opportunity.stage and opportunity.stage.stage_name == "Won":
            row["won"] += 1
        elif opportunity.stage and opportunity.stage.stage_name != "Lost":
            row["active"] += 1

        row["value"] += float(opportunity.opportunity_value or 0)

    return stats


def _find_role_from_payload(data):
    """Accept either {'role': 'Viewer'} or {'role_id': 9}."""
    role_id = data.get("role_id")
    role_name = data.get("role")

    if role_id is not None:
        try:
            return RoleMaster.query.filter_by(
                role_id=int(role_id)
            ).first()
        except (TypeError, ValueError):
            return None

    if isinstance(role_name, str) and role_name.strip():
        return RoleMaster.query.filter_by(
            role_name=role_name.strip()
        ).first()

    return None


def _replace_user_role(user_id, role_id):
    """Replace the existing role mapping for a user."""
    UserRoleMapping.query.filter_by(
        user_id=user_id
    ).delete(synchronize_session=False)

    db.session.add(
        UserRoleMapping(
            user_id=user_id,
            role_id=role_id,
        )
    )


# -------------------------------------------------------------------
# Team & Roles
# -------------------------------------------------------------------

@team_bp.route("/members", methods=["GET"])
@role_required("Tenant Super Admin", *CAN_MANAGE_ROLES)
def list_team_members():
    """
    GET /api/teams/members

    Lists accounts belonging to the current tenant.
    """
    tenant_id = g.tenant_id

    employees = (
        EmployeeMaster.query
        .filter_by(tenant_id=tenant_id)
        .order_by(EmployeeMaster.employee_name)
        .all()
    )

    members = [
        _team_member_dict(employee)
        for employee in employees
        if employee.user is not None
    ]

    return jsonify(members), 200


@team_bp.route("/roles", methods=["GET"])
@role_required("Tenant Super Admin", *CAN_MANAGE_ROLES)
def list_team_roles():
    """GET /api/teams/roles — returns roles for the settings dropdown."""
    roles = RoleMaster.query.order_by(RoleMaster.role_name).all()

    return jsonify([
        {
            "role_id": role.role_id,
            "role_name": role.role_name,
            "description": role.role_description,
        }
        for role in roles
    ]), 200


@team_bp.route("/members/<int:employee_id>/role", methods=["PUT"])
@role_required("Tenant Super Admin", *CAN_MANAGE_ROLES)
def update_member_role(employee_id):
    """
    PUT /api/teams/members/<employee_id>/role

    Body:
        {"role": "Viewer"}
    or:
        {"role_id": 9}
    """
    data = request.get_json(silent=True) or {}

    employee = EmployeeMaster.query.filter_by(
        employee_id=employee_id,
        tenant_id=g.tenant_id,
    ).first()

    if not employee:
        return jsonify({
            "error": "Employee not found in your tenant"
        }), 404

    user = employee.user

    if not user:
        return jsonify({
            "error": "This employee does not have a user account"
        }), 404

    role = _find_role_from_payload(data)

    if not role:
        return jsonify({
            "error": "A valid role or role_id is required"
        }), 400

    try:
        _replace_user_role(user.user_id, role.role_id)
        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "Could not save the selected role"
        }), 409

    except Exception:
        db.session.rollback()
        return jsonify({
            "error": "Failed to update role"
        }), 500

    return jsonify({
        "message": "Role updated successfully",
        "user_id": user.user_id,
        "employee_id": employee.employee_id,
        "role_id": role.role_id,
        "role": role.role_name,
    }), 200


# -------------------------------------------------------------------
# Salesperson statistics
# -------------------------------------------------------------------

@team_bp.route("/salespeople", methods=["GET"])
@role_required("Tenant Super Admin", "Platform Admin", "Manager")
def list_salespeople():
    tenant_id = g.tenant_id

    employees = (
        EmployeeMaster.query
        .filter_by(tenant_id=tenant_id)
        .order_by(EmployeeMaster.employee_name)
        .all()
    )

    stats = _build_opp_stats(tenant_id)

    return jsonify([
        _salesperson_dict(employee, stats)
        for employee in employees
    ]), 200


@team_bp.route("/salespeople/<int:employee_id>", methods=["GET"])
@role_required("Tenant Super Admin", "Platform Admin", "Manager")
def get_salesperson(employee_id):
    employee = EmployeeMaster.query.filter_by(
        employee_id=employee_id,
        tenant_id=g.tenant_id,
    ).first()

    if not employee:
        return jsonify({"error": "Employee not found"}), 404

    stats = _build_opp_stats(g.tenant_id)

    return jsonify(_salesperson_dict(employee, stats)), 200


@team_bp.route("/leaderboard", methods=["GET"])
@role_required("Tenant Super Admin", "Platform Admin", "Manager")
def leaderboard():
    employees = EmployeeMaster.query.filter_by(
        tenant_id=g.tenant_id
    ).all()

    stats = _build_opp_stats(g.tenant_id)

    ranked = sorted(
        [_salesperson_dict(employee, stats) for employee in employees],
        key=lambda row: (row["won_opps"], row["pipeline_value"]),
        reverse=True,
    )

    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank

    return jsonify(ranked), 200


# -------------------------------------------------------------------
# Invitations
# -------------------------------------------------------------------

@team_bp.route("/invite", methods=["POST"])
@role_required(*CAN_INVITE_TEAM)
def create_invite():
    """
    POST /api/teams/invite

    Body:
        {
            "name": "Example User",
            "email": "user@example.com",
            "role": "Viewer",
            "phone": "..."
        }
    """
    tenant_id = g.tenant_id
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip() or None

    if not name:
        return jsonify({"error": "Name is required"}), 400

    if not email:
        return jsonify({"error": "Email is required"}), 400

    role = _find_role_from_payload(data)

    if not role:
        return jsonify({
            "error": "A valid role or role_id is required"
        }), 400

    employee = EmployeeMaster.query.filter_by(
        email=email,
        tenant_id=tenant_id,
    ).first()

    # Check plan limits for a genuinely new account.
    if not (employee and employee.user):
        limit_payload = check_limit(str(tenant_id), "users")
        if limit_payload:
            return jsonify(limit_payload), 403

    if employee and employee.user and not employee.user.is_invite_pending:
        return jsonify({
            "error": "A user with this email already has an active account"
        }), 409

    try:
        if employee is None:
            employee = EmployeeMaster(
                tenant_id=tenant_id,
                employee_name=name,
                email=email,
                phone=phone,
            )
            db.session.add(employee)
            db.session.flush()
        else:
            employee.employee_name = name
            if phone:
                employee.phone = phone

        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(
            hours=INVITE_EXPIRY_HOURS
        )

        user = employee.user

        if user is None:
            placeholder_password = secrets.token_urlsafe(48)

            user = UserMaster(
                employee_id=employee.employee_id,
                tenant_id=tenant_id,
                user_name=(
                    f"pending_{employee.employee_id}_{secrets.token_hex(6)}"
                ),
                password=generate_password_hash(placeholder_password),
                is_active=False,
                is_invite_pending=True,
                invite_token=raw_token,
                invite_expires_at=expires_at,
                created_by_employee_id=getattr(g, "employee_id", None),
            )

            db.session.add(user)
            db.session.flush()

        else:
            # Resend invitation for an existing pending account.
            user.invite_token = raw_token
            user.invite_expires_at = expires_at
            user.is_invite_pending = True
            user.is_active = False

        # Assign the requested role for new and resent invitations.
        _replace_user_role(user.user_id, role.role_id)

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": (
                "Failed to create invitation. Check for duplicate "
                "email or username."
            )
        }), 409

    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to create invitation"}), 500

    invite_url = (
        f"{FRONTEND_BASE_URL.rstrip('/')}/invite/{raw_token}"
    )

    return jsonify({
        "message": "Invite created",
        "invite_url": invite_url,
        "employee_id": employee.employee_id,
        "name": name,
        "email": email,
        "role": role.role_name,
        "role_id": role.role_id,
        "expires_at": expires_at.isoformat(),
    }), 201


@team_bp.route("/invite/<string:token>/verify", methods=["GET"])
def verify_invite(token):
    """Public endpoint to validate an invitation token."""
    user = UserMaster.query.filter_by(
        invite_token=token
    ).first()

    if not user:
        return jsonify({"error": "Invalid invite link"}), 404

    if not user.is_invite_pending:
        return jsonify({
            "error": "This invite has already been accepted"
        }), 410

    if (
        not user.invite_expires_at
        or datetime.utcnow() > user.invite_expires_at
    ):
        return jsonify({
            "error": (
                "This invite link has expired — ask your admin to resend it"
            )
        }), 410

    employee = user.employee
    role = _get_user_role(user)

    return jsonify({
        "valid": True,
        "name": employee.employee_name if employee else None,
        "email": employee.email if employee else None,
        "role": role.role_name if role else None,
        "role_id": role.role_id if role else None,
        "expires_at": user.invite_expires_at.isoformat(),
    }), 200
