# routes/db_routes.py
from flask import Blueprint, request, jsonify, g
from database import db
from models import (
    Customer, Opportunity, Activity, OpportunityNote, OpportunityDocument,
    Proposal, ProposalItem, Product, ProductCategory,
    Invoice, InvoiceLineItem, Payment, Team, TeamMember, 
    Salesperson, FormSubmission, CustomerFormData, AuditLog, Assignment
)
from tenant_middleware import require_tenant  # ADD THIS IMPORT
import json
from datetime import datetime

# Create blueprint
db_bp = Blueprint('database', __name__)

# ----------------------------------
# Opportunity Routes
# ----------------------------------

@db_bp.route('/opportunities', methods=['GET', 'POST'])
@require_tenant  # ADD THIS
def handle_opportunities():
    if request.method == 'POST':
        data = request.json
        
        opportunity = Opportunity(
            tenant_id=g.tenant_id,  # ADD THIS - CRITICAL!
            customer_id=data['customer_id'],
            opportunity_name=data.get('opportunity_name'),
            opportunity_reference=data.get('opportunity_reference'),
            stage=data.get('stage', 'Prospect'),
            priority=data.get('priority', 'Medium'),
            estimated_value=data.get('estimated_value'),
            probability=data.get('probability'),
            expected_close_date=datetime.strptime(data['expected_close_date'], '%Y-%m-%d') if data.get('expected_close_date') else None,
            salesperson_name=data.get('salesperson_name'),
            notes=data.get('notes'),
        )
        
        db.session.add(opportunity)
        db.session.commit()
        
        return jsonify({
            'id': opportunity.id,
            'message': 'Opportunity created successfully'
        }), 201
    
    # GET opportunities (filtered by tenant)
    customer_id = request.args.get('customer_id')
    query = Opportunity.query.filter_by(tenant_id=g.tenant_id)  # ADD TENANT FILTER
    
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    opportunities = query.order_by(Opportunity.created_at.desc()).all()
    
    return jsonify([
        {
            'id': o.id,
            'customer_id': o.customer_id,
            'customer_name': o.customer.name if o.customer else None,
            'opportunity_name': o.opportunity_name,
            'opportunity_reference': o.opportunity_reference,
            'stage': o.stage,
            'priority': o.priority,
            'estimated_value': float(o.estimated_value) if o.estimated_value else None,
            'probability': o.probability,
            'expected_close_date': o.expected_close_date.isoformat() if o.expected_close_date else None,
            'actual_close_date': o.actual_close_date.isoformat() if o.actual_close_date else None,
            'salesperson_name': o.salesperson_name,
            'notes': o.notes,
            'created_at': o.created_at.isoformat() if o.created_at else None,
            'updated_at': o.updated_at.isoformat() if o.updated_at else None
        }
        for o in opportunities
    ])

