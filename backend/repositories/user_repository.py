"""
User Repository
Handles user authentication database operations
"""
#C:\streemlyne_crm_backend\backend\repositories\user_repository.py
from models import UserMaster, EmployeeMaster
from .base_repository import BaseRepository
from typing import Optional


class UserRepository(BaseRepository):
    """Repository for User authentication operations"""
    
    def __init__(self):
        super().__init__(UserMaster)
    
    def get_by_username(self, user_name: str) -> Optional[UserMaster]:
        query = self.session.query(UserMaster).filter(
            UserMaster.user_name == user_name
        )
        print(f"[DEBUG] SQL: {query}")          # ← add this
        result = query.first()
        print(f"[DEBUG] result: {result}")      # ← add this
        return result
    
    def get_by_employee_id(self, employee_id: int) -> Optional[UserMaster]:
        """
        Find user by employee ID
        
        Args:
            employee_id: Employee ID
        
        Returns:
            UserMaster instance or None
        """
        return self.find_one_by(employee_id=employee_id, force_tenant=False)
    
    def get_with_employee(self, user_id: int) -> Optional[UserMaster]:
        """
        Get user with employee details loaded
        
        Args:
            user_id: User ID
        
        Returns:
            UserMaster instance with employee relationship loaded
        """
        return self.session.query(UserMaster).filter(
            UserMaster.user_id == user_id
        ).join(EmployeeMaster).first()
    
    def create_user(self, employee_id: int, user_name: str, password: str,
                    is_active: bool = True,
                    tenant_id: str = None,
                    is_invite_pending: bool = False) -> UserMaster:
        user = UserMaster(
            employee_id=employee_id,
            user_name=user_name,
            is_active=is_active,
            tenant_id=tenant_id,
            is_invite_pending=is_invite_pending,
        )
        user.set_password(password)
        self.session.add(user)
        self.session.commit()
        return user
    
    def authenticate(self, user_name: str, password: str) -> Optional[UserMaster]:
        user = self.get_by_username(user_name)
        if not user:
            return None
        if not user.is_active:        # ← block inactive users
            return None
        if user.check_password(password):
            return user
        return None