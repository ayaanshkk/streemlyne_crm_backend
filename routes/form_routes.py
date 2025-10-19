# routes/form_routes.py - Fixed to create only one submission record
from flask import Blueprint, request, jsonify, current_app
from models import db, Customer, CustomerFormData
import secrets
import string
import json
from datetime import datetime, timedelta

form_bp = Blueprint("form", __name__)

# In-memory storage for form tokens (for production use Redis/DB)
form_tokens = {}

def generate_secure_token(length=32):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@form_bp.route('/customers/<customer_id>/generate-form-link', methods=['POST', 'OPTIONS'])
def generate_customer_form_link(customer_id):
    """Generate form link for specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Verify customer exists
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({
                'success': False,
                'error': 'Customer not found'
            }), 404

        data = request.get_json(silent=True) or {}
        form_type = data.get('formType', 'bedroom')  # bedroom or kitchen

        token = generate_secure_token()
        expiration = datetime.now() + timedelta(hours=24)
        
        # Store token with customer association
        form_tokens[token] = {
            'customer_id': customer_id,
            'form_type': form_type,
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        
        current_app.logger.debug(f"Generated token {token} for customer {customer_id}, expires {expiration}")

        return jsonify({
            'success': True,
            'token': token,
            'form_type': form_type,
            'expires_at': expiration.isoformat(),
            'message': f'{form_type.title()} form link generated successfully'
        }), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to generate form link for customer {customer_id}")
        return jsonify({
            'success': False,
            'error': f'Failed to generate form link: {str(e)}'
        }), 500

@form_bp.route('/validate-form-token/<token>', methods=['GET', 'OPTIONS'])
def validate_form_token(token):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        current_app.logger.debug(f"Validating token: {token}")
        if token not in form_tokens:
            return jsonify({'valid': False, 'error': 'Invalid token'}), 404

        token_data = form_tokens[token]

        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({'valid': False, 'error': 'Token has expired'}), 410

        if token_data['used']:
            return jsonify({'valid': False, 'error': 'Token has already been used'}), 410

        return jsonify({
            'valid': True, 
            'expires_at': token_data['expires_at'].isoformat(),
            'customer_id': token_data.get('customer_id'),
            'form_type': token_data.get('form_type')
        }), 200

    except Exception as e:
        current_app.logger.exception("Token validation failed")
        return jsonify({'valid': False, 'error': f'Validation failed: {str(e)}'}), 500

@form_bp.route('/submit-customer-form', methods=['POST', 'OPTIONS'])
def submit_customer_form():
    """Submit form - creates only ONE submission record"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.get_json(silent=True) or {}
        token = data.get('token')
        form_data = data.get('formData', {})

        if not form_data:
            return jsonify({'success': False, 'error': 'Missing form data'}), 400

        customer_id = None
        
        # Try token-based submission first (for existing customers)
        if token:
            current_app.logger.debug(f"Processing token-based submission with token: {token}")
            
            if token not in form_tokens:
                return jsonify({'success': False, 'error': 'Invalid or expired token'}), 400

            token_data = form_tokens[token]
            
            # Check expiration
            if datetime.now() > token_data['expires_at']:
                del form_tokens[token]
                return jsonify({'success': False, 'error': 'Token has expired'}), 410
                
            # Check if already used
            if token_data['used']:
                return jsonify({'success': False, 'error': 'Token has already been used'}), 410

            customer_id = token_data.get('customer_id')
            
            # Verify customer exists
            if customer_id:
                customer = Customer.query.get(customer_id)
                if not customer:
                    return jsonify({'success': False, 'error': 'Associated customer not found'}), 404
                
                # Mark token as used
                form_tokens[token]['used'] = True
                current_app.logger.info(f"Token {token} marked as used for customer {customer_id}")
        
        # If no valid token or customer_id from token, try alternative methods
        if not customer_id:
            # Check if customer_id is provided directly in form data or URL params
            customer_id = form_data.get('customer_id') or request.args.get('customerId')
            
            if customer_id:
                # Verify this customer exists
                customer = Customer.query.get(customer_id)
                if not customer:
                    return jsonify({'success': False, 'error': 'Specified customer not found'}), 404
            else:
                # Fallback: create new customer from form data (legacy behavior)
                customer_name = (form_data.get('customer_name') or '').strip()
                customer_address = (form_data.get('customer_address') or '').strip()
                
                if not customer_name or not customer_address:
                    return jsonify({
                        'success': False, 
                        'error': 'Customer name and address are required for new customer creation'
                    }), 400
                
                customer = Customer(
                    name=customer_name,
                    phone=(form_data.get('customer_phone') or '').strip(),
                    address=customer_address,
                    status='New Lead',
                    created_by='Form Submission'
                )
                db.session.add(customer)
                db.session.flush()  # Get the ID without committing
                customer_id = customer.id
                current_app.logger.info(f"Created new customer {customer_id} from form submission")

        # Create ONLY ONE form submission record
        try:
            customer_form_data = CustomerFormData(
                customer_id=customer_id,
                form_data=json.dumps(form_data),
                token_used=token or '',
                submitted_at=datetime.utcnow()
            )
            db.session.add(customer_form_data)
            db.session.commit()
            
            # Get customer name for response
            final_customer = Customer.query.get(customer_id)
            customer_name = final_customer.name if final_customer else 'Customer'
            
            current_app.logger.info(f"Single form submission created for customer {customer_id}")

            return jsonify({
                'success': True, 
                'customer_id': customer_id,
                'form_submission_id': customer_form_data.id,
                'message': f'Form submitted successfully for {customer_name}'
            }), 201

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception(f"Database error during form submission for customer {customer_id}")
            raise e

    except Exception as e:
        current_app.logger.exception("Form submission failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Form submission failed: {str(e)}'}), 500

# Legacy endpoint for backward compatibility
@form_bp.route('/generate-form-link', methods=['POST', 'OPTIONS'])
def generate_form_link():
    """Legacy endpoint - generates token not tied to specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        token = generate_secure_token()
        expiration = datetime.now() + timedelta(hours=24)
        form_tokens[token] = {
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        current_app.logger.debug(f"Generated legacy token {token} expires {expiration}")

        return jsonify({
            'success': True,
            'token': token,
            'expires_at': expiration.isoformat(),
            'message': 'Form link generated successfully'
        }), 200

    except Exception as e:
        current_app.logger.exception("Failed to generate form link")
        return jsonify({
            'success': False,
            'error': f'Failed to generate form link: {str(e)}'
        }), 500

@form_bp.route('/cleanup-expired-tokens', methods=['POST', 'OPTIONS'])
def cleanup_expired_tokens():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        current_time = datetime.now()
        expired_tokens = [t for t, d in form_tokens.items() if current_time > d['expires_at']]
        for t in expired_tokens:
            del form_tokens[t]
        return jsonify({
            'success': True, 
            'cleaned_tokens': len(expired_tokens), 
            'remaining_tokens': len(form_tokens)
        }), 200
    except Exception as e:
        current_app.logger.exception("Cleanup failed")
        return jsonify({'success': False, 'error': f'Cleanup failed: {str(e)}'}), 500