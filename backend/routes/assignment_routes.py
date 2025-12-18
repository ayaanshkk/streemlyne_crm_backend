from flask import Blueprint, request, jsonify, g
from datetime import datetime, date
from database import db
from models import Assignment, TeamMember, Job, Customer
from tenant_middleware import require_tenant  # ✅ ADDED

assignment_bp = Blueprint("assignment", __name__, url_prefix="/assignments")


# ✅ VALID ASSIGNMENT FIELDS - Based on working project
VALID_ASSIGNMENT_FIELDS = [
    'type', 'title', 'date', 'start_date', 'end_date', 'customer_name',
    'user_id', 'team_member', 'job_id', 'customer_id', 'job_type',
    'start_time', 'end_time', 'estimated_hours',
    'notes', 'priority', 'status', 'staff_name', 'staff_id'
]


def filter_assignment_data(data):
    """Filter request data to only include valid Assignment fields"""
    filtered = {}
    for key in VALID_ASSIGNMENT_FIELDS:
        if key in data:
            filtered[key] = data[key]
    return filtered


# -----------------------------
# GET assignments for a month
# -----------------------------
@assignment_bp.route("", methods=["GET"])
@require_tenant  # ✅ ADDED
def get_assignments():
    """Get all assignments, optionally filtered by month"""
    month = request.args.get("month")  # YYYY-MM

    # ✅ FILTER BY TENANT
    query = Assignment.query.filter_by(tenant_id=g.tenant_id)

    if month:
        try:
            year, month_num = map(int, month.split("-"))
            start_date = date(year, month_num, 1)
            if month_num == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month_num + 1, 1)

            query = query.filter(
                Assignment.date >= start_date,
                Assignment.date < end_date
            )
        except ValueError:
            return jsonify({"error": "Invalid month format. Use YYYY-MM"}), 400

    assignments = query.order_by(Assignment.date.desc()).all()
    return jsonify([a.to_dict() for a in assignments])


