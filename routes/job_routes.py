# routes/job_routes.py
from flask import Blueprint, request, jsonify
from database import db
from models import Job, Customer, Opportunity, generate_job_reference
from datetime import datetime, date
from sqlalchemy import func
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

    job = Job()

    job.job_reference = data.get("job_reference") or generate_job_reference()
    job.title = data.get("title") or data.get("job_name") or "New Job"
    job.job_type = data.get("job_type") or "General"
    job.stage = data.get("stage") or "Prospect"
    job.priority = data.get("priority") or "Medium"
    job.customer_id = customer_id

    job.due_date = due_date
    job.start_date = start_date
    job.completion_date = completion_date

    job.estimated_value = data.get("estimated_value")
    job.agreed_value = data.get("agreed_value")
    job.deposit_amount = data.get("deposit_amount")
    job.deposit_due_date = parse_iso_date_safe(data.get("deposit_due_date"))

    job.location = data.get("location")
    job.primary_contact = data.get("primary_contact")
    job.account_manager = data.get("account_manager")
    job.notes = data.get("notes")
    job.tags = data.get("tags")
    job.description = data.get("description")
    job.requirements = data.get("requirements")
    

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

@job_bp.route("/jobs", methods=["GET"])
def get_jobs():
    from sqlalchemy.orm import Query
    
    ref = request.args.get("ref", type=str)
    customer_id = request.args.get("customer_id", type=str)
    stage = request.args.get("stage", type=str)
    priority = request.args.get("priority", type=str)
    account_manager = request.args.get("account_manager", type=str)
    team_member = request.args.get("team_member", type=str)
    team = request.args.get("team", type=str)
    from_date = request.args.get("from_date", type=str)
    to_date = request.args.get("to_date", type=str)

    query = Job.query  # type: Query

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

    # team filter (search inside team_members_json)
    if team:
        query = query.filter(Job.team_members_json.ilike(f"%{team}%"))

    # team_member filter (same backing column)
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

@job_bp.route('/jobs/pipeline-opportunities', methods=['GET'])
def get_pipeline_opportunities():
    """
    Fetch customers in "Closed Won" stage for Jobs Pipeline view.
    Distributed across job workflow stages.
    """
    print("🔍 DEBUG: /jobs/pipeline-opportunities endpoint called")
    
    CLOSED_WON_STAGE = "Closed Won"
    
    # Query CUSTOMERS in "Closed Won" stage only
    customers = Customer.query.filter(
        Customer.stage == CLOSED_WON_STAGE
    ).order_by(Customer.updated_at.desc()).all()
    
    print(f"🔍 DEBUG: Found {len(customers)} customers in 'Closed Won' stage")
    
    # Build response with job_workflow_stage
    pipeline_items = []
    for customer in customers:
        # Use correct column name: jobworkflowstage
        job_workflow_stage = getattr(customer, 'job_workflow_stage', None) or "New"
        
        item = {
            "id": customer.id,
            "opportunity_name": customer.name,
            "opportunity_reference": f"CUST-{str(customer.id)[:4].upper()}",
            "stage": customer.stage,
            "job_workflow_stage": job_workflow_stage,
            "priority": getattr(customer, 'priority', 'Medium') or "Medium",
            "estimated_value": float(customer.estimatedvalue) if hasattr(customer, 'estimatedvalue') and customer.estimatedvalue else None,
            "probability": getattr(customer, 'probability', None),
            "expected_close_date": None,
            "actual_close_date": customer.updated_at.isoformat() if customer.updated_at else None,
            "salesperson_name": customer.salesperson,
            "notes": getattr(customer, 'notes', None),
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
            "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "company_name": customer.company_name,  # FIX: Use company_name with underscore
                "email": customer.email,
                "phone": customer.phone,
                "address": customer.address,
                "stage": customer.stage,
                "salesperson": customer.salesperson,
            }
        }
        pipeline_items.append(item)
        print(f"  → {customer.name} | Sales: {customer.stage}, Job: {job_workflow_stage}")
    
    print(f"🔍 DEBUG: Returning {len(pipeline_items)} items")
    return jsonify(pipeline_items), 200

# Update job workflow stage
# Update job workflow stage - MODIFIED TO BROADCAST SSE
@job_bp.route('/jobs/pipeline-opportunities/<string:customer_id>/stage', methods=['PUT'])
def update_pipeline_opportunity_stage(customer_id):
    """Update the job_workflow_stage for a customer in the Jobs Pipeline."""
    print(f"🔧 DEBUG: Update stage called for customer {customer_id}")
    
    customer = Customer.query.get(customer_id)
    if not customer:
        print(f"❌ ERROR: Customer {customer_id} not found")
        return jsonify({"error": "Customer not found"}), 404
    
    data = request.json or {}
    print(f"📥 DEBUG: Received data: {data}")
    
    # Accept both formats: job_workflow_stage and jobworkflowstage
    new_stage = data.get('job_workflow_stage') or data.get('jobworkflowstage')
    
    if not new_stage:
        print("❌ ERROR: No stage provided in request")
        return jsonify({"error": "job_workflow_stage is required"}), 400
    
    # Validate stage
    valid_stages = ["New", "Assigned", "In Progress", "On Hold Waiting", "Review", "Completed"]
    if new_stage not in valid_stages:
        print(f"❌ ERROR: Invalid stage '{new_stage}'")
        return jsonify({"error": f"Invalid job_workflow_stage. Must be one of {valid_stages}"}), 400
    
    old_stage = customer.job_workflow_stage
    customer.job_workflow_stage = new_stage
    
    try:
        db.session.commit()
        print(f"✅ SUCCESS: Updated customer {customer.name} from '{old_stage}' to '{new_stage}'")
        
        # 🚀 NEW: Broadcast SSE event for real-time update
        from app import broadcast_sse_event
        broadcast_sse_event("workflow_stage_updated", {
            "customer_id": customer.id,
            "customer_name": customer.name,
            "old_stage": old_stage,
            "new_stage": new_stage,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return jsonify({
            "message": "Job workflow stage updated successfully",
            "customer_id": customer.id,
            "job_workflow_stage": customer.job_workflow_stage,
            "old_stage": old_stage
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR: Database commit failed: {str(e)}")
        return jsonify({"error": f"Failed to update stage: {str(e)}"}), 500
        return jsonify({"error": f"Failed to update stage: {str(e)}"}), 500