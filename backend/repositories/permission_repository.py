"""
Permission Repository
Handles permission and role database operations.

CHANGES vs previous version
─────────────────────────────────────────────────────────────────────────────
[PR-001] ROLE SOURCE FIX — user_has_permission() previously read role IDs
         from Employee_Master.role_ids (a comma-separated varchar column) via
         user.employee.get_roles(). This is the legacy role store and is NOT
         the authoritative source.

         The canonical role store is User_Role_Mapping (the proper join table).
         auth_middleware.require_tenant_owner already reads User_Role_Mapping
         via the UserMaster.roles ORM relationship. Having permission_required
         read a different table meant the two guards were non-deterministic —
         a user could have a role in one store but not the other.

         Fix: user_has_permission() now queries UserRoleMapping directly using
         user.user_id. The Employee_Master.role_ids column is left intact for
         now (backward compat) but is no longer consulted for auth decisions.
─────────────────────────────────────────────────────────────────────────────
"""

from models import (
    PermissionCatalog, RoleMaster, RolePermissionMapping,
    UserRoleMapping,
    ModuleMaster, SubscriptionPlan, SubscriptionModuleMapping
)
from .base_repository import BaseRepository
from typing import List, Optional


class PermissionRepository:
    """Repository for Permission and Role operations"""

    def __init__(self):
        from database import db
        self.session = db.session

    # ============================================================
    # PERMISSION CATALOG
    # ============================================================

    def get_all_permissions(self) -> List[PermissionCatalog]:
        """Get all permissions"""
        return self.session.query(PermissionCatalog).all()

    def get_permission_by_code(self, permission_code: str) -> Optional[PermissionCatalog]:
        """Get permission by code"""
        return self.session.query(PermissionCatalog).filter(
            PermissionCatalog.permission_code == permission_code
        ).first()

    def create_permission(self, permission_code: str, description: str = None) -> PermissionCatalog:
        """Create a new permission"""
        permission = PermissionCatalog(
            permission_code=permission_code,
            description=description
        )
        self.session.add(permission)
        self.session.commit()
        return permission

    # ============================================================
    # ROLE MASTER
    # ============================================================

    def get_all_roles(self) -> List[RoleMaster]:
        """Get all roles"""
        return self.session.query(RoleMaster).all()

    def get_role_by_id(self, role_id: int) -> Optional[RoleMaster]:
        """Get role by ID"""
        return self.session.query(RoleMaster).get(role_id)

    def get_role_by_name(self, role_name: str) -> Optional[RoleMaster]:
        """Get role by name"""
        return self.session.query(RoleMaster).filter(
            RoleMaster.role_name == role_name
        ).first()

    def create_role(self, role_name: str, role_description: str = None,
                    is_system: bool = False) -> RoleMaster:
        """Create a new role"""
        role = RoleMaster(
            role_name=role_name,
            role_description=role_description,
            is_system=is_system
        )
        self.session.add(role)
        self.session.commit()
        return role

    # ============================================================
    # ROLE PERMISSION MAPPING
    # ============================================================

    def get_role_permissions(self, role_id: int) -> List[PermissionCatalog]:
        """Get all permissions for a role"""
        mappings = self.session.query(RolePermissionMapping).filter(
            RolePermissionMapping.role_id == role_id
        ).all()

        permission_ids = [m.permission_id for m in mappings]
        return self.session.query(PermissionCatalog).filter(
            PermissionCatalog.permission_id.in_(permission_ids)
        ).all()

    def add_permission_to_role(self, role_id: int, permission_id: int) -> bool:
        """Add a permission to a role"""
        existing = self.session.query(RolePermissionMapping).filter(
            RolePermissionMapping.role_id == role_id,
            RolePermissionMapping.permission_id == permission_id
        ).first()

        if existing:
            return False

        mapping = RolePermissionMapping(
            role_id=role_id,
            permission_id=permission_id
        )
        self.session.add(mapping)
        self.session.commit()
        return True

    def remove_permission_from_role(self, role_id: int, permission_id: int) -> bool:
        """Remove a permission from a role"""
        mapping = self.session.query(RolePermissionMapping).filter(
            RolePermissionMapping.role_id == role_id,
            RolePermissionMapping.permission_id == permission_id
        ).first()

        if mapping:
            self.session.delete(mapping)
            self.session.commit()
            return True
        return False

    def user_has_permission(self, user, permission_code: str) -> bool:
        """
        Check if a user has a specific permission.

        [PR-001] SOURCE OF TRUTH CHANGE:
        Previously read role IDs from Employee_Master.role_ids via
        user.employee.get_roles(). Now reads from User_Role_Mapping —
        the same join table that require_tenant_owner uses — so both
        permission guards are consistent.

        Args:
            user: UserMaster instance (user.user_id is used directly).
            permission_code: Permission code to check (e.g. 'client.create').

        Returns:
            True if the user holds at least one role that grants this permission.
        """
        if not user:
            return False

        # [PR-001] Read from User_Role_Mapping — the canonical role store.
        user_role_rows = (
            self.session.query(UserRoleMapping)
            .filter(UserRoleMapping.user_id == user.user_id)
            .all()
        )
        role_ids = [r.role_id for r in user_role_rows]

        if not role_ids:
            return False

        permission = self.get_permission_by_code(permission_code)
        if not permission:
            return False

        mapping = self.session.query(RolePermissionMapping).filter(
            RolePermissionMapping.role_id.in_(role_ids),
            RolePermissionMapping.permission_id == permission.permission_id
        ).first()

        return mapping is not None

    def get_user_role_ids(self, user_id: int) -> List[int]:
        """
        Return all role IDs assigned to a user via User_Role_Mapping.

        [PR-001] New helper used by PermissionService.get_user_permissions()
        to avoid repeating the UserRoleMapping query.
        """
        rows = (
            self.session.query(UserRoleMapping)
            .filter(UserRoleMapping.user_id == user_id)
            .all()
        )
        return [r.role_id for r in rows]

    # ============================================================
    # MODULE MASTER
    # ============================================================

    def get_all_modules(self) -> List[ModuleMaster]:
        """Get all modules"""
        return self.session.query(ModuleMaster).all()

    def get_active_modules(self) -> List[ModuleMaster]:
        """Get all active modules"""
        return self.session.query(ModuleMaster).filter(
            ModuleMaster.is_active == True
        ).all()

    def get_module_by_code(self, module_code: str) -> Optional[ModuleMaster]:
        """Get module by code"""
        return self.session.query(ModuleMaster).filter(
            ModuleMaster.module_code == module_code
        ).first()

    # ============================================================
    # SUBSCRIPTION PLANS
    # ============================================================

    def get_all_subscription_plans(self) -> List[SubscriptionPlan]:
        """Get all subscription plans"""
        return self.session.query(SubscriptionPlan).all()

    def get_active_subscription_plans(self) -> List[SubscriptionPlan]:
        """Get all active subscription plans"""
        return self.session.query(SubscriptionPlan).filter(
            SubscriptionPlan.is_active == True
        ).all()

    def get_subscription_by_code(self, subscription_code: str) -> Optional[SubscriptionPlan]:
        """Get subscription plan by code"""
        return self.session.query(SubscriptionPlan).filter(
            SubscriptionPlan.subscription_code == subscription_code
        ).first()

    def get_subscription_modules(self, subscription_id: int) -> List[ModuleMaster]:
        """Get all modules included in a subscription plan"""
        mappings = self.session.query(SubscriptionModuleMapping).filter(
            SubscriptionModuleMapping.subscription_id == subscription_id
        ).all()

        module_ids = [m.module_id for m in mappings]
        return self.session.query(ModuleMaster).filter(
            ModuleMaster.module_id.in_(module_ids)
        ).all()