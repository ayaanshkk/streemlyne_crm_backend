"""
middleware/access_control.py
────────────────────────────
Record-level access control for StreemLyne.

Rules:
  Platform Admin  — full access
  Manager         — full access
  Salesperson     — read all, write own only (assigned_employee_id or created_by_employee_id)
  Viewer          — read only, no write at all

Usage in route files:
    from middleware.access_control import require_write_access, check_record_ownership, AccessDenied

    # 1. Block Viewers from any write route:
    @client_bp.route("/<int:client_id>", methods=["PUT"])
    @auth_required
    @require_write_access          # ← blocks Viewers
    def update_client(client_id):
        check_record_ownership(client)  # ← blocks Salesperson editing others' records
        ...

    # 2. On create routes — just @require_write_access (no ownership check needed)
    @client_bp.route("", methods=["POST"])
    @auth_required
    @require_write_access
    def create_client(): ...
"""

from functools import wraps
from flask import g, jsonify
from models import UserMaster

# ── Role constants (mirrors middleware/__init__.py) ────────────────────────────
_FULL_ACCESS_ROLES = {"Platform Admin", "Manager"}
_SALESPERSON_ROLE  = "Salesperson"
_VIEWER_ROLE       = "Viewer"


def _get_user_role() -> str | None:
    """Return the current user's primary role name, or None."""
    user = UserMaster.query.filter_by(user_id=g.user_id).first()
    if not user:
        return None
    roles = [r.role_name for r in (user.roles or [])]
    return roles[0] if roles else None


def _get_employee_id() -> int | None:
    """Return the current user's employee_id from g or UserMaster."""
    if hasattr(g, "employee_id") and g.employee_id:
        return int(g.employee_id)
    user = UserMaster.query.filter_by(user_id=g.user_id).first()
    return user.employee_id if user else None


# ── Decorators ─────────────────────────────────────────────────────────────────

def require_write_access(f):
    """
    Decorator: blocks Viewer role from any write (POST/PUT/PATCH/DELETE).
    Must be applied AFTER @auth_required.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        role = _get_user_role()
        if role == _VIEWER_ROLE:
            return jsonify({
                "error":   "Access denied",
                "message": "Viewers cannot create or modify records. Please contact your admin to change your role.",
            }), 403
        return f(*args, **kwargs)
    return decorated


# ── Record ownership check ─────────────────────────────────────────────────────

class AccessDenied(Exception):
    """Raised when a Salesperson tries to modify another user's record."""
    pass


def check_record_ownership(record, employee_id_field: str = "assigned_employee_id",
                            fallback_field: str = "created_by_employee_id") -> None:
    """
    For Salesperson role: raise AccessDenied if the record doesn't belong to them.
    For Admin/Manager: always passes.
    For Viewer: always passes (write is blocked before this is called).

    Call this inside your route handler AFTER fetching the record.

    Args:
        record:               SQLAlchemy model instance
        employee_id_field:    Primary ownership column (default: assigned_employee_id)
        fallback_field:       Fallback ownership column (default: created_by_employee_id)

    Raises:
        AccessDenied: if the current salesperson doesn't own this record
    """
    role = _get_user_role()

    # Admins and Managers — always allowed
    if role in _FULL_ACCESS_ROLES:
        return

    # Salesperson — check ownership
    if role == _SALESPERSON_ROLE:
        current_emp_id = _get_employee_id()
        if not current_emp_id:
            raise AccessDenied("Could not determine your employee ID.")

        owner_id = getattr(record, employee_id_field, None)
        if owner_id is None:
            owner_id = getattr(record, fallback_field, None)

        if owner_id is None:
            # Unassigned record — allow (salesperson can claim it)
            return

        if int(owner_id) != int(current_emp_id):
            raise AccessDenied(
                "You can only edit records assigned to you. "
                "Contact your manager to reassign this record."
            )


def handle_access_denied(e: AccessDenied):
    """Call this in your except block to return the right HTTP response."""
    return jsonify({
        "error":   "Access denied",
        "message": str(e),
    }), 403


# ── Convenience: ownership-aware query filter ──────────────────────────────────

def ownership_filter(model, role: str = None, employee_id: int = None):
    """
    Returns a SQLAlchemy filter expression for list queries.
    Salesperson: only sees own records.
    Admin/Manager/Viewer: sees all.

    Usage:
        clients = ClientMaster.query.filter_by(tenant_id=tid)
        clients = clients.filter(ownership_filter(ClientMaster))
        clients = clients.all()
    """
    if role is None:
        role = _get_user_role()
    if employee_id is None:
        employee_id = _get_employee_id()

    if role == _SALESPERSON_ROLE and employee_id:
        from sqlalchemy import or_
        return or_(
            model.assigned_employee_id == employee_id,
            model.created_by_employee_id == employee_id,
        )

    # All other roles — no filter (see everything)
    return True  # SQLAlchemy accepts True as "no filter"