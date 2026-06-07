"""
Team Routes
Handles salesperson/team management.
Uses OpportunityDetails to derive team stats.

GET  /api/teams/salespeople        — list employees with opportunity counts
GET  /api/teams/salespeople/<id>   — single salesperson stats
GET  /api/teams/leaderboard        — ranked by won opportunities
"""

from flask import Blueprint, g, jsonify
from sqlalchemy import func
from database import db
from middleware import auth_required
from models import EmployeeMaster, OpportunityDetails

team_bp = Blueprint("team", __name__, url_prefix="/teams")


def _salesperson_dict(emp: EmployeeMaster, opp_stats: dict) -> dict:
    stats = opp_stats.get(emp.employee_id, {})
    return {
        "employee_id":   emp.employee_id,
        "name":          emp.employee_name,
        "email":         emp.email,
        "phone":         emp.phone,
        "designation":   emp.designation.designation_description if emp.designation else None,
        "total_opps":    stats.get("total", 0),
        "won_opps":      stats.get("won", 0),
        "active_opps":   stats.get("active", 0),
        "pipeline_value": stats.get("value", 0.0),
    }


def _build_opp_stats(tenant_id: str) -> dict:
    """
    Returns a dict keyed by employee_id with opportunity stats.
    Queries OpportunityDetails once and aggregates in Python.
    """
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


@team_bp.route("/salespeople", methods=["GET"])
@auth_required
def list_salespeople():
    """
    GET /api/teams/salespeople
    Returns all employees for the tenant with their opportunity stats.
    """
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
@auth_required
def get_salesperson(employee_id: int):
    """
    GET /api/teams/salespeople/<employee_id>
    Returns a single employee with full opportunity stats.
    """
    tid = str(g.tenant_id)
    emp = EmployeeMaster.query.filter_by(
        employee_id=employee_id,
        tenant_id=tid,
    ).first()

    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    stats = _build_opp_stats(tid)
    return jsonify(_salesperson_dict(emp, stats)), 200


@team_bp.route("/leaderboard", methods=["GET"])
@auth_required
def leaderboard():
    """
    GET /api/teams/leaderboard
    Returns employees ranked by won opportunities descending.
    """
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