@db_bp.route('/opportunities/<string:opportunity_id>', methods=['GET', 'PUT', 'DELETE'])
@require_tenant  # ADD THIS
def handle_single_opportunity(opportunity_id):
    # ADD TENANT FILTER - CRITICAL FOR SECURITY!
    opportunity = Opportunity.query.filter_by(
        id=opportunity_id,
        tenant_id=g.tenant_id
    ).first()
    
    if not opportunity:
        return jsonify({'error': 'Opportunity not found'}), 404
    
    if request.method == 'GET':
        return jsonify({
            'id': opportunity.id,
            'customer_id': opportunity.customer_id,
            'customer_name': opportunity.customer.name if opportunity.customer else None,
            'opportunity_name': opportunity.opportunity_name,
            'opportunity_reference': opportunity.opportunity_reference,
            'stage': opportunity.stage,
            'priority': opportunity.priority,
            'estimated_value': float(opportunity.estimated_value) if opportunity.estimated_value else None,
            'probability': opportunity.probability,
            'expected_close_date': opportunity.expected_close_date.isoformat() if opportunity.expected_close_date else None,
            'actual_close_date': opportunity.actual_close_date.isoformat() if opportunity.actual_close_date else None,
            'salesperson_name': opportunity.salesperson_name,
            'notes': opportunity.notes,
            'created_at': opportunity.created_at.isoformat() if opportunity.created_at else None,
            'updated_at': opportunity.updated_at.isoformat() if opportunity.updated_at else None,
        })
    
    elif request.method == 'PUT':
        data = request.json
        opportunity.opportunity_name = data.get('opportunity_name', opportunity.opportunity_name)
        opportunity.stage = data.get('stage', opportunity.stage)
        opportunity.priority = data.get('priority', opportunity.priority)
        opportunity.estimated_value = data.get('estimated_value', opportunity.estimated_value)
        opportunity.probability = data.get('probability', opportunity.probability)
        
        if data.get('expected_close_date'):
            opportunity.expected_close_date = datetime.strptime(data['expected_close_date'], '%Y-%m-%d')
        if data.get('actual_close_date'):
            opportunity.actual_close_date = datetime.strptime(data['actual_close_date'], '%Y-%m-%d')
        
        opportunity.salesperson_name = data.get('salesperson_name', opportunity.salesperson_name)
        opportunity.notes = data.get('notes', opportunity.notes)
        
        db.session.commit()
        return jsonify({'message': 'Opportunity updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(opportunity)
        db.session.commit()
        return jsonify({'message': 'Opportunity deleted successfully'})

# ----------------------------------
# Proposal Routes
# ----------------------------------

@db_bp.route('/proposals', methods=['GET', 'POST'])
@require_tenant  # ADD THIS
def handle_proposals():
    if request.method == 'POST':
        data = request.json
        proposal = Proposal(
            tenant_id=g.tenant_id,  # ADD THIS
            customer_id=data['customer_id'],
            reference_number=data.get('reference_number'),
            title=data.get('title'),
            total=data['total'],
            status=data.get('status', 'Draft'),
            valid_until=datetime.strptime(data['valid_until'], '%Y-%m-%d').date() if data.get('valid_until') else None,
            notes=data.get('notes')
        )
        db.session.add(proposal)
        db.session.flush()

        for item in data.get('items', []):
            p_item = ProposalItem(
                tenant_id=g.tenant_id,  # ADD THIS
                proposal_id=proposal.id,
                product_id=item.get('product_id'),
                description=item['description'],
                quantity=item.get('quantity', 1),
                unit_price=item['unit_price']
            )
            p_item.calculate_line_total()
            db.session.add(p_item)

        db.session.commit()
        return jsonify({'id': proposal.id, 'message': 'Proposal created successfully'}), 201

    customer_id = request.args.get('customer_id', type=str)
    query = Proposal.query.filter_by(tenant_id=g.tenant_id)  # ADD TENANT FILTER
    
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    proposals = query.all()
        
    return jsonify([
        {
            'id': p.id,
            'customer_id': p.customer_id,
            'customer_name': p.customer.name if p.customer else None,
            'reference_number': p.reference_number,
            'title': p.title,
            'total': float(p.total) if p.total else None,
            'status': p.status,
            'valid_until': p.valid_until.isoformat() if p.valid_until else None,
            'notes': p.notes,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'items': [
                {
                    'id': i.id,
                    'description': i.description,
                    'quantity': i.quantity,
                    'unit_price': float(i.unit_price) if i.unit_price else None,
                    'line_total': float(i.line_total) if i.line_total else None
                } for i in p.items
            ]
        } for p in proposals
    ])

# ----------------------------------
# Invoice Routes
# ----------------------------------

@db_bp.route('/invoices', methods=['GET', 'POST'])
@require_tenant  # ADD THIS
def handle_invoices():
    if request.method == 'POST':
        data = request.json
        
        invoice = Invoice(
            tenant_id=g.tenant_id,  # ADD THIS
            opportunity_id=data['opportunity_id'],
            invoice_number=data['invoice_number'],
            status=data.get('status', 'Draft'),
            due_date=datetime.strptime(data['due_date'], '%Y-%m-%d').date() if data.get('due_date') else None,
        )
        
        db.session.add(invoice)
        db.session.flush()
        
        # Add line items
        for item in data.get('line_items', []):
            line_item = InvoiceLineItem(
                tenant_id=g.tenant_id,  # ADD THIS
                invoice_id=invoice.id,
                description=item['description'],
                quantity=item.get('quantity', 1),
                unit_price=item['unit_price'],
                tax_rate=item.get('tax_rate', 0)
            )
            db.session.add(line_item)
        
        db.session.commit()
        
        return jsonify({
            'id': invoice.id,
            'message': 'Invoice created successfully'
        }), 201
    
    # GET invoices (filtered by tenant)
    opportunity_id = request.args.get('opportunity_id')
    query = Invoice.query.filter_by(tenant_id=g.tenant_id)  # ADD TENANT FILTER
    
    if opportunity_id:
        query = query.filter_by(opportunity_id=opportunity_id)
    
    invoices = query.order_by(Invoice.created_at.desc()).all()
    
    return jsonify([
        {
            'id': i.id,
            'opportunity_id': i.opportunity_id,
            'invoice_number': i.invoice_number,
            'status': i.status,
            'due_date': i.due_date.isoformat() if i.due_date else None,
            'paid_date': i.paid_date.isoformat() if i.paid_date else None,
            'amount_due': float(i.amount_due),
            'amount_paid': float(i.amount_paid),
            'balance': float(i.balance),
        }
        for i in invoices
    ])

# ----------------------------------
# Team Routes
# ----------------------------------

@db_bp.route('/teams', methods=['GET', 'POST'])
@require_tenant  # ADD THIS
def handle_teams():
    if request.method == 'POST':
        data = request.json
        team = Team(
            tenant_id=g.tenant_id,  # ADD THIS
            name=data['name'],
            specialty=data.get('specialty'),
            active=data.get('active', True)
        )
        db.session.add(team)
        db.session.commit()
        return jsonify({
            'id': team.id,
            'message': 'Team created successfully'
        }), 201
    
    teams = Team.query.filter_by(tenant_id=g.tenant_id, active=True).all()  # ADD TENANT FILTER
    return jsonify([
        {
            'id': t.id,
            'name': t.name,
            'specialty': t.specialty,
            'active': t.active,
            'created_at': t.created_at.isoformat() if t.created_at else None
        }
        for t in teams
    ])

@db_bp.route('/salespeople', methods=['GET', 'POST'])
@require_tenant  # ADD THIS
def handle_salespeople():
    if request.method == 'POST':
        data = request.json
        salesperson = Salesperson(
            tenant_id=g.tenant_id,  # ADD THIS
            name=data['name'],
            email=data.get('email'),
            phone=data.get('phone'),
            active=data.get('active', True)
        )
        db.session.add(salesperson)
        db.session.commit()
        return jsonify({
            'id': salesperson.id,
            'message': 'Salesperson created successfully'
        }), 201
    
    salespeople = Salesperson.query.filter_by(tenant_id=g.tenant_id, active=True).all()  # ADD TENANT FILTER
    return jsonify([
        {
            'id': s.id,
            'name': s.name,
            'email': s.email,
            'phone': s.phone,
            'active': s.active,
            'created_at': s.created_at.isoformat() if s.created_at else None
        }
        for s in salespeople
    ])

# ----------------------------------
# Job Routes (mapped to Opportunities)
# ----------------------------------

@db_bp.route('/jobs', methods=['GET', 'POST'])
@require_tenant  # ADD THIS
def handle_jobs():
    """Jobs are mapped to Opportunities in the backend"""
    if request.method == 'POST':
        data = request.json
        
        # Validate required fields
        if not data.get('customer_id'):
            return jsonify({'error': 'customer_id is required'}), 400
        if not data.get('job_name'):
            return jsonify({'error': 'job_name is required'}), 400
        
        # Create new opportunity (job)
        opportunity = Opportunity(
            tenant_id=g.tenant_id,  # ADD THIS
            customer_id=data['customer_id'],
            opportunity_name=data['job_name'],
            opportunity_reference=data.get('job_reference'),
            stage=data.get('stage', 'Prospect'),
            priority=data.get('priority', 'Medium'),
            estimated_value=data.get('estimated_value'),
            probability=data.get('probability'),
            expected_close_date=datetime.strptime(data['due_date'], '%Y-%m-%d') if data.get('due_date') else None,
            actual_close_date=datetime.strptime(data['completion_date'], '%Y-%m-%d') if data.get('completion_date') else None,
            salesperson_name=data.get('salesperson'),
            notes=data.get('notes'),
        )
        
        db.session.add(opportunity)
        db.session.commit()
        
        # Return in job format
        return jsonify({
            'id': opportunity.id,
            'customer_id': opportunity.customer_id,
            'job_name': opportunity.opportunity_name,
            'job_reference': opportunity.opportunity_reference,
            'job_type': data.get('job_type', 'General'),
            'stage': opportunity.stage,
            'priority': opportunity.priority,
            'estimated_value': float(opportunity.estimated_value) if opportunity.estimated_value else None,
            'agreed_value': float(opportunity.estimated_value) if opportunity.estimated_value else None,
            'deposit_amount': data.get('deposit_amount'),
            'start_date': data.get('start_date'),
            'due_date': opportunity.expected_close_date.isoformat() if opportunity.expected_close_date else None,
            'completion_date': opportunity.actual_close_date.isoformat() if opportunity.actual_close_date else None,
            'deposit_due_date': data.get('deposit_due_date'),
            'salesperson': opportunity.salesperson_name,
            'assigned_team': data.get('assigned_team'),
            'primary_contact': data.get('primary_contact'),
            'service_location': data.get('service_location'),
            'requirements': data.get('requirements'),
            'tags': data.get('tags'),
            'notes': opportunity.notes,
            'quote_id': data.get('quote_id'),
            'created_at': opportunity.created_at.isoformat() if opportunity.created_at else None,
            'updated_at': opportunity.updated_at.isoformat() if opportunity.updated_at else None,
        }), 201
    
    # GET jobs (mapped to opportunities, filtered by tenant)
    customer_id = request.args.get('customer_id')
    query = Opportunity.query.filter_by(tenant_id=g.tenant_id)  # ADD TENANT FILTER
    
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    opportunities = query.order_by(Opportunity.created_at.desc()).all()
    
    return jsonify([
        {
            'id': o.id,
            'customer_id': o.customer_id,
            'customer_name': o.customer.name if o.customer else None,
            'job_name': o.opportunity_name,
            'job_reference': o.opportunity_reference,
            'job_type': 'General',
            'stage': o.stage,
            'priority': o.priority,
            'estimated_value': float(o.estimated_value) if o.estimated_value else None,
            'agreed_value': float(o.estimated_value) if o.estimated_value else None,
            'probability': o.probability,
            'due_date': o.expected_close_date.isoformat() if o.expected_close_date else None,
            'completion_date': o.actual_close_date.isoformat() if o.actual_close_date else None,
            'salesperson': o.salesperson_name,
            'notes': o.notes,
            'created_at': o.created_at.isoformat() if o.created_at else None,
            'updated_at': o.updated_at.isoformat() if o.updated_at else None
        }
        for o in opportunities
    ])


@db_bp.route('/jobs/<string:job_id>', methods=['GET', 'PUT', 'DELETE'])
@require_tenant  # ADD THIS
def handle_single_job(job_id):
    """Single job endpoint (mapped to opportunity)"""
    # ADD TENANT FILTER
    opportunity = Opportunity.query.filter_by(
        id=job_id,
        tenant_id=g.tenant_id
    ).first()
    
    if not opportunity:
        return jsonify({'error': 'Job not found'}), 404
    
    if request.method == 'GET':
        job_data = {
            'id': opportunity.id,
            'customer_id': opportunity.customer_id,
            'job_name': opportunity.opportunity_name,
            'job_reference': opportunity.opportunity_reference,
            'job_type': 'General',
            'stage': opportunity.stage,
            'priority': opportunity.priority,
            'estimated_value': float(opportunity.estimated_value) if opportunity.estimated_value else None,
            'agreed_value': float(opportunity.estimated_value) if opportunity.estimated_value else None,
            'probability': opportunity.probability,
            'due_date': opportunity.expected_close_date.isoformat() if opportunity.expected_close_date else None,
            'completion_date': opportunity.actual_close_date.isoformat() if opportunity.actual_close_date else None,
            'salesperson': opportunity.salesperson_name,
            'notes': opportunity.notes,
            'created_at': opportunity.created_at.isoformat() if opportunity.created_at else None,
            'updated_at': opportunity.updated_at.isoformat() if opportunity.updated_at else None,
        }
        
        # Add customer information
        if opportunity.customer:
            job_data['customer'] = {
                'id': opportunity.customer.id,
                'name': opportunity.customer.name,
                'company_name': opportunity.customer.company_name,
                'email': opportunity.customer.email,
                'phone': opportunity.customer.phone,
                'address': opportunity.customer.address,
            }
        
        return jsonify(job_data)
    
    elif request.method == 'PUT':
        data = request.json
        
        # Update fields
        if 'job_name' in data:
            opportunity.opportunity_name = data['job_name']
        if 'job_reference' in data:
            opportunity.opportunity_reference = data['job_reference']
        if 'stage' in data:
            opportunity.stage = data['stage']
        if 'priority' in data:
            opportunity.priority = data['priority']
        if 'estimated_value' in data:
            opportunity.estimated_value = data['estimated_value']
        if 'probability' in data:
            opportunity.probability = data['probability']
        
        # Update dates
        if 'due_date' in data and data['due_date']:
            opportunity.expected_close_date = datetime.strptime(data['due_date'], '%Y-%m-%d')
        if 'completion_date' in data and data['completion_date']:
            opportunity.actual_close_date = datetime.strptime(data['completion_date'], '%Y-%m-%d')
        
        # Update other fields
        if 'salesperson' in data:
            opportunity.salesperson_name = data['salesperson']
        if 'notes' in data:
            opportunity.notes = data['notes']
        
        db.session.commit()
        
        return jsonify({
            'id': opportunity.id,
            'customer_id': opportunity.customer_id,
            'job_name': opportunity.opportunity_name,
            'job_reference': opportunity.opportunity_reference,
            'stage': opportunity.stage,
            'priority': opportunity.priority,
            'estimated_value': float(opportunity.estimated_value) if opportunity.estimated_value else None,
            'salesperson': opportunity.salesperson_name,
            'notes': opportunity.notes,
            'created_at': opportunity.created_at.isoformat() if opportunity.created_at else None,
            'updated_at': opportunity.updated_at.isoformat() if opportunity.updated_at else None,
        })
    
    elif request.method == 'DELETE':
        db.session.delete(opportunity)
        db.session.commit()
        return jsonify({'message': 'Job deleted successfully'})

# ----------------------------------
# Pipeline View (Combined Data)
# ----------------------------------

@db_bp.route('/pipeline', methods=['GET'])
@require_tenant  # ADD THIS
def get_pipeline_data():
    """
    Returns combined customer/opportunity data for pipeline view
    """
    # FILTER BY TENANT
    customers = Customer.query.filter_by(tenant_id=g.tenant_id).all()
    opportunities = Opportunity.query.filter_by(tenant_id=g.tenant_id).all()
    
    # Map opportunities by customer
    opps_by_customer = {}
    for opp in opportunities:
        if opp.customer_id not in opps_by_customer:
            opps_by_customer[opp.customer_id] = []
        opps_by_customer[opp.customer_id].append(opp)
    
    pipeline_items = []
    
    for customer in customers:
        customer_opps = opps_by_customer.get(customer.id, [])
        
        if not customer_opps:
            # Customer without opportunities (lead)
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
                    'salesperson': customer.salesperson,
                    'notes': customer.notes,
                    'status': customer.status,
                    'created_at': customer.created_at.isoformat() if customer.created_at else None,
                }
            })
        else:
            # Customer with opportunities
            for opp in customer_opps:
                pipeline_items.append({
                    'id': f'opportunity-{opp.id}',
                    'type': 'opportunity',
                    'customer': {
                        'id': customer.id,
                        'name': customer.name,
                        'company_name': customer.company_name,
                        'address': customer.address,
                        'phone': customer.phone,
                        'email': customer.email,
                        'industry': customer.industry,
                        'company_size': customer.company_size,
                        'contact_made': customer.contact_made,
                        'preferred_contact_method': customer.preferred_contact_method,
                        'stage': customer.stage,
                        'salesperson': customer.salesperson,
                        'status': customer.status,
                    },
                    'opportunity': {
                        'id': opp.id,
                        'opportunity_name': opp.opportunity_name,
                        'opportunity_reference': opp.opportunity_reference,
                        'stage': opp.stage,
                        'priority': opp.priority,
                        'estimated_value': float(opp.estimated_value) if opp.estimated_value else None,
                        'probability': opp.probability,
                        'expected_close_date': opp.expected_close_date.isoformat() if opp.expected_close_date else None,
                        'salesperson_name': opp.salesperson_name,
                        'notes': opp.notes,
                        'created_at': opp.created_at.isoformat() if opp.created_at else None,
                    }
                })
    
    return jsonify(pipeline_items)


