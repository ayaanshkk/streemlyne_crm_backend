"""
Team Routes — invite system using User_Master columns only
No new tables — uses: invite_token, invite_expires_at, is_invite_pending, is_active

GET  /api/teams/salespeople            — list employees with opportunity counts
GET  /api/teams/salespeople/<id>       — single salesperson stats
GET  /api/teams/leaderboard            — ranked by won opportunities
PUT  /api/teams/members/<id>/role      — update role
POST /api/teams/invite                 — generate invite link
GET  /api/teams/invite/<token>/verify  — verify token (public, no auth)

POST /api/auth/accept-invite           — set username + password, activate account
     (paste this into your auth blueprint — see bottom of file)
"""

import os
import secrets
from datetime import datetime, timedelta
from middleware import auth_required, role_required
from middleware import CAN_INVITE_TEAM, CAN_MANAGE_ROLES
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError
from services.usage_service import check_customer_limit
from database import db
from middleware import auth_required
from models import (
    EmployeeMaster,
    OpportunityDetails,
    RoleMaster,
    UserMaster,
    UserRoleMapping,
)

team_bp = Blueprint("team", __name__, url_prefix="/teams")

INVITE_EXPIRY_HOURS = 72
FRONTEND_BASE_URL   = os.environ.get("FRONTEND_BASE_URL=http://localhost:3000", "http://localhost:3000")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _salesperson_dict(emp: EmployeeMaster, opp_stats: dict) -> dict:
    stats = opp_stats.get(emp.employee_id, {})

    role_name = None
    if emp.user and emp.user.roles:
        role_name = emp.user.roles[0].role_name

    return {
        "employee_id":    emp.employee_id,
        "name":           emp.employee_name,
        "email":          emp.email,
        "phone":          emp.phone,
        "designation":    emp.designation.designation_description if emp.designation else None,
        "role":           role_name,
        "total_opps":     stats.get("total", 0),
        "won_opps":       stats.get("won", 0),
        "active_opps":    stats.get("active", 0),
        "pipeline_value": stats.get("value", 0.0),
        "has_account":    emp.user is not None,
        "invite_pending": emp.user.is_invite_pending if emp.user else False,
    }


def _build_opp_stats(tenant_id: str) -> dict:
    opps = (
        OpportunityDetails.query
        .filter_by(tenant_id=tenant_id)
        .filter(OpportunityDetails.deleted_at.is_(None))
        .all()
    )
    stats: dict = {}
    for o in opps:
        eid = o.opportunity_owner_employee_id
        if not eid:
            continue
        s = stats.setdefault(eid, {"total": 0, "won": 0, "active": 0, "value": 0.0})
        s["total"] += 1
        if o.stage and o.stage.stage_name == "Won":
            s["won"] += 1
        elif o.stage and o.stage.stage_name not in ("Won", "Lost"):
            s["active"] += 1
        s["value"] += float(o.opportunity_value or 0)
    return stats


# ── Standard team endpoints ────────────────────────────────────────────────────

@team_bp.route("/salespeople", methods=["GET"])
@role_required("Platform Admin", "Manager")
def list_salespeople():
    tid = str(g.tenant_id)
    employees = (
        EmployeeMaster.query
        .filter_by(tenant_id=tid)
        .order_by(EmployeeMaster.employee_name)
        .all()
    )
    stats = _build_opp_stats(tid)
    return jsonify([_salesperson_dict(e, stats) for e in employees]), 200


@team_bp.route("/salespeople/<int:employee_id>", methods=["GET"])
@role_required("Platform Admin", "Manager")
def get_salesperson(employee_id: int):
    tid = str(g.tenant_id)
    emp = EmployeeMaster.query.filter_by(employee_id=employee_id, tenant_id=tid).first()
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    stats = _build_opp_stats(tid)
    return jsonify(_salesperson_dict(emp, stats)), 200


@team_bp.route("/leaderboard", methods=["GET"])
@role_required("Platform Admin", "Manager")
def leaderboard():
    tid = str(g.tenant_id)
    employees = EmployeeMaster.query.filter_by(tenant_id=tid).all()
    stats = _build_opp_stats(tid)
    ranked = sorted(
        [_salesperson_dict(e, stats) for e in employees],
        key=lambda x: (x["won_opps"], x["pipeline_value"]),
        reverse=True,
    )
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return jsonify(ranked), 200


