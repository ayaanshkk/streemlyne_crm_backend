# routes/customer_routes.py
from flask import Blueprint, request, jsonify, g
from database import db
from models import Customer, CustomerFormData, Opportunity
from tenant_middleware import require_tenant, check_feature
import json
from datetime import datetime

customer_bp = Blueprint('customer', __name__)

# ----------------------------------
# Customer Routes
# ----------------------------------

@customer_bp.route('/customers', methods=['GET', 'POST'])
@require_tenant
def handle_customers():
    if request.method == 'POST':
        data = request.json
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Customer name is required'}), 400
        
        # Convert empty string to None for enum field
        preferred_contact = data.get('preferred_contact_method')
        if preferred_contact == '':
            preferred_contact = None
        
        customer = Customer(
            tenant_id=g.tenant_id,  # CRITICAL: Set tenant_id
            name=data.get('name', ''),
            company_name=data.get('company_name'),
            address=data.get('address'),
            postcode=data.get('postcode'),
            phone=data.get('phone'),
            email=data.get('email'),
            industry=data.get('industry'),
            company_size=data.get('company_size'),
            contact_made=data.get('contact_made', 'Unknown'),
            preferred_contact_method=preferred_contact,
            marketing_opt_in=data.get('marketing_opt_in', False),
            stage=data.get('stage', 'Prospect'),
            salesperson=data.get('salesperson'),
            notes=data.get('notes'),
            created_by=g.user.get_full_name(),  # Use authenticated user
            status=data.get('status', 'active'),
        )
        
        db.session.add(customer)
        db.session.commit()
        
        return jsonify({
            'id': customer.id,
            'tenant_id': customer.tenant_id,
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
            'message': 'Customer created successfully'
        }), 201
    
    # GET all customers - filtered by tenant
    name_query = request.args.get('name', type=str)
    
    query = Customer.query.filter_by(tenant_id=g.tenant_id)  # CRITICAL: Filter by tenant
    
    if name_query:
        query = query.filter(Customer.name.ilike(f"%{name_query}%"))
    
    customers = query.order_by(Customer.created_at.desc()).all()
    
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

@customer_bp.route('/customers/<string:customer_id>', methods=['GET', 'PUT', 'DELETE'])
@require_tenant
def handle_single_customer(customer_id):
    # CRITICAL: Filter by both id AND tenant_id for security
    customer = Customer.query.filter_by(
        id=customer_id,
        tenant_id=g.tenant_id
    ).first()
    
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    
    if request.method == 'GET':
        # Fetch form submissions for this customer
        form_entries = CustomerFormData.query.filter_by(
            customer_id=customer.id,
            tenant_id=g.tenant_id  # CRITICAL: Filter by tenant
        ).order_by(CustomerFormData.submitted_at.desc()).all()
        
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
        customer.updated_by = g.user.get_full_name()
        
        db.session.commit()
        return jsonify({'message': 'Customer updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': 'Customer deleted successfully'})


@customer_bp.route('/customers/<string:customer_id>/stage', methods=['PATCH'])
@require_tenant
def update_customer_stage(customer_id):
    """Update customer stage via drag and drop"""
    # CRITICAL: Filter by tenant
    customer = Customer.query.filter_by(
        id=customer_id,
        tenant_id=g.tenant_id
    ).first()
    
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    
    data = request.json
    
    new_stage = data.get('stage')
    reason = data.get('reason', 'Stage updated via drag and drop')
    
    if not new_stage:
        return jsonify({'error': 'Stage is required'}), 400
    
    old_stage = customer.stage
    customer.stage = new_stage
    customer.updated_by = g.user.get_full_name()
    customer.updated_at = datetime.utcnow()
    
    # Add audit note
    note_entry = f"\n[{datetime.utcnow().isoformat()}] Stage changed from {old_stage} to {new_stage}. Reason: {reason}"
    customer.notes = (customer.notes or '') + note_entry
    
    db.session.commit()
    
    return jsonify({
        'message': 'Stage updated successfully',
        'customer_id': customer.id,
        'old_stage': old_stage,
        'new_stage': new_stage,
        'stage_updated': True
    }), 200