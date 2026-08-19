"""
Client Interactions Routes
Handles logging and retrieval of client interactions (calls, emails, meetings).

GET    /api/clients/<client_id>/interactions          — list all interactions
POST   /api/clients/<client_id>/interactions          — log a new interaction
DELETE /api/clients/<client_id>/interactions/<id>     — delete an interaction

GET    /api/clients/<client_id>/assign                — get current assigned employee
PUT    /api/clients/<client_id>/assign                — assign employee to client

NOTE: contact_method maps to Contact_Method_Master:
  1 = Phone, 2 = Email, 3 = In Person, 4 = Other
  These are seeded on first request via _seed_contact_methods().

  call_status (Called, Not Called, Callback, Not Answered, Left Voicemail, Meeting Booked)
  is stored in the `next_steps` column since Client_Interactions has no dedicated
  status column. Migrate to a proper column when schema can be updated.
"""

from datetime import date, datetime
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from database import db
from middleware import auth_required
from models import ClientInteractions, ClientMaster, ContactMethodMaster, EmployeeMaster

interactions_bp = Blueprint("interactions", __name__)

# ── Constants ────────────────────────────────────────────────────────────────

CONTACT_METHODS = [
    {"method_name": "Phone",     "method_description": "Phone call",     "is_active": True},
    {"method_name": "Email",     "method_description": "Email contact",  "is_active": True},
    {"method_name": "In Person", "method_description": "In-person visit","is_active": True},
    {"method_name": "Other",     "method_description": "Other method",   "is_active": True},
]

# Method name → ID cache (populated on first use)
_METHOD_ID_CACHE: dict = {}