# -----------------------------
# CREATE assignment
# -----------------------------
@assignment_bp.route("", methods=["POST"])
@require_tenant  # ✅ ADDED
def create_assignment():
    """Create a new assignment"""
    data = request.json
    
    # ✅ FIRST: Check if data exists
    if not data:
        return jsonify({"error": "No data provided"}), 400

    print(f"📥 RAW data received: {data}")
    print(f"🏢 Tenant ID: {g.tenant_id}")  # ✅ ADDED
    
    # ✅ Filter out invalid fields
    data = filter_assignment_data(data)
    print(f"📥 Creating assignment with filtered data: {data}")

    # ✅ PARSE DATE FIELDS - Handle both old and new format
    date_value = None
    start_date_value = None
    end_date_value = None
    
    if data.get('start_date'):
        try:
            start_date_value = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            date_value = start_date_value  # Also set date for backward compatibility
        except Exception as e:
            print(f"❌ Error parsing start_date: {e}")
            return jsonify({'error': 'Invalid start_date format'}), 400
    elif data.get('date'):
        try:
            date_value = datetime.strptime(data['date'], '%Y-%m-%d').date()
            start_date_value = date_value  # Also set start_date
        except Exception as e:
            print(f"❌ Error parsing date: {e}")
            return jsonify({'error': 'Invalid date format'}), 400
    else:
        return jsonify({'error': 'start_date or date is required'}), 400
    
    # ✅ ✅ ✅ VALIDATE: No past dates (AFTER parsing, not before)
    today = date.today()
    if date_value < today:
        error_msg = f'Cannot schedule in the past. Date {date_value} is before today ({today})'
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 400
    
    if data.get('end_date'):
        try:
            end_date_value = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            # Also validate end_date
            if end_date_value < today:
                return jsonify({
                    'error': f'End date {end_date_value} cannot be in the past'
                }), 400
        except Exception as e:
            print(f"❌ Error parsing end_date: {e}")
            return jsonify({'error': 'Invalid end_date format'}), 400
    else:
        end_date_value = start_date_value  # Default: end_date = start_date

    # ✅ Handle staff assignment
    staff_name = data.get("staff_name") or data.get("team_member")
    staff_id = None
    
    if staff_name:
        staff_name = staff_name.strip()
        # ✅ FILTER BY TENANT
        member = TeamMember.query.filter(
            TeamMember.tenant_id == g.tenant_id,
            TeamMember.name.ilike(staff_name)
        ).first()

        if not member:
            member = TeamMember(
                name=staff_name, 
                active=True,
                tenant_id=g.tenant_id  # ✅ ADDED
            )
            db.session.add(member)
            db.session.flush()  # Get ID before commit
        
        staff_id = member.id

    # ✅ GET CUSTOMER NAME
    customer_name = data.get('customer_name')
    customer_id = data.get('customer_id')
    if customer_id and not customer_name:
        # ✅ FILTER BY TENANT
        customer = Customer.query.filter_by(
            id=customer_id,
            tenant_id=g.tenant_id
        ).first()
        if customer:
            customer_name = customer.name

    # Parse times if provided (optional for meetings)
    start_time = None
    end_time = None
    if data.get('start_time'):
        try:
            start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        except ValueError:
            print(f"Invalid start_time format: {data['start_time']}")
    
    if data.get('end_time'):
        try:
            end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        except ValueError:
            print(f"Invalid end_time format: {data['end_time']}")

    # Calculate hours
    estimated_hours = data.get('estimated_hours')
    if isinstance(estimated_hours, str):
        try:
            estimated_hours = float(estimated_hours) if estimated_hours else None
        except ValueError:
            estimated_hours = None

    # ✅ Create assignment with date range support AND tenant_id
    try:
        assignment = Assignment(
            tenant_id=g.tenant_id,  # ✅ CRITICAL FIX - ADDED THIS
            type=data.get('type', 'task'),  # ✅ Changed default from 'job' to 'task'
            title=data.get('title', ''),
            date=date_value,
            start_date=start_date_value,
            end_date=end_date_value,
            customer_name=customer_name,
            staff_id=staff_id,
            team_member=staff_name,
            job_id=data.get('job_id'),
            customer_id=customer_id,
            start_time=start_time,
            end_time=end_time,
            estimated_hours=estimated_hours,
            notes=data.get('notes', ''),
            priority=data.get('priority', 'Medium'),
            status=data.get('status', 'Scheduled'),
            job_type=data.get('job_type'),
            created_by=g.user.get_full_name() if hasattr(g, 'user') else None  # ✅ ADDED
        )
        
        db.session.add(assignment)
        db.session.commit()

        print(f"✅ Assignment created: {assignment.id}")
        return jsonify(assignment.to_dict()), 201

    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creating assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# -----------------------------
