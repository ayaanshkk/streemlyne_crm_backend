# routes/job_routes.py
from flask import Blueprint, request, jsonify
from database import db
from models import Job, Customer, generate_job_reference
from datetime import datetime, date
import json

job_bp = Blueprint("jobs", __name__)

def parse_iso_date_safe(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception:
            try:
                return datetime.fromisoformat(value).date()
            except Exception:
                return None
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value
    return None



@job_bp.route('/jobs/<int:job_id>', methods=['GET'])
def get_job_by_id(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(job.to_dict())


# ----------------------------
# Create Job
# ----------------------------
@job_bp.route("/jobs", methods=["POST"])
def create_job():
    data = request.json or {}

    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"error": "customer_id is required"}), 400

    customer = Customer.query.get(customer_id)
    if not customer:
        return jsonify({"error": "Invalid customer_id"}), 400

    due_date = parse_iso_date_safe(data.get("due_date"))
    start_date = parse_iso_date_safe(data.get("start_date"))
    completion_date = parse_iso_date_safe(data.get("completion_date"))

    job = Job(
        job_reference = data.get("job_reference") or generate_job_reference(),
        title = data.get("title") or data.get("job_name") or "New Job",
        job_type = data.get("job_type") or "General",
        stage = data.get("stage") or "Prospect",
        priority = data.get("priority") or "Medium",
        customer_id = customer_id,
        due_date = due_date,
        start_date = start_date,
        completion_date = completion_date,
        estimated_value = data.get("estimated_value"),
        agreed_value = data.get("agreed_value"),
        deposit_amount = data.get("deposit_amount"),
        deposit_due_date = parse_iso_date_safe(data.get("deposit_due_date")),
        location = data.get("location"),
        primary_contact = data.get("primary_contact"),
        account_manager = data.get("account_manager"),
        notes = data.get("notes"),
        tags = data.get("tags"),
        description = data.get("description"),
        requirements = data.get("requirements")
    )

    # accept team_members either as list or comma-separated string
    team_members = data.get("team_members") or data.get("team_member")
    if team_members:
        if isinstance(team_members, str):
            # split by comma or " and "
            parts = [p.strip() for p in (team_members.replace(" and ", ",").split(",")) if p.strip()]
            job.team_members = parts
        elif isinstance(team_members, list):
            job.team_members = team_members

    db.session.add(job)
    db.session.commit()

    return jsonify({
        "id": job.id,
        "job_reference": job.job_reference,
        "title": job.title,
        "stage": job.stage,
        "priority": job.priority,
        "customer_id": job.customer_id,
        "due_date": job.due_date.isoformat() if job.due_date else None,
        "team_members": job.team_members,
        "message": "Job created successfully"
    }), 201



