from flask import Blueprint, request, jsonify
from database import db
from models import Assignment, Customer, CustomerFormData, Fitter, Job, Quotation, QuotationItem
import json
from datetime import datetime

# Create blueprint
db_bp = Blueprint('database', __name__)

@db_bp.route('/customers/<string:customer_id>/sync-stage', methods=['POST'])
def sync_customer_stage(customer_id):
    """Sync customer stage with their primary job's stage"""
    customer = Customer.query.get_or_404(customer_id)
    old_stage = customer.stage
    
    # You can implement custom logic here if needed
    # For now, just return current stage
    
    return jsonify({
        'message': 'Customer stage synchronized',
        'old_stage': old_stage,
        'new_stage': customer.stage
    })

# Keep existing quotation routes unchanged
@db_bp.route('/quotations', methods=['GET', 'POST'])
def handle_quotations():
    if request.method == 'POST':
        data = request.json
        quotation = Quotation(
            customer_id=data['customer_id'],
            total=data['total'],
            notes=data.get('notes')
        )
        db.session.add(quotation)
        db.session.flush()

        for item in data.get('items', []):
            q_item = QuotationItem(
                quotation_id=quotation.id,
                item=item['item'],
                description=item.get('description'),
                color=item.get('color'),
                amount=item['amount']
            )
            db.session.add(q_item)

        db.session.commit()
        return jsonify({'id': quotation.id}), 201

    customer_id = request.args.get('customer_id', type=str)
    if customer_id:
        quotations = Quotation.query.filter_by(customer_id=customer_id).all()
    else:
        quotations = Quotation.query.all()
        
    return jsonify([
        {
            'id': q.id,
            'customer_id': q.customer_id,
            'customer_name': q.customer.name if q.customer else None,
            'total': q.total,
            'notes': q.notes,
            'created_at': q.created_at.isoformat() if q.created_at else None,
            'items': [
                {
                    'id': i.id,
                    'item': i.item,
                    'description': i.description,
                    'color': i.color,
                    'amount': i.amount
                } for i in q.items
            ]
        } for q in quotations
    ])