# ----------------------------------
# Stage Update Routes (CRITICAL FOR DRAG & DROP)
# ----------------------------------
@db_bp.route('/opportunities/<string:opportunity_id>/stage', methods=['PATCH', 'OPTIONS'])
@require_tenant  # ADD THIS
def update_opportunity_stage(opportunity_id):
    """Update opportunity stage via drag and drop"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    # ADD TENANT FILTER
    opportunity = Opportunity.query.filter_by(
        id=opportunity_id,
        tenant_id=g.tenant_id
    ).first()
    
    if not opportunity:
        return jsonify({'error': 'Opportunity not found'}), 404
    
    data = request.json
    
    new_stage = data.get('stage')
    reason = data.get('reason', 'Stage updated via drag and drop')
    
    if not new_stage:
        return jsonify({'error': 'Stage is required'}), 400
    
    old_stage = opportunity.stage
    opportunity.stage = new_stage
    opportunity.updated_at = datetime.utcnow()
    
    # Add audit note
    note_entry = f"\n[{datetime.utcnow().isoformat()}] Stage changed from {old_stage} to {new_stage}. Reason: {reason}"
    opportunity.notes = (opportunity.notes or '') + note_entry
    
    db.session.commit()
    
    return jsonify({
        'message': 'Stage updated successfully',
        'opportunity_id': opportunity.id,
        'old_stage': old_stage,
        'new_stage': new_stage,
        'stage_updated': True
    }), 200