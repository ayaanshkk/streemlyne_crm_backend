"""
routes/usage_routes.py
─────────────────────
Usage & limits API endpoints.

GET  /api/usage/me          — full usage snapshot for current tenant
GET  /api/usage/warnings    — warnings for resources above 80%
"""

from flask import Blueprint, g, jsonify
from middleware import auth_required
from services.usage_service import get_usage_snapshot, get_usage_warnings

usage_bp = Blueprint("usage", __name__, url_prefix="/usage")


@usage_bp.route("/me", methods=["GET"])
@auth_required
def get_my_usage():
    """
    GET /api/usage/me
    Returns current usage + plan limits for the authenticated tenant.
    """
    snapshot = get_usage_snapshot(str(g.tenant_id))
    return jsonify(snapshot), 200


@usage_bp.route("/warnings", methods=["GET"])
@auth_required
def get_my_warnings():
    """
    GET /api/usage/warnings
    Returns list of warnings for resources above 80% usage.
    Empty list = all good.
    """
    warnings = get_usage_warnings(str(g.tenant_id))
    return jsonify(warnings), 200
