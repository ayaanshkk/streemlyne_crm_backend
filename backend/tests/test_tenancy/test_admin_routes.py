"""
Test Admin Routes
"""

import pytest
import json


def test_get_all_tenants_unauthorized(client):
    """Test getting tenants without authentication"""
    response = client.get('/api/admin/tenants')
    
    # Should return 401 Unauthorized
    assert response.status_code == 401


def test_get_all_tenants_authorized(client, user):
    """Test getting tenants with authentication"""
    # Login first
    token = user.generate_jwt_token('test-secret-key')
    
    response = client.get(
        '/api/admin/tenants',
        headers={'Authorization': f'Bearer {token}'}
    )
    
    # Should return 200 OK (or 403 if user doesn't have permission)
    assert response.status_code in [200, 403]


def test_get_master_data_countries(client, user):
    """Test getting countries master data"""
    token = user.generate_jwt_token('test-secret-key')
    
    response = client.get(
        '/api/admin/master-data/countries',
        headers={'Authorization': f'Bearer {token}'}
    )
    
    assert response.status_code in [200, 403]
    
    if response.status_code == 200:
        data = json.loads(response.data)
        assert isinstance(data, list)


def test_get_master_data_currencies(client, user):
    """Test getting currencies master data"""
    token = user.generate_jwt_token('test-secret-key')
    
    response = client.get(
        '/api/admin/master-data/currencies',
        headers={'Authorization': f'Bearer {token}'}
    )
    
    assert response.status_code in [200, 403]
    
    if response.status_code == 200:
        data = json.loads(response.data)
        assert isinstance(data, list)
