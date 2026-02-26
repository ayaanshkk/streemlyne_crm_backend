"""
Employee Repository
Handles employee-related database operations
"""

from models import EmployeeMaster
from .base_repository import BaseRepository
from typing import List, Optional


class EmployeeRepository(BaseRepository):
    """Repository for Employee operations"""
    
    def __init__(self):
        super().__init__(EmployeeMaster)
    
    def get_by_email(self, email: str) -> Optional[EmployeeMaster]:
        """
        Find employee by email within current tenant
        
        Args:
            email: Employee email address
        
        Returns:
            EmployeeMaster instance or None
        """
        return self.find_one_by(email=email, force_tenant=True)
    
    def get_all_employees(self) -> List[EmployeeMaster]:
        """
        Get all employees for current tenant
        
        Returns:
            List of EmployeeMaster instances
        """
        return self.get_all(force_tenant=True)
    
    def get_by_designation(self, designation_id: int) -> List[EmployeeMaster]:
        """
        Get all employees with a specific designation
        
        Args:
            designation_id: Designation ID
        
        Returns:
            List of EmployeeMaster instances
        """
        return self.find_by(employee_designation_id=designation_id, force_tenant=True)
    
    def get_employees_with_role(self, role_id: int) -> List[EmployeeMaster]:
        """
        Get all employees that have a specific role
        
        Args:
            role_id: Role ID
        
        Returns:
            List of EmployeeMaster instances
        """
        employees = self.get_all_employees()
        return [emp for emp in employees if role_id in emp.get_roles()]
    
    def update_commission(self, employee_id: int, commission_percentage: float) -> Optional[EmployeeMaster]:
        """
        Update employee commission percentage
        
        Args:
            employee_id: Employee ID
            commission_percentage: New commission percentage
        
        Returns:
            Updated EmployeeMaster instance or None
        """
        return self.update(employee_id, commission_percentage=commission_percentage)