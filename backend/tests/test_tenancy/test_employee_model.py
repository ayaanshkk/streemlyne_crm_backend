"""
Test Employee Model
"""

import pytest
from models import EmployeeMaster
from datetime import date


def test_create_employee(session, tenant):
    """Test creating an employee"""
    from flask import g
    g.tenant_id = tenant.tenant_id
    
    employee = EmployeeMaster(
        tenant_id=tenant.tenant_id,
        employee_name='Test Employee',
        email='emp@test.com',
        phone='555-0100',
        date_of_joining=date.today()
    )
    session.add(employee)
    session.commit()
    
    assert employee.employee_id is not None
    assert employee.employee_name == 'Test Employee'


def test_employee_roles(session, employee):
    """Test employee role management"""
    # Add role
    employee.add_role(1)
    assert 1 in employee.get_roles()
    
    # Add another role
    employee.add_role(2)
    roles = employee.get_roles()
    assert 1 in roles
    assert 2 in roles
    
    # Remove role
    employee.remove_role(1)
    assert 1 not in employee.get_roles()
    assert 2 in employee.get_roles()


def test_employee_to_dict(session, employee):
    """Test employee to_dict method"""
    emp_dict = employee.to_dict()
    
    assert 'employee_id' in emp_dict
    assert 'employee_name' in emp_dict
    assert emp_dict['employee_name'] == employee.employee_name