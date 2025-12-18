# routes/job_routes.py
from flask import Blueprint, request, jsonify
from database import db
from models import Job, Customer, generate_job_reference
from datetime import datetime, date
import json
import pytz

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

    # -----------------------------
    # DATE HANDLING
    # -----------------------------

    # 1️⃣ DUE DATE - only if user explicitly sent it
    due_date = None
    if "due_date" in data and data.get("due_date"):
        due_date = parse_iso_date_safe(data.get("due_date"))

    # 2️⃣ COMPLETION
    completion_date = parse_iso_date_safe(data.get("completion_date")) if data.get("completion_date") else None
    deposit_due_date = parse_iso_date_safe(data.get("deposit_due_date")) if data.get("deposit_due_date") else None

    # 3️⃣ START DATE (client timezone aware)
    start_date = None

    # If user provided explicit start date → respect it
    if "start_date" in data and data.get("start_date"):
        parsed = parse_iso_date_safe(data.get("start_date"))
        if parsed:
            start_date = parsed

    # If user didn't give start_date → use client_today
    if not start_date:
        client_today = data.get("client_today")  # 👈 passed from frontend
        if client_today:
            parsed_client = parse_iso_date_safe(client_today)
            if parsed_client:
                start_date = parsed_client

    # Final fallback — server timezone (rarely used)
    if not start_date:
        start_date = datetime.now().date()


    # ----------------------------------------------------
    # FINANCIALS
    # ----------------------------------------------------
    estimated_value = data.get("estimated_value") if "estimated_value" in data else None
    agreed_value = data.get("agreed_value") if "agreed_value" in data else None
    deposit_amount = data.get("deposit_amount") if "deposit_amount" in data else None

    # ----------------------------------------------------
    # CREATE JOB
    # ----------------------------------------------------
    job = Job(
        job_reference=data.get("job_reference") or generate_job_reference(),
        title=data.get("title") or data.get("job_name") or "New Job",
        job_type=data.get("job_type") or "General",
        stage=data.get("stage") or "Prospect",
        priority=data.get("priority") or "Medium",
        customer_id=customer_id,

        start_date=start_date,
        due_date=due_date,
        completion_date=completion_date,
        deposit_due_date=deposit_due_date,

        estimated_value=estimated_value,
        agreed_value=agreed_value,
        deposit_amount=deposit_amount,

        location=data.get("location"),
        primary_contact=data.get("primary_contact"),
        notes=data.get("notes"),
        tags=data.get("tags"),
        description=data.get("description"),
        requirements=data.get("requirements")
    )

    # ----------------------------------------------------
    # TEAM MEMBERS
    # ----------------------------------------------------
    team_members = data.get("team_members") or data.get("team_member")
    if team_members:
        if isinstance(team_members, str):
            members = [p.strip() for p in team_members.replace(" and ", ",").split(",") if p.strip()]
            job.team_members = members
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
        "customer_name": customer.name,
        "start_date": job.start_date.isoformat() if job.start_date else None,
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
      #  "account_manager": job.account_manager,
        "team_members": job.team_members,
        "notes": job.notes,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None
    }), 200



# ----------------------------
# Get All Jobs (with filtering)
# ----------------------------
@job_bp.route("/jobs", methods=["GET"])
def get_jobs():
    ref = request.args.get("ref")
    customer_id = request.args.get("customer_id")

    stage = request.args.get("stage")
    priority = request.args.get("priority")
    team_member = request.args.get("team_member")

    # NEW: flexible date filters - FIXED to handle due_date parameter
    due_date = parse_iso_date_safe(request.args.get("due_date"))  # ADDED THIS
    from_date = parse_iso_date_safe(request.args.get("from_date"))
    to_date = parse_iso_date_safe(request.args.get("to_date"))

    query = Job.query

    # -----------------------
    # BASIC FILTERS
    # -----------------------
    if ref:
        query = query.filter(Job.job_reference == ref)

    if customer_id:
        query = query.filter(Job.customer_id == customer_id)

    if stage:
        query = query.filter(Job.stage.ilike(f"%{stage}%"))

    if priority:
        query = query.filter(Job.priority.ilike(f"%{priority}%"))

    if team_member:
        query = query.filter(Job.team_members_json.ilike(f"%{team_member}%"))

    # -----------------------
    # DATE FILTERS 
    # -----------------------

    # EXACT DUE DATE (highest priority)
    if due_date:
        query = query.filter(Job.due_date == due_date)

    # BOTH dates provided → check if exact-date case
    elif from_date and to_date:
        # EXACT DATE (same date)
        if from_date == to_date:
            query = query.filter(Job.due_date == from_date)
        # RANGE between two different dates
        else:
            query = query.filter(Job.due_date >= from_date)
            query = query.filter(Job.due_date <= to_date)

    # ONLY from_date → AFTER or ON this date
    elif from_date:
        query = query.filter(Job.due_date >= from_date)

    # ONLY to_date → BEFORE or ON this date
    elif to_date:
        query = query.filter(Job.due_date <= to_date)

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
            "start_date": j.start_date.isoformat() if j.start_date else None,
            "completion_date": j.completion_date.isoformat() if j.completion_date else None,
            "estimated_value": float(j.estimated_value) if j.estimated_value else None,
            "agreed_value": float(j.agreed_value) if j.agreed_value else None,
            "deposit_amount": float(j.deposit_amount) if j.deposit_amount else None,
            "team_members": j.team_members,
            "location": j.location,
            "primary_contact": j.primary_contact,
            "notes": j.notes,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None
        }

    return jsonify([job_to_json(j) for j in jobs])