@db_bp.route('/quotations/<int:quotation_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_single_quotation(quotation_id):
    quotation = Quotation.query.get_or_404(quotation_id)

    if request.method == 'GET':
        return jsonify({
            'id': quotation.id,
            'customer_id': quotation.customer_id,
            'customer_name': quotation.customer.name if quotation.customer else None,
            'total': quotation.total,
            'notes': quotation.notes,
            'created_at': quotation.created_at.isoformat() if quotation.created_at else None,
            'updated_at': quotation.updated_at.isoformat() if quotation.updated_at else None,
            'items': [
                {
                    'id': i.id,
                    'item': i.item,
                    'description': i.description,
                    'color': i.color,
                    'amount': i.amount
                } for i in quotation.items
            ]
        })

    elif request.method == 'PUT':
        data = request.json
        quotation.total = data.get('total', quotation.total)
        quotation.notes = data.get('notes', quotation.notes)

        if 'items' in data:
            QuotationItem.query.filter_by(quotation_id=quotation.id).delete()
            for item in data['items']:
                q_item = QuotationItem(
                    quotation_id=quotation.id,
                    item=item['item'],
                    description=item.get('description'),
                    color=item.get('color'),
                    amount=item['amount']
                )
                db.session.add(q_item)

        db.session.commit()
        return jsonify({'message': 'Quotation updated successfully'})

    elif request.method == 'DELETE':
        db.session.delete(quotation)
        db.session.commit()
        return jsonify({'message': 'Quotation deleted successfully'})

# Jobs routes
@db_bp.route('/jobs', methods=['GET', 'POST'])
def handle_jobs():
    if request.method == 'POST':
        data = request.json
        
        # Create new job
        job = Job(
            customer_id=data['customer_id'],
            job_reference=data.get('job_reference'),
            job_name=data.get('job_name'),
            job_type=data.get('job_type', 'Kitchen'),
            stage=data.get('stage', 'Prospect'),  # Changed default to Prospect
            priority=data.get('priority', 'Medium'),
            quote_price=data.get('quote_price'),
            agreed_price=data.get('agreed_price'),
            sold_amount=data.get('sold_amount'),
            deposit1=data.get('deposit1'),
            deposit2=data.get('deposit2'),
            installation_address=data.get('installation_address'),
            notes=data.get('notes'),
            salesperson_name=data.get('salesperson_name'),
            assigned_team_name=data.get('assigned_team_name'),
            primary_fitter_name=data.get('primary_fitter_name')
        )
        
        # Parse dates
        if data.get('delivery_date'):
            job.delivery_date = datetime.strptime(data['delivery_date'], '%Y-%m-%d')
        if data.get('measure_date'):
            job.measure_date = datetime.strptime(data['measure_date'], '%Y-%m-%d')
        if data.get('completion_date'):
            job.completion_date = datetime.strptime(data['completion_date'], '%Y-%m-%d')
        if data.get('deposit_due_date'):
            job.deposit_due_date = datetime.strptime(data['deposit_due_date'], '%Y-%m-%d')
        
        db.session.add(job)
        db.session.commit()
        
        return jsonify({
            'id': job.id,
            'message': 'Job created successfully'
        }), 201
    
    # GET all jobs
    customer_id = request.args.get('customer_id', type=str)
    if customer_id:
        jobs = Job.query.filter_by(customer_id=customer_id).order_by(Job.created_at.desc()).all()
    else:
        jobs = Job.query.order_by(Job.created_at.desc()).all()
        
    return jsonify([
        {
            'id': j.id,
            'customer_id': j.customer_id,
            'job_reference': j.job_reference,
            'job_name': j.job_name,
            'job_type': j.job_type,
            'stage': j.stage,
            'priority': j.priority,
            'quote_price': float(j.quote_price) if j.quote_price else None,
            'agreed_price': float(j.agreed_price) if j.agreed_price else None,
            'sold_amount': float(j.sold_amount) if j.sold_amount else None,
            'deposit1': float(j.deposit1) if j.deposit1 else None,
            'deposit2': float(j.deposit2) if j.deposit2 else None,
            'delivery_date': j.delivery_date.isoformat() if j.delivery_date else None,
            'measure_date': j.measure_date.isoformat() if j.measure_date else None,
            'completion_date': j.completion_date.isoformat() if j.completion_date else None,
            'installation_address': j.installation_address,
            'notes': j.notes,
            'salesperson_name': j.salesperson_name,
            'assigned_team_name': j.assigned_team_name,
            'primary_fitter_name': j.primary_fitter_name,
            'created_at': j.created_at.isoformat() if j.created_at else None,
            'updated_at': j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in jobs
    ])

@db_bp.route('/jobs/<string:job_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_single_job(job_id):
    job = Job.query.get_or_404(job_id)
    
    if request.method == 'GET':
        return jsonify({
            'id': job.id,
            'customer_id': job.customer_id,
            'job_reference': job.job_reference,
            'job_name': job.job_name,
            'job_type': job.job_type,
            'stage': job.stage,
            'priority': job.priority,
            'quote_price': float(job.quote_price) if job.quote_price else None,
            'agreed_price': float(job.agreed_price) if job.agreed_price else None,
            'sold_amount': float(job.sold_amount) if job.sold_amount else None,
            'deposit1': float(job.deposit1) if job.deposit1 else None,
            'deposit2': float(job.deposit2) if job.deposit2 else None,
            'delivery_date': job.delivery_date.isoformat() if job.delivery_date else None,
            'measure_date': job.measure_date.isoformat() if job.measure_date else None,
            'completion_date': job.completion_date.isoformat() if job.completion_date else None,
            'deposit_due_date': job.deposit_due_date.isoformat() if job.deposit_due_date else None,
            'installation_address': job.installation_address,
            'notes': job.notes,
            'salesperson_name': job.salesperson_name,
            'assigned_team_name': job.assigned_team_name,
            'primary_fitter_name': job.primary_fitter_name,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'updated_at': job.updated_at.isoformat() if job.updated_at else None,
        })
    
    elif request.method == 'PUT':
        data = request.json
        
        # Update job fields
        job.job_reference = data.get('job_reference', job.job_reference)
        job.job_name = data.get('job_name', job.job_name)
        job.job_type = data.get('job_type', job.job_type)
        job.stage = data.get('stage', job.stage)
        job.priority = data.get('priority', job.priority)
        job.quote_price = data.get('quote_price', job.quote_price)
        job.agreed_price = data.get('agreed_price', job.agreed_price)
        job.sold_amount = data.get('sold_amount', job.sold_amount)
        job.deposit1 = data.get('deposit1', job.deposit1)
        job.deposit2 = data.get('deposit2', job.deposit2)
        job.installation_address = data.get('installation_address', job.installation_address)
        job.notes = data.get('notes', job.notes)
        job.salesperson_name = data.get('salesperson_name', job.salesperson_name)
        job.assigned_team_name = data.get('assigned_team_name', job.assigned_team_name)
        job.primary_fitter_name = data.get('primary_fitter_name', job.primary_fitter_name)
        
        # Update dates
        if 'delivery_date' in data and data['delivery_date']:
            job.delivery_date = datetime.strptime(data['delivery_date'], '%Y-%m-%d')
        if 'measure_date' in data and data['measure_date']:
            job.measure_date = datetime.strptime(data['measure_date'], '%Y-%m-%d')
        if 'completion_date' in data and data['completion_date']:
            job.completion_date = datetime.strptime(data['completion_date'], '%Y-%m-%d')
        if 'deposit_due_date' in data and data['deposit_due_date']:
            job.deposit_due_date = datetime.strptime(data['deposit_due_date'], '%Y-%m-%d')
        
        db.session.commit()
        
        return jsonify({'message': 'Job updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(job)
        db.session.commit()
        
        return jsonify({'message': 'Job deleted successfully'})

@db_bp.route('/pipeline', methods=['GET'])
def get_pipeline_data():
    """
    Specialized endpoint that returns combined customer/job data optimized for the pipeline view
    """
    customers = Customer.query.all()
    jobs = Job.query.all()
    
    # Create a map for quick job lookup
    jobs_by_customer = {}
    for job in jobs:
        if job.customer_id not in jobs_by_customer:
            jobs_by_customer[job.customer_id] = []
        jobs_by_customer[job.customer_id].append(job)
    
    pipeline_items = []
    
    for customer in customers:
        customer_jobs = jobs_by_customer.get(customer.id, [])
        
        if not customer_jobs:
            # Customer without jobs
            pipeline_items.append({
                'id': f'customer-{customer.id}',
                'type': 'customer',
                'customer': {
                    'id': customer.id,
                    'name': customer.name,
                    'company_name': customer.company_name,
                    'address': customer.address,
                    'postcode': customer.postcode,
                    'phone': customer.phone,
                    'email': customer.email,
                    'industry': customer.industry,
                    'company_size': customer.company_size,
                    'contact_made': customer.contact_made,
                    'preferred_contact_method': customer.preferred_contact_method,
                    'marketing_opt_in': customer.marketing_opt_in,
                    'stage': customer.stage,
                    'notes': customer.notes,
                    'salesperson': customer.salesperson,
                    'status': customer.status,
                    'created_at': customer.created_at.isoformat() if customer.created_at else None,
                }
            })
        else:
            # Customer with jobs - create item for each job
            for job in customer_jobs:
                deposit1_paid = False
                deposit2_paid = False
                
                pipeline_items.append({
                    'id': f'job-{job.id}',
                    'type': 'job',
                    'customer': {
                        'id': customer.id,
                        'name': customer.name,
                        'company_name': customer.company_name,
                        'address': customer.address,
                        'postcode': customer.postcode,
                        'phone': customer.phone,
                        'email': customer.email,
                        'industry': customer.industry,
                        'company_size': customer.company_size,
                        'contact_made': customer.contact_made,
                        'preferred_contact_method': customer.preferred_contact_method,
                        'marketing_opt_in': customer.marketing_opt_in,
                        'stage': customer.stage,
                        'notes': customer.notes,
                        'salesperson': customer.salesperson,
                        'status': customer.status,
                        'created_at': customer.created_at.isoformat() if customer.created_at else None,
                    },
                    'job': {
                        'id': job.id,
                        'customer_id': job.customer_id,
                        'job_reference': job.job_reference,
                        'job_name': job.job_name,
                        'job_type': job.job_type,
                        'stage': job.stage,
                        'priority': job.priority,
                        'quote_price': float(job.quote_price) if job.quote_price else None,
                        'agreed_price': float(job.agreed_price) if job.agreed_price else None,
                        'sold_amount': float(job.sold_amount) if job.sold_amount else None,
                        'deposit1': float(job.deposit1) if job.deposit1 else None,
                        'deposit2': float(job.deposit2) if job.deposit2 else None,
                        'deposit1_paid': deposit1_paid,
                        'deposit2_paid': deposit2_paid,
                        'delivery_date': job.delivery_date.isoformat() if job.delivery_date else None,
                        'measure_date': job.measure_date.isoformat() if job.measure_date else None,
                        'completion_date': job.completion_date.isoformat() if job.completion_date else None,
                        'installation_address': job.installation_address,
                        'notes': job.notes,
                        'salesperson_name': job.salesperson_name,
                        'assigned_team_name': job.assigned_team_name,
                        'primary_fitter_name': job.primary_fitter_name,
                        'created_at': job.created_at.isoformat() if job.created_at else None,
                        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
                    }
                })
    
    return jsonify(pipeline_items)

# Assignment routes (keep existing code)
@db_bp.route('/assignments', methods=['GET', 'POST'])
def handle_assignments():
    if request.method == 'POST':
        data = request.json
        
        try:
            start_time = None
            end_time = None
            if data.get('start_time'):
                start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            if data.get('end_time'):
                end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            
            estimated_hours = None
            if start_time and end_time:
                start_datetime = datetime.combine(datetime.today(), start_time)
                end_datetime = datetime.combine(datetime.today(), end_time)
                duration = end_datetime - start_datetime
                estimated_hours = duration.total_seconds() / 3600
                
            assignment = Assignment(
                type=data.get('type', 'job'),
                title=data.get('title', ''),
                date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
                staff_id=int(data['staff_id']),
                job_id=data.get('job_id'),
                customer_id=data.get('customer_id'),
                start_time=start_time,
                end_time=end_time,
                estimated_hours=estimated_hours,
                notes=data.get('notes'),
                priority=data.get('priority', 'Medium'),
                status=data.get('status', 'Scheduled'),
                created_by=data.get('created_by', 'system')
            )
            
            if not assignment.title:
                if assignment.type == 'job':
                    if assignment.job:
                        assignment.title = f"{assignment.job.job_reference} - {assignment.job.customer.name}"
                    elif assignment.customer:
                        assignment.title = f"Job - {assignment.customer.name}"
                    else:
                        assignment.title = "Job Assignment"
                elif assignment.type == 'off':
                    assignment.title = "Day Off"
                elif assignment.type == 'delivery':
                    assignment.title = "Deliveries"
                elif assignment.type == 'note':
                    assignment.title = assignment.notes or "Note"
            
            db.session.add(assignment)
            db.session.commit()
            return jsonify({
                'id': assignment.id,
                'message': 'Assignment created successfully',
                'assignment': assignment.to_dict()
            }), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
            
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        staff_id = request.args.get('staff_id')
        query = Assignment.query
        
        if start_date:
            query = query.filter(Assignment.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            query = query.filter(Assignment.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        if staff_id:
            query = query.filter(Assignment.staff_id == int(staff_id))
            
        assignments = query.order_by(Assignment.date.desc(), Assignment.start_time).all()
        return jsonify([assignment.to_dict() for assignment in assignments])
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@db_bp.route('/assignments/<string:assignment_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_single_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    
    if request.method == 'GET':
        return jsonify(assignment.to_dict())
        
    elif request.method == 'PUT':
        try:
            data = request.json
            assignment.type = data.get('type', assignment.type)
            assignment.title = data.get('title', assignment.title)
            assignment.staff_id = int(data.get('staff_id', assignment.staff_id))
            assignment.job_id = data.get('job_id', assignment.job_id)
            assignment.customer_id = data.get('customer_id', assignment.customer_id)
            assignment.notes = data.get('notes', assignment.notes)
            assignment.priority = data.get('priority', assignment.priority)
            assignment.status = data.get('status', assignment.status)
            assignment.updated_by = data.get('updated_by', 'system')
            
            if 'date' in data:
                assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            if 'start_time' in data and data['start_time']:
                assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            if 'end_time' in data and data['end_time']:
                assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                
            if assignment.start_time and assignment.end_time:
                start_datetime = datetime.combine(datetime.today(), assignment.start_time)
                end_datetime = datetime.combine(datetime.today(), assignment.end_time)
                duration = end_datetime - start_datetime
                assignment.estimated_hours = duration.total_seconds() / 3600
            
            db.session.commit()
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': assignment.to_dict()
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
    
    elif request.method == 'DELETE':
        try:
            db.session.delete(assignment)
            db.session.commit()
            return jsonify({'message': 'Assignment deleted successfully'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

@db_bp.route('/fitters', methods=['GET'])
def get_fitters():
    """Get all active fitters for team member dropdown"""
    try:
        fitters = Fitter.query.filter_by(active=True).all()
        return jsonify([
            {
                'id': f.id,
                'name': f.name,
                'role': f.team.name if f.team else 'Unassigned',
                'team_id': f.team_id
            }
            for f in fitters
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@db_bp.route('/jobs/available', methods=['GET'])
def get_available_jobs():
    """Get jobs that are ready for scheduling"""
    try:
        schedulable_stages = ['Accepted', 'Production', 'Delivery', 'Installation']
        jobs = Job.query.filter(Job.stage.in_(schedulable_stages)).all()
        
        return jsonify([
            {
                'id': j.id,
                'job_reference': j.job_reference,
                'customer_name': j.customer.name,
                'customer_id': j.customer_id,
                'job_type': j.job_type,
                'stage': j.stage,
                'installation_address': j.installation_address or j.customer.address,
                'priority': j.priority
            }
            for j in jobs
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    
@db_bp.route('/customers', methods=['GET', 'POST'])
def handle_customers():
    if request.method == 'POST':
        data = request.json
        
        # Create new customer with universal fields
        customer = Customer(
            name=data.get('name', ''),
            company_name=data.get('company_name'),
            address=data.get('address', ''),
            postcode=data.get('postcode', ''),
            phone=data.get('phone', ''),
            email=data.get('email', ''),
            industry=data.get('industry'),
            company_size=data.get('company_size'),
            contact_made=data.get('contact_made', 'Unknown'),
            preferred_contact_method=data.get('preferred_contact_method'),
            marketing_opt_in=data.get('marketing_opt_in', False),
            notes=data.get('notes', ''),
            stage=data.get('stage', 'Prospect'),  # Default to Prospect
            created_by=data.get('created_by', 'System'),
            status=data.get('status', 'active'),
            salesperson=data.get('salesperson'),
        )
        
        db.session.add(customer)
        db.session.commit()
        
        return jsonify({
            'id': customer.id,
            'message': 'Customer created successfully'
        }), 201
    
    # GET all customers
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    return jsonify([
        {
            'id': c.id,
            'name': c.name,
            'company_name': c.company_name,
            'address': c.address,
            'postcode': c.postcode,
            'phone': c.phone,
            'email': c.email,
            'industry': c.industry,
            'company_size': c.company_size,
            'contact_made': c.contact_made,
            'preferred_contact_method': c.preferred_contact_method,
            'marketing_opt_in': c.marketing_opt_in,
            'status': c.status,
            'stage': c.stage,
            'notes': c.notes,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'created_by': c.created_by,
            'salesperson': c.salesperson,
        }
        for c in customers
    ])

@db_bp.route('/customers/<string:customer_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_single_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'GET':
        # Fetch form submissions
        form_entries = CustomerFormData.query.filter_by(customer_id=customer.id).order_by(CustomerFormData.submitted_at.desc()).all()
        
        form_submissions = []
        for f in form_entries:
            try:
                parsed = json.loads(f.form_data)
            except Exception:
                parsed = {"raw": f.form_data}
            
            form_submissions.append({
                "id": f.id,
                "token_used": f.token_used,
                "submitted_at": f.submitted_at.isoformat() if f.submitted_at else None,
                "form_data": parsed,
                "source": "web_form"
            })

        return jsonify({
            'id': customer.id,
            'name': customer.name,
            'company_name': customer.company_name,
            'address': customer.address,
            'postcode': customer.postcode,
            'phone': customer.phone,
            'email': customer.email,
            'industry': customer.industry,
            'company_size': customer.company_size,
            'contact_made': customer.contact_made,
            'preferred_contact_method': customer.preferred_contact_method,
            'marketing_opt_in': customer.marketing_opt_in,
            'status': customer.status,
            'stage': customer.stage,
            'notes': customer.notes,
            'created_at': customer.created_at.isoformat() if customer.created_at else None,
            'updated_at': customer.updated_at.isoformat() if customer.updated_at else None,
            'created_by': customer.created_by,
            'updated_by': customer.updated_by,
            'salesperson': customer.salesperson,
            'form_submissions': form_submissions
        })
    
    elif request.method == 'PUT':
        data = request.json
        customer.name = data.get('name', customer.name)
        customer.company_name = data.get('company_name', customer.company_name)
        customer.address = data.get('address', customer.address)
        customer.postcode = data.get('postcode', customer.postcode)
        customer.phone = data.get('phone', customer.phone)
        customer.email = data.get('email', customer.email)
        customer.industry = data.get('industry', customer.industry)
        customer.company_size = data.get('company_size', customer.company_size)
        customer.contact_made = data.get('contact_made', customer.contact_made)
        customer.preferred_contact_method = data.get('preferred_contact_method', customer.preferred_contact_method)
        customer.marketing_opt_in = data.get('marketing_opt_in', customer.marketing_opt_in)
        customer.status = data.get('status', customer.status)
        customer.stage = data.get('stage', customer.stage)
        customer.notes = data.get('notes', customer.notes)
        customer.updated_by = data.get('updated_by', 'System')
        customer.salesperson = data.get('salesperson', customer.salesperson)
        
        db.session.commit()
        return jsonify({'message': 'Customer updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': 'Customer deleted successfully'})