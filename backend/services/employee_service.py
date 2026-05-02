"""
Employee Service
Business logic for employee management
"""

from repositories import EmployeeRepository, UserRepository
from models import EmployeeMaster, UserMaster
from typing import List, Optional, Dict
from datetime import date


class EmployeeService:
    """Service for employee business logic"""
    
    def __init__(self):
        self.repo = EmployeeRepository()
        self.user_repo = UserRepository()
    
    def create_employee(self, employee_name: str, email: str, phone: str = None,
                       designation_id: int = None, date_of_joining: date = None,
                       **kwargs) -> EmployeeMaster:
        """
        Create a new employee
        
        Args:
            employee_name: Employee full name
            email: Employee email
            phone: Employee phone
            designation_id: Designation ID
            date_of_joining: Date of joining
            **kwargs: Additional fields
        
        Returns:
            Created EmployeeMaster instance
        
        Raises:
            ValueError: If email already exists
        """
        # Check if email already exists
        existing = self.repo.get_by_email(email)
        if existing:
            raise ValueError(f"Employee with email '{email}' already exists")
        
        # Create employee
        employee = self.repo.create(
            employee_name=employee_name,
            email=email,
            phone=phone,
            employee_designation_id=designation_id,
            date_of_joining=date_of_joining or date.today(),
            **kwargs
        )
        
        return employee
    
    def get_employee(self, employee_id: int) -> Optional[EmployeeMaster]:
        """Get employee by ID"""
        return self.repo.get_by_id(employee_id)
    
    def get_all_employees(self) -> List[EmployeeMaster]:
        """Get all employees for current tenant"""
        return self.repo.get_all_employees()
    
    def get_by_email(self, email: str) -> Optional[EmployeeMaster]:
        """Get employee by email"""
        return self.repo.get_by_email(email)
    
    def update_employee(self, employee_id: int, **updates) -> Optional[EmployeeMaster]:
        """Update employee information"""
        return self.repo.update(employee_id, **updates)
    
    def delete_employee(self, employee_id: int) -> bool:
        """Delete an employee"""
        return self.repo.delete(employee_id)
    
    def get_employees_by_designation(self, designation_id: int) -> List[EmployeeMaster]:
        """Get all employees with a specific designation"""
        return self.repo.get_by_designation(designation_id)
    
    def assign_role(self, employee_id: int, role_id: int) -> Optional[EmployeeMaster]:
        """
        Assign a role to an employee
        
        Args:
            employee_id: Employee ID
            role_id: Role ID to assign
        
        Returns:
            Updated EmployeeMaster instance or None
        """
        employee = self.get_employee(employee_id)
        if not employee:
            return None
        
        employee.add_role(role_id)
        self.repo.commit()
        return employee
    
    def revoke_role(self, employee_id: int, role_id: int) -> Optional[EmployeeMaster]:
        """
        Revoke a role from an employee
        
        Args:
            employee_id: Employee ID
            role_id: Role ID to revoke
        
        Returns:
            Updated EmployeeMaster instance or None
        """
        employee = self.get_employee(employee_id)
        if not employee:
            return None
        
        employee.remove_role(role_id)
        self.repo.commit()
        return employee
    
    def create_user_account(self, employee_id: int, user_name: str, password: str) -> UserMaster:
        employee = self.get_employee(employee_id)
        if not employee:
            raise ValueError(f"Employee {employee_id} not found")
        
        existing_user = self.user_repo.get_by_employee_id(employee_id)
        if existing_user:
            raise ValueError(f"Employee already has a user account")
        
        existing_username = self.user_repo.get_by_username(user_name)
        if existing_username:
            raise ValueError(f"Username '{user_name}' already exists")

        return self.user_repo.create_user(
            employee_id,
            user_name,
            password,
            is_active=True,
            tenant_id=employee.tenant_id,
            is_invite_pending=False,
        )
    
    def get_employee_summary(self, employee_id: int) -> Optional[Dict]:
        """
        Get employee summary with related data
        
        Args:
            employee_id: Employee ID
        
        Returns:
            Dictionary with employee details or None
        """
        employee = self.get_employee(employee_id)
        if not employee:
            return None
        
        # Get user account
        user = self.user_repo.get_by_employee_id(employee_id)
        
        return {
            'employee_id': employee.employee_id,
            'employee_name': employee.employee_name,
            'email': employee.email,
            'phone': employee.phone,
            'designation': employee.designation.designation_description if employee.designation else None,
            'date_of_joining': employee.date_of_joining.isoformat() if employee.date_of_joining else None,
            'roles': employee.get_roles(),
            'commission_percentage': employee.commission_percentage,
            'has_user_account': user is not None,
            'user_name': user.user_name if user else None,
            'created_on': employee.created_on.isoformat() if employee.created_on else None
        }