"""
Permission Service
Business logic for permission and role management
"""

from repositories import PermissionRepository
from models import PermissionCatalog, RoleMaster, UserMaster
from typing import List, Optional, Dict


class PermissionService:
    """Service for permission and role business logic"""
    
    def __init__(self):
        self.repo = PermissionRepository()
    
    # ============================================================
    # PERMISSIONS
    # ============================================================
    
    def get_all_permissions(self) -> List[PermissionCatalog]:
        """Get all available permissions"""
        return self.repo.get_all_permissions()
    
    def create_permission(self, permission_code: str, description: str = None) -> PermissionCatalog:
        """
        Create a new permission
        
        Args:
            permission_code: Unique permission code (e.g., 'client.create')
            description: Human-readable description
        
        Returns:
            Created PermissionCatalog instance
        
        Raises:
            ValueError: If permission code already exists
        """
        existing = self.repo.get_permission_by_code(permission_code)
        if existing:
            raise ValueError(f"Permission '{permission_code}' already exists")
        
        return self.repo.create_permission(permission_code, description)
    
    # ============================================================
    # ROLES
    # ============================================================
    
    def get_all_roles(self) -> List[RoleMaster]:
        """Get all roles"""
        return self.repo.get_all_roles()
    
    def get_role(self, role_id: int) -> Optional[RoleMaster]:
        """Get role by ID"""
        return self.repo.get_role_by_id(role_id)
    
    def create_role(self, role_name: str, role_description: str = None,
                   is_system: bool = False) -> RoleMaster:
        """
        Create a new role
        
        Args:
            role_name: Role name (e.g., 'Admin', 'Manager')
            role_description: Description of the role
            is_system: Whether this is a system role (cannot be deleted)
        
        Returns:
            Created RoleMaster instance
        
        Raises:
            ValueError: If role name already exists
        """
        existing = self.repo.get_role_by_name(role_name)
        if existing:
            raise ValueError(f"Role '{role_name}' already exists")
        
        return self.repo.create_role(role_name, role_description, is_system)
    
    def delete_role(self, role_id: int) -> bool:
        """
        Delete a role
        
        Args:
            role_id: Role ID
        
        Returns:
            True if deleted, False if not found or is system role
        """
        role = self.get_role(role_id)
        if not role:
            return False
        
        if role.is_system:
            raise ValueError("Cannot delete system role")
        
        self.repo.session.delete(role)
        self.repo.session.commit()
        return True
    
    # ============================================================
    # ROLE PERMISSIONS
    # ============================================================
    
    def get_role_permissions(self, role_id: int) -> List[PermissionCatalog]:
        """Get all permissions for a role"""
        return self.repo.get_role_permissions(role_id)
    
    def assign_permission_to_role(self, role_id: int, permission_code: str) -> bool:
        """
        Assign a permission to a role
        
        Args:
            role_id: Role ID
            permission_code: Permission code
        
        Returns:
            True if successful, False if already assigned
        
        Raises:
            ValueError: If role or permission not found
        """
        # Verify role exists
        role = self.get_role(role_id)
        if not role:
            raise ValueError(f"Role {role_id} not found")
        
        # Verify permission exists
        permission = self.repo.get_permission_by_code(permission_code)
        if not permission:
            raise ValueError(f"Permission '{permission_code}' not found")
        
        return self.repo.add_permission_to_role(role_id, permission.permission_id)
    
    def revoke_permission_from_role(self, role_id: int, permission_code: str) -> bool:
        """
        Revoke a permission from a role
        
        Args:
            role_id: Role ID
            permission_code: Permission code
        
        Returns:
            True if successful, False if not assigned
        """
        permission = self.repo.get_permission_by_code(permission_code)
        if not permission:
            return False
        
        return self.repo.remove_permission_from_role(role_id, permission.permission_id)
    
    # ============================================================
    # USER PERMISSIONS
    # ============================================================
    
    def user_has_permission(self, user: UserMaster, permission_code: str) -> bool:
        """
        Check if user has a specific permission
        
        Args:
            user: UserMaster instance with employee loaded
            permission_code: Permission code to check
        
        Returns:
            True if user has permission, False otherwise
        """
        return self.repo.user_has_permission(user, permission_code)
    
    def get_user_permissions(self, user: UserMaster) -> List[str]:
        """
        Get all permission codes for a user
        
        Args:
            user: UserMaster instance with employee loaded
        
        Returns:
            List of permission codes
        """
        if not user or not user.employee:
            return []
        
        role_ids = user.employee.get_roles()
        if not role_ids:
            return []
        
        all_permissions = []
        for role_id in role_ids:
            permissions = self.get_role_permissions(role_id)
            all_permissions.extend([p.permission_code for p in permissions])
        
        return list(set(all_permissions))  # Remove duplicates