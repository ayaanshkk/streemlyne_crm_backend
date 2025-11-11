from flask import Blueprint, request, jsonify
from database import db
from models import (
    Customer, Opportunity, Activity, OpportunityNote, OpportunityDocument,
    Proposal, ProposalItem, Product, ProductCategory,
    Invoice, InvoiceLineItem, Payment, Team, TeamMember, 
    Salesperson, FormSubmission, CustomerFormData, AuditLog, Assignment
)
import json
from datetime import datetime

# Create blueprint
db_bp = Blueprint('database', __name__)

# ----------------------------------
# Customer Routes
# ----------------------------------

@db_bp.route('/customers', methods=['GET', 'POST'])
def handle_customers():
    if request.method == 'POST':
        data = request.json
        
        # Convert empty string to None for enum field
        preferred_contact = data.get('preferred_contact_method')
        if preferred_contact == '':
            preferred_contact = None
        
        customer = Customer(
            name=data.get('name', ''),
            company_name=data.get('company_name'),
            address=data.get('address'),
            postcode=data.get('postcode'),
            phone=data.get('phone'),
            email=data.get('email'),
            industry=data.get('industry'),
            company_size=data.get('company_size'),
            contact_made=data.get('contact_made', 'Unknown'),
            preferred_contact_method=preferred_contact,  # Use the converted value
            marketing_opt_in=data.get('marketing_opt_in', False),
            stage=data.get('stage', 'Prospect'),
            salesperson=data.get('salesperson'),
            notes=data.get('notes'),
            created_by=data.get('created_by', 'System'),
            status=data.get('status', 'active'),
        )
        
        db.session.add(customer)
        db.session.commit()
        
        return jsonify({
            'id': customer.id,
            'message': 'Customer created successfully'
        }), 201
    
    # GET all customers or filter by name
    name_query = request.args.get('name', type=str)
    if name_query:
        customers = Customer.query.filter(Customer.name.ilike(f"%{name_query}%")).all()
    else:
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
            'stage': c.stage,
            'salesperson': c.salesperson,
            'notes': c.notes,
            'status': c.status,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None,
            'created_by': c.created_by,
            'updated_by': c.updated_by,
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
            'stage': customer.stage,
            'salesperson': customer.salesperson,
            'notes': customer.notes,
            'status': customer.status,
            'created_at': customer.created_at.isoformat() if customer.created_at else None,
            'updated_at': customer.updated_at.isoformat() if customer.updated_at else None,
            'created_by': customer.created_by,
            'updated_by': customer.updated_by,
            'form_submissions': form_submissions,
            'opportunities': [
                {
                    'id': o.id,
                    'opportunity_name': o.opportunity_name,
                    'opportunity_reference': o.opportunity_reference,
                    'stage': o.stage,
                    'estimated_value': float(o.estimated_value) if o.estimated_value else None,
                    'probability': o.probability,
                    'expected_close_date': o.expected_close_date.isoformat() if o.expected_close_date else None,
                }
                for o in customer.opportunities
            ]
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
        
        # Handle preferred_contact_method - convert empty string to None
        preferred_contact = data.get('preferred_contact_method', customer.preferred_contact_method)
        if preferred_contact == '':
            preferred_contact = None
        customer.preferred_contact_method = preferred_contact
        
        customer.marketing_opt_in = data.get('marketing_opt_in', customer.marketing_opt_in)
        customer.stage = data.get('stage', customer.stage)
        customer.salesperson = data.get('salesperson', customer.salesperson)
        customer.notes = data.get('notes', customer.notes)
        customer.status = data.get('status', customer.status)
        customer.updated_by = data.get('updated_by', 'System')
        
        db.session.commit()
        return jsonify({'message': 'Customer updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': 'Customer deleted successfully'})

# ----------------------------------
# Opportunity Routes
# ----------------------------------

@db_bp.route('/opportunities', methods=['GET', 'POST'])
def handle_opportunities():
    if request.method == 'POST':
        data = request.json
        
        opportunity = Opportunity(
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
    
    # GET opportunities (optionally filtered by customer)
    customer_id = request.args.get('customer_id')
    if customer_id:
        opportunities = Opportunity.query.filter_by(customer_id=customer_id).order_by(Opportunity.created_at.desc()).all()
    else:
        opportunities = Opportunity.query.order_by(Opportunity.created_at.desc()).all()
    
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
def handle_single_opportunity(opportunity_id):
    opportunity = Opportunity.query.get_or_404(opportunity_id)
    
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
def handle_proposals():
    if request.method == 'POST':
        data = request.json
        proposal = Proposal(
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
    if customer_id:
        proposals = Proposal.query.filter_by(customer_id=customer_id).all()
    else:
        proposals = Proposal.query.all()
        
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
def handle_invoices():
    if request.method == 'POST':
        data = request.json
        
        invoice = Invoice(
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
    
    # GET invoices
    opportunity_id = request.args.get('opportunity_id')
    if opportunity_id:
        invoices = Invoice.query.filter_by(opportunity_id=opportunity_id).order_by(Invoice.created_at.desc()).all()
    else:
        invoices = Invoice.query.order_by(Invoice.created_at.desc()).all()
    
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
def handle_teams():
    if request.method == 'POST':
        data = request.json
        team = Team(
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
    
    teams = Team.query.filter_by(active=True).all()
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
def handle_salespeople():
    if request.method == 'POST':
        data = request.json
        salesperson = Salesperson(
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
    
    salespeople = Salesperson.query.filter_by(active=True).all()
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
    
    # GET jobs (mapped to opportunities)
    customer_id = request.args.get('customer_id')
    if customer_id:
        opportunities = Opportunity.query.filter_by(customer_id=customer_id).order_by(Opportunity.created_at.desc()).all()
    else:
        opportunities = Opportunity.query.order_by(Opportunity.created_at.desc()).all()
    
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
def handle_single_job(job_id):
    """Single job endpoint (mapped to opportunity)"""
    opportunity = Opportunity.query.get_or_404(job_id)
    
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
def get_pipeline_data():
    """
    Returns combined customer/opportunity data for pipeline view
    """
    customers = Customer.query.all()
    opportunities = Opportunity.query.all()
    
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