# ----------------------------
# Update Job
# ----------------------------
@job_bp.route("/jobs/<string:job_id>", methods=["PUT"])
def update_job(job_id):
    job = Job.query.get_or_404(job_id)
    data = request.json or {}

    print(f"[DEBUG] Updating job {job_id} with data: {data}")  # Debug logging

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
    if "primary_contact" in data: job.primary_contact = data.get("primary_contact")
    if "notes" in data: job.notes = data.get("notes")
    if "tags" in data: job.tags = data.get("tags")
    if "description" in data: job.description = data.get("description")
    if "requirements" in data: job.requirements = data.get("requirements")

    # team_members — MERGE (append new members, keep existing)
    if "team_members" in data or "team_member" in data:
        raw = data.get("team_members") or data.get("team_member")

        # Normalize incoming to a list of clean names
        incoming = []
        if isinstance(raw, str):
            incoming = [p.strip() for p in raw.replace(" and ", ",").split(",") if p.strip()]
        elif isinstance(raw, list):
            # accept list directly
            incoming = [str(p).strip() for p in raw if str(p).strip()]

        # Ensure we have at least something
        if incoming:
            # Get current members (ensure it's a list)
            current = job.team_members or []
            # Merge preserving order: keep current first, then append new unique ones
            merged = list(current)  # shallow copy
            for name in incoming:
                # compare case-insensitively but keep original casing from incoming/current
                if not any(n.lower() == name.lower() for n in merged):
                    merged.append(name)

            job.team_members = merged


    # ✅ CRITICAL FIX: Handle all date fields properly
    # START DATE - explicitly check for it
    if "start_date" in data:
        parsed = parse_iso_date_safe(data.get("start_date"))
        if parsed:
            job.start_date = parsed
            print(f"[DEBUG] Start date updated to: {parsed}")
        else:
            print(f"[WARNING] Failed to parse start_date: {data.get('start_date')}")

    # DUE DATE
    if "due_date" in data:
        parsed = parse_iso_date_safe(data.get("due_date"))
        if parsed:
            job.due_date = parsed
            print(f"[DEBUG] Due date updated to: {parsed}")

    # COMPLETION DATE
    if "completion_date" in data:
        parsed = parse_iso_date_safe(data.get("completion_date"))
        if parsed:
            job.completion_date = parsed
            print(f"[DEBUG] Completion date updated to: {parsed}")

    # DEPOSIT DUE DATE
    if "deposit_due_date" in data:
        parsed = parse_iso_date_safe(data.get("deposit_due_date"))
        if parsed:
            job.deposit_due_date = parsed
            print(f"[DEBUG] Deposit due date updated to: {parsed}")

    # Commit changes
    try:
        db.session.commit()
        print(f"[DEBUG] Job {job_id} updated successfully")
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Failed to commit: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "id": job.id,
        "job_reference": job.job_reference,
        "title": job.title,
        "stage": job.stage,
        "priority": job.priority,
        "job_type": job.job_type,
        "customer_id": job.customer_id,
        "customer_name": job.customer.name if job.customer else None,
        "start_date": job.start_date.isoformat() if job.start_date else None,
        "due_date": job.due_date.isoformat() if job.due_date else None,
        "completion_date": job.completion_date.isoformat() if job.completion_date else None,
        "estimated_value": float(job.estimated_value) if job.estimated_value else None,
        "agreed_value": float(job.agreed_value) if job.agreed_value else None,
        "deposit_amount": float(job.deposit_amount) if job.deposit_amount else None,
        "deposit_due_date": job.deposit_due_date.isoformat() if job.deposit_due_date else None,
        "location": job.location,
        "primary_contact": job.primary_contact,
        "team_members": job.team_members,
        "notes": job.notes,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None
    }), 200


# ----------------------------
# Delete Job
# ----------------------------
@job_bp.route("/jobs/<string:job_id>", methods=["DELETE"])
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({"message": "Job deleted successfully"}), 200