# ----------------------------
# Get Single Job by ID
# ----------------------------
@job_bp.route("/jobs/<string:job_id>", methods=["GET"])
def get_single_job(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify({
        "id": job.id,
        "job_reference": job.job_reference,
        "title": job.title,
        "stage": job.stage,
        "priority": job.priority,
        "job_type": job.job_type,
        "customer_id": job.customer_id,
        "customer_name": job.customer.name if job.customer else None,
        "due_date": job.due_date.isoformat() if job.due_date else None,
        "start_date": job.start_date.isoformat() if job.start_date else None,
        "completion_date": job.completion_date.isoformat() if job.completion_date else None,
        "estimated_value": float(job.estimated_value) if job.estimated_value else None,
        "agreed_value": float(job.agreed_value) if job.agreed_value else None,
        "deposit_amount": float(job.deposit_amount) if job.deposit_amount else None,
        "deposit_due_date": job.deposit_due_date.isoformat() if job.deposit_due_date else None,
        "location": job.location,
        "primary_contact": job.primary_contact,
        "account_manager": job.account_manager,
        "team_members": job.team_members,
        "notes": job.notes,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None
    }), 200



# ----------------------------
# Get All Jobs (with filtering)
# ----------------------------
# replace the existing get_jobs function in job_routes.py with this

@job_bp.route("/jobs", methods=["GET"])
def get_jobs():
    ref = request.args.get("ref", type=str)
    customer_id = request.args.get("customer_id", type=str)

    # NEW FILTERS (from frontend params)
    stage = request.args.get("stage", type=str)
    priority = request.args.get("priority", type=str)
    account_manager = request.args.get("account_manager", type=str)
    team_member = request.args.get("team_member", type=str)   # treated as substring match against team_members JSON list
    team = request.args.get("team", type=str)
    from_date = request.args.get("from_date", type=str)
    to_date = request.args.get("to_date", type=str)

    query = Job.query

    # Basic filters
    if ref:
        query = query.filter(Job.job_reference == ref)
    if customer_id:
        query = query.filter(Job.customer_id == customer_id)

    # Stage / priority (case-insensitive)
    if stage:
        query = query.filter(Job.stage.ilike(f"%{stage}%"))
    if priority:
        query = query.filter(Job.priority.ilike(f"%{priority}%"))

    # account manager
    if account_manager:
        query = query.filter(Job.account_manager.ilike(f"%{account_manager}%"))

    # team filter - stored as text on job, if you have Job.team column use that; otherwise ignore if not present
    if team:
        # if Job has 'team' attribute, use it; otherwise ignore
        if hasattr(Job, "team"):
            query = query.filter(Job.team.ilike(f"%{team}%"))

    # team_member: search inside the JSON text for substring (simple)
    if team_member:
        query = query.filter(Job.team_members_json.ilike(f"%{team_member}%"))

    # date filters - parse as ISO-like YYYY-MM-DD; safe fallback to ignore invalid dates
    try:
        if from_date:
            fd = parse_iso_date_safe(from_date)
            if fd:
                query = query.filter(Job.due_date >= fd)
        if to_date:
            td = parse_iso_date_safe(to_date)
            if td:
                query = query.filter(Job.due_date <= td)
    except Exception:
        pass

    jobs = query.order_by(Job.created_at.desc()).all()

    def job_to_json(j):
        return {
            "id": j.id,
            "job_reference": j.job_reference,
            "title": j.title,
            "stage": j.stage,
            "priority": j.priority,
            "job_type": j.job_type,
            "customer_id": j.customer_id,
            "customer_name": j.customer.name if j.customer else None,
            "due_date": j.due_date.isoformat() if j.due_date else None,
            "estimated_value": float(j.estimated_value) if j.estimated_value else None,
            "agreed_value": float(j.agreed_value) if j.agreed_value else None,
            "deposit_amount": float(j.deposit_amount) if j.deposit_amount else None,
            "location": j.location,
            "account_manager": j.account_manager,
            "team_members": j.team_members,   # <-- use property (list)
            "team": getattr(j, "team", None),
            "primary_contact": j.primary_contact,
            "notes": j.notes,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None
        }

    return jsonify([job_to_json(j) for j in jobs]), 200


# ----------------------------
# Update Job
# ----------------------------
@job_bp.route("/jobs/<string:job_id>", methods=["PUT"])
def update_job(job_id):
    job = Job.query.get_or_404(job_id)
    data = request.json or {}

    # simple fields
    if "title" in data: job.title = data.get("title")
    if "job_reference" in data: job.job_reference = data.get("job_reference")
    if "stage" in data: job.stage = data.get("stage")
    if "priority" in data: job.priority = data.get("priority")
    if "job_type" in data: job.job_type = data.get("job_type")
    if "estimated_value" in data: job.estimated_value = data.get("estimated_value")
    if "agreed_value" in data: job.agreed_value = data.get("agreed_value")
    if "deposit_amount" in data: job.deposit_amount = data.get("deposit_amount")
    if "location" in data: job.location = data.get("location")
    if "account_manager" in data: job.account_manager = data.get("account_manager")
    if "primary_contact" in data: job.primary_contact = data.get("primary_contact")
    if "notes" in data: job.notes = data.get("notes")
    if "tags" in data: job.tags = data.get("tags")
    if "description" in data: job.description = data.get("description")
    if "requirements" in data: job.requirements = data.get("requirements")

    # team_members
    if "team_members" in data or "team_member" in data:
        raw = data.get("team_members") or data.get("team_member")
        if isinstance(raw, str):
            # support comma and "and"
            parts = [
                p.strip() for p in raw.replace(" and ", ",").split(",")
                if p.strip()
            ]
            job.team_members = parts
        elif isinstance(raw, list):
            job.team_members = raw

    # dates (safe)
    if "due_date" in data:
        parsed = parse_iso_date_safe(data.get("due_date"))
        if parsed: job.due_date = parsed

    if "start_date" in data:
        parsed = parse_iso_date_safe(data.get("start_date"))
        if parsed: job.start_date = parsed

    if "completion_date" in data:
        parsed = parse_iso_date_safe(data.get("completion_date"))
        if parsed: job.completion_date = parsed

    if "deposit_due_date" in data:
        parsed = parse_iso_date_safe(data.get("deposit_due_date"))
        if parsed: job.deposit_due_date = parsed

    db.session.commit()

    return jsonify({"message": "Job updated successfully"}), 200


# ----------------------------
# Delete Job
# ----------------------------
@job_bp.route("/jobs/<string:job_id>", methods=["DELETE"])
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({"message": "Job deleted successfully"}), 200
