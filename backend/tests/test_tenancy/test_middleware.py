"""
Test Middleware
"""

import pytest
from flask import g
from middleware import inject_tenant_context, get_current_tenant_id


def test_inject_tenant_context(app, client, user):
    """Test tenant context injection from JWT"""
    
    # Generate token
    token = user.generate_jwt_token(app.config['SECRET_KEY'])
    
    # Make request with token
    with app.test_request_context(
        headers={'Authorization': f'Bearer {token}'}
    ):
        inject_tenant_context()
        
        # Check tenant_id was injected
        assert hasattr(g, 'tenant_id')
        assert g.tenant_id == user.employee.tenant_id


def test_get_current_tenant_id(app):
    """Test getting current tenant ID"""
    with app.test_request_context():
        # No tenant_id set yet
        tenant_id = get_current_tenant_id()
        assert tenant_id is None
        
        # Set tenant_id
        g.tenant_id = 123
        tenant_id = get_current_tenant_id()
        assert tenant_id == 123