# UPDATE assignment
# -----------------------------
@assignment_bp.route("/<assignment_id>", methods=["PUT"])
@require_tenant  # ✅ ADDED
def update_assignment(assignment_id):
    """Update an existing assignment"""
    # ✅ FILTER BY TENANT
    assignment = Assignment.query.filter_by(
        id=assignment_id,
        tenant_id=g.tenant_id
    ).first()
    
    if not assignment:
        print(f"❌ Assignment {assignment_id} not found for tenant {g.tenant_id}")
        return jsonify({"error": "Assignment not found"}), 404
    
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    print(f"📝 RAW update data received: {data}")
    
    # ✅ Filter out invalid fields
    data = filter_assignment_data(data)
    print(f"📝 Updating assignment {assignment_id} with filtered data: {data}")

    try:
        if 'type' in data:
            assignment.type = data['type']
        if 'title' in data:
            assignment.title = data['title']
        
        # ✅ Handle date updates for drag and drop
        if 'start_date' in data and data['start_date']:
            assignment.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            assignment.date = assignment.start_date  # Keep date in sync
            print(f"📅 Updated start_date to: {assignment.start_date}")
        elif 'date' in data and data['date']:
            assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            if not assignment.start_date:
                assignment.start_date = assignment.date
            print(f"📅 Updated date to: {assignment.date}")
        
        if 'end_date' in data and data['end_date']:
            assignment.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            print(f"📅 Updated end_date to: {assignment.end_date}")
        elif 'start_date' in data and not ('end_date' in data):
            # If only start_date provided, set end_date same as start_date
            assignment.end_date = assignment.start_date
            print(f"📅 Set end_date same as start_date: {assignment.end_date}")
        
        if 'start_time' in data:
            try:
                assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time() if data['start_time'] else None
            except ValueError:
                print(f"Invalid start_time: {data['start_time']}")
        
        if 'end_time' in data:
            try:
                assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time() if data['end_time'] else None
            except ValueError:
                print(f"Invalid end_time: {data['end_time']}")
        
        if 'estimated_hours' in data:
            estimated_hours = data['estimated_hours']
            try:
                assignment.estimated_hours = float(estimated_hours) if isinstance(estimated_hours, str) else estimated_hours
            except (ValueError, TypeError):
                print(f"Invalid estimated_hours: {estimated_hours}")
        
        if 'notes' in data:
            assignment.notes = data['notes']
        if 'priority' in data:
            assignment.priority = data['priority']
        if 'status' in data:
            assignment.status = data['status']
        if 'job_type' in data:
            assignment.job_type = data['job_type']
        if 'job_id' in data:
            assignment.job_id = data['job_id']
        
        # ✅ Update customer
        if 'customer_id' in data:
            assignment.customer_id = data['customer_id']
            if data['customer_id']:
                # ✅ FILTER BY TENANT
                customer = Customer.query.filter_by(
                    id=data['customer_id'],
                    tenant_id=g.tenant_id
                ).first()
                if customer:
                    assignment.customer_name = customer.name
        
        if 'customer_name' in data:
            assignment.customer_name = data['customer_name']
        
        # ✅ Update staff assignment
        if 'staff_name' in data or 'team_member' in data:
            staff_name = (data.get('staff_name') or data.get('team_member', '')).strip()
            if staff_name:
                # ✅ FILTER BY TENANT
                member = TeamMember.query.filter(
                    TeamMember.tenant_id == g.tenant_id,
                    TeamMember.name.ilike(staff_name)
                ).first()

                if not member:
                    member = TeamMember(
                        name=staff_name, 
                        active=True,
                        tenant_id=g.tenant_id  # ✅ ADDED
                    )
                    db.session.add(member)
                    db.session.flush()

                assignment.staff_id = member.id
                assignment.team_member = staff_name
        
        assignment.updated_at = datetime.utcnow()
        assignment.updated_by = g.user.get_full_name() if hasattr(g, 'user') else None  # ✅ ADDED
        
        db.session.commit()
        
        print(f"✅ Assignment {assignment_id} updated successfully")
        return jsonify(assignment.to_dict())
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error updating assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# -----------------------------
# DELETE assignment
# -----------------------------
@assignment_bp.route("/<assignment_id>", methods=["DELETE"])
@require_tenant  # ✅ ADDED
def delete_assignment(assignment_id):
    """Delete an assignment"""
    # ✅ FILTER BY TENANT
    assignment = Assignment.query.filter_by(
        id=assignment_id,
        tenant_id=g.tenant_id
    ).first()
    
    if not assignment:
        print(f"❌ Assignment {assignment_id} not found for tenant {g.tenant_id}")
        return jsonify({"error": "Assignment not found"}), 404
    
    try:
        print(f"🗑️ Deleting assignment {assignment_id}")
        db.session.delete(assignment)
        db.session.commit()
        print(f"✅ Assignment {assignment_id} deleted")
        
        # ✅ Always return JSON
        return jsonify({
            'message': 'Assignment deleted successfully',
            'id': assignment_id
        }), 200
    
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error deleting assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500