CALL_STATUSES = [
    "Not Called",
    "Called",
    "Not Answered",
    "Left Voicemail",
    "Callback Requested",
    "Meeting Booked",
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _seed_contact_methods() -> None:
    """
    Ensure Phone/Email/In Person/Other exist in Contact_Method_Master.
    Safe to call multiple times — only inserts missing rows.
    Does not touch rows other projects may have added.
    """
    for m in CONTACT_METHODS:
        exists = ContactMethodMaster.query.filter_by(method_name=m["method_name"]).first()
        if not exists:
            row = ContactMethodMaster(
                method_name=m["method_name"],
                method_description=m["method_description"],
                is_active=m["is_active"],
                created_at=datetime.utcnow(),
            )
            db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def _get_method_id(method_name: str) -> int:
    """Return contact_method_id for a given method name, seeding if needed."""
    global _METHOD_ID_CACHE
    if not _METHOD_ID_CACHE:
        _seed_contact_methods()
        rows = ContactMethodMaster.query.all()
        _METHOD_ID_CACHE = {r.method_name: r.contact_method_id for r in rows}
    return _METHOD_ID_CACHE.get(method_name, 1)  # default to Phone (1)


def _get_method_name(method_id: int) -> str:
    """Reverse lookup: contact_method_id → method_name."""
    global _METHOD_ID_CACHE
    if not _METHOD_ID_CACHE:
        _seed_contact_methods()
        rows = ContactMethodMaster.query.all()
        _METHOD_ID_CACHE = {r.method_name: r.contact_method_id for r in rows}
    reverse = {v: k for k, v in _METHOD_ID_CACHE.items()}
    return reverse.get(method_id, "Phone")


def _interaction_dict(i: ClientInteractions, employee_name: str | None = None) -> dict:
    return {
        "interaction_id":  i.interaction_id,
        "client_id":       i.client_id,
        "contact_date":    i.contact_date.isoformat() if i.contact_date else None,
        "contact_method":  i.contact_method,
        "contact_method_name": _get_method_name(i.contact_method),
        # call_status is stored in next_steps — see module docstring
        "call_status":     i.next_steps or "Not Called",
        "notes":           i.notes,
        "reminder_date":   i.reminder_date.isoformat() if i.reminder_date else None,
        "created_at":      i.created_at.isoformat() if i.created_at else None,
        "logged_by":       employee_name,
    }


def _get_client_or_404(client_id: int):
    client = ClientMaster.query.filter_by(
        client_id=client_id,
        tenant_id=str(g.tenant_id),
    ).first()
    if not client:
        return None
    return client


# ── Routes ───────────────────────────────────────────────────────────────────

@interactions_bp.route("/clients/<int:client_id>/interactions", methods=["GET"])
@auth_required
def list_interactions(client_id: int):
    """
    GET /api/clients/<client_id>/interactions
    Returns all interactions for this client, newest first.
    """
    client = _get_client_or_404(client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    interactions = (
        ClientInteractions.query
        .filter_by(client_id=client_id)
        .order_by(ClientInteractions.created_at.desc())
        .all()
    )

    # Fetch all employees once for name lookup
    employees = EmployeeMaster.query.filter_by(tenant_id=str(g.tenant_id)).all()
    emp_map = {e.employee_id: e.employee_name for e in employees}

    return jsonify([
        _interaction_dict(i, emp_map.get(i.contact_method))
        for i in interactions
    ]), 200


@interactions_bp.route("/clients/<int:client_id>/interactions", methods=["POST"])
@auth_required
def create_interaction(client_id: int):
    """
    POST /api/clients/<client_id>/interactions
    Body:
    {
        "contact_method_name": "Phone",        — "Phone"|"Email"|"In Person"|"Other"
        "call_status": "Called",               — see CALL_STATUSES
        "notes": "Spoke about renewal...",
        "contact_date": "2026-08-19",          — ISO date, defaults to today
        "reminder_date": "2026-08-26",         — optional
        "assigned_to": 3                       — employee_id, optional
    }
    """
    client = _get_client_or_404(client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    data = request.get_json() or {}

    # ── Resolve contact_method_id ────────────────────────────────────────────
    # Seed first, then look up — guarantees the row exists before we reference it
    _seed_contact_methods()
    global _METHOD_ID_CACHE
    _METHOD_ID_CACHE = {}  # force fresh reload after seed
    rows = ContactMethodMaster.query.filter_by(is_active=True).all()
    _METHOD_ID_CACHE = {r.method_name: r.contact_method_id for r in rows}

    method_name = data.get("contact_method_name", "Phone")
    method_id   = _METHOD_ID_CACHE.get(method_name)
    if not method_id:
        # fallback: use first available method
        method_id = rows[0].contact_method_id if rows else None
    if not method_id:
        return jsonify({"error": "No contact methods found. Please seed Contact_Method_Master."}), 500

    call_status = data.get("call_status", "Not Called")
    notes       = (data.get("notes") or "").strip() or None

    # ── contact_date — always provide an explicit date, never rely on default ─
    contact_date_str = data.get("contact_date")
    if contact_date_str:
        try:
            contact_date = date.fromisoformat(str(contact_date_str).strip())
        except ValueError:
            return jsonify({"error": "Invalid contact_date format. Use YYYY-MM-DD"}), 400
    else:
        contact_date = date.today()

    reminder_date = None
    if data.get("reminder_date"):
        try:
            reminder_date = date.fromisoformat(str(data["reminder_date"]).strip())
        except ValueError:
            return jsonify({"error": "Invalid reminder_date format. Use YYYY-MM-DD"}), 400

    interaction = ClientInteractions(
        client_id=client_id,
        contact_date=contact_date,          # explicit — satisfies NOT NULL
        contact_method=method_id,           # resolved integer FK
        notes=notes,
        next_steps=call_status,             # call_status stored here — see module docstring
        reminder_date=reminder_date,
        created_at=datetime.utcnow(),
    )

    # Optionally update assigned employee on client
    assigned_to = data.get("assigned_to")
    if assigned_to:
        emp = EmployeeMaster.query.filter_by(
            employee_id=int(assigned_to),
            tenant_id=str(g.tenant_id),
        ).first()
        if emp:
            client.assigned_employee_name = emp.employee_name  # type: ignore[attr-defined]

    db.session.add(interaction)
    db.session.commit()

    return jsonify(_interaction_dict(interaction)), 201


@interactions_bp.route("/clients/<int:client_id>/interactions/<int:interaction_id>", methods=["DELETE"])
@auth_required
def delete_interaction(client_id: int, interaction_id: int):
    """
    DELETE /api/clients/<client_id>/interactions/<interaction_id>
    """
    client = _get_client_or_404(client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    interaction = ClientInteractions.query.filter_by(
        interaction_id=interaction_id,
        client_id=client_id,
    ).first()

    if not interaction:
        return jsonify({"error": "Interaction not found"}), 404

    db.session.delete(interaction)
    db.session.commit()
    return jsonify({"message": "Interaction deleted"}), 200


@interactions_bp.route("/clients/<int:client_id>/assign", methods=["PUT"])
@auth_required
def assign_employee(client_id: int):
    """
    PUT /api/clients/<client_id>/assign
    Body: { "employee_id": 3 }
    Updates the assigned_employee_name on Client_Master.
    """
    client = _get_client_or_404(client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    data = request.get_json() or {}
    employee_id = data.get("employee_id")

    if not employee_id:
        return jsonify({"error": "employee_id is required"}), 400

    emp = EmployeeMaster.query.filter_by(
        employee_id=int(employee_id),
        tenant_id=str(g.tenant_id),
    ).first()

    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    client.assigned_employee_name = emp.employee_name  # type: ignore[attr-defined]
    db.session.commit()

    return jsonify({
        "message": "Employee assigned",
        "employee_id": emp.employee_id,
        "employee_name": emp.employee_name,
    }), 200


@interactions_bp.route("/clients/interaction-options", methods=["GET"])
@auth_required
def get_interaction_options():
    """
    GET /api/clients/interaction-options
    Returns contact methods and call statuses for frontend dropdowns.
    """
    _seed_contact_methods()
    methods = ContactMethodMaster.query.filter_by(is_active=True).all()
    employees = EmployeeMaster.query.filter_by(tenant_id=str(g.tenant_id)).order_by(EmployeeMaster.employee_name).all()

    return jsonify({
        "contact_methods": [{"id": m.contact_method_id, "name": m.method_name} for m in methods],
        "call_statuses":   CALL_STATUSES,
        "employees":       [{"employee_id": e.employee_id, "name": e.employee_name} for e in employees],
    }), 200