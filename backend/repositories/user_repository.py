"""
User Repository
Handles user authentication database operations
"""

from models import UserMaster, EmployeeMaster
from .base_repository import BaseRepository
from typing import Optional


class UserRepository(BaseRepository):
    """Repository for User authentication operations"""
    
    def __init__(self):
        super().__init__(UserMaster)
    
    def get_by_username(self, user_name: str) -> Optional[UserMaster]:
        """
        Find user by username
        
        Args:
            user_name: Username to search for
        
        Returns:
            UserMaster instance or None
        """
        return self.session.query(UserMaster).filter(
            UserMaster.user_name == user_name
        ).first()
    
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
    
    def create_user(self, employee_id: int, user_name: str, password: str) -> UserMaster:
        """
        Create a new user account
        
        Args:
            employee_id: Employee ID to link to
            user_name: Username for login
            password: Plain text password (will be hashed)
        
        Returns:
            Created UserMaster instance
        """
        user = UserMaster(
            employee_id=employee_id,
            user_name=user_name
        )
        user.set_password(password)
        self.session.add(user)
        self.session.commit()
        return user
    
    def authenticate(self, user_name: str, password: str) -> Optional[UserMaster]:
        """
        Authenticate user by username and password
        
        Args:
            user_name: Username
            password: Plain text password
        
        Returns:
            UserMaster instance if authentication successful, None otherwise
        """
        user = self.get_by_username(user_name)
        if not user:
            return None
        
        # Check if password is stored as hash or plain text
        if user.password and user.password.startswith('pbkdf2:sha256'):
            # Password is hashed - use check_password_hash
            if user.check_password(password):
                return user
        else:
            # Password is plain text - compare directly
            if user.password == password:
                return user
        
        return None