@team_bp.route("/members/<int:employee_id>/role", methods=["PUT"])
@role_required(*CAN_MANAGE_ROLES)
def update_member_role(employee_id: int):
    tid = str(g.tenant_id)
    data = request.get_json() or {}
    role_name = data.get("role", "").strip()

    if not role_name:
        return jsonify({"error": "Role is required"}), 400

    emp = EmployeeMaster.query.filter_by(employee_id=employee_id, tenant_id=tid).first()
    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    role = RoleMaster.query.filter_by(role_name=role_name).first()
    if not role:
        return jsonify({"error": f"Role '{role_name}' not found"}), 400

    if emp.user:
        UserRoleMapping.query.filter_by(user_id=emp.user.user_id).delete()
        db.session.add(UserRoleMapping(user_id=emp.user.user_id, role_id=role.role_id))
        db.session.commit()

    return jsonify({"message": "Role updated"}), 200


# ── Invite ─────────────────────────────────────────────────────────────────────

@team_bp.route("/invite", methods=["POST"])
@role_required(*CAN_INVITE_TEAM)  
def create_invite():
    """
    POST /api/teams/invite
    Body: { "name", "email", "role", "phone"? }

    Flow:
      1. Find or create EmployeeMaster row
      2. Find or create UserMaster row — writes invite_token + invite_expires_at,
         sets is_invite_pending=True, is_active=False
      3. Assign role in UserRoleMapping
      4. Return the invite URL for the admin to copy
    """
    # ── Limit check ───────────────────────────────────────────────────────────
    err = check_user_limit(str(g.tenant_id))
    if err:
        return jsonify({"error": err, "limit_reached": True, "resource": "users"}), 403
    tid  = str(g.tenant_id)
    data = request.get_json() or {}

    name      = (data.get("name")  or "").strip()
    email     = (data.get("email") or "").lower().strip()
    role_name = (data.get("role")  or "").strip()
    phone     = (data.get("phone") or "").strip() or None

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not email:
        return jsonify({"error": "Email is required"}), 400
    if not role_name:
        return jsonify({"error": "Role is required"}), 400

    role = RoleMaster.query.filter_by(role_name=role_name).first()
    if not role:
        return jsonify({"error": f"Role '{role_name}' not found"}), 400

    # ── Find or create Employee ───────────────────────────────────────────────
    employee = EmployeeMaster.query.filter_by(email=email, tenant_id=tid).first()

    if employee:
        # Block re-invite if they already have a live account
        if employee.user and not employee.user.is_invite_pending:
            return jsonify({"error": "A user with this email already has an active account"}), 409
    else:
        employee = EmployeeMaster(
            tenant_id=tid,
            employee_name=name,
            email=email,
            phone=phone,
        )
        db.session.add(employee)
        db.session.flush()  # get employee_id

    # ── Token ─────────────────────────────────────────────────────────────────
    raw_token  = secrets.token_urlsafe(48)   # → 64-char URL-safe string
    expires_at = datetime.utcnow() + timedelta(hours=INVITE_EXPIRY_HOURS)

    # ── Find or create UserMaster ─────────────────────────────────────────────
    user = employee.user
    if user:
        # Re-invite: refresh token + expiry, keep everything else
        user.invite_token      = raw_token
        user.invite_expires_at = expires_at
        user.is_invite_pending = True
        user.is_active         = False
    else:
        user = UserMaster(
            employee_id            = employee.employee_id,
            tenant_id              = tid,
            user_name              = None,        # set by invitee on accept
            password               = None,        # set by invitee on accept
            is_active              = False,
            is_invite_pending      = True,
            invite_token           = raw_token,
            invite_expires_at      = expires_at,
            created_by_employee_id = getattr(g, "employee_id", None),
        )
        db.session.add(user)
        db.session.flush()

        # Role assignment
        db.session.add(UserRoleMapping(user_id=user.user_id, role_id=role.role_id))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Failed to create invite — please try again"}), 500

    invite_url = f"{FRONTEND_BASE_URL}/invite/{raw_token}"

    return jsonify({
        "message":     "Invite created",
        "invite_url":  invite_url,
        "employee_id": employee.employee_id,
        "name":        name,
        "email":       email,
        "role":        role_name,
        "expires_at":  expires_at.isoformat(),
    }), 201


@team_bp.route("/invite/<string:token>/verify", methods=["GET"])
def verify_invite(token: str):
    """
    GET /api/teams/invite/<token>/verify
    Public — no auth required.
    Validates the token and returns name/email/role for the accept page.
    """
    user = UserMaster.query.filter_by(invite_token=token).first()

    if not user:
        return jsonify({"error": "Invalid invite link"}), 404

    if not user.is_invite_pending:
        return jsonify({"error": "This invite has already been accepted"}), 410

    if not user.invite_expires_at or datetime.utcnow() > user.invite_expires_at:
        return jsonify({"error": "This invite link has expired — ask your admin to resend it"}), 410

    emp       = user.employee
    role_name = user.roles[0].role_name if user.roles else None

    return jsonify({
        "valid":      True,
        "name":       emp.employee_name if emp else None,
        "email":      emp.email         if emp else None,
        "role":       role_name,
        "expires_at": user.invite_expires_at.isoformat(),
    }), 200