"""
Repositories Package
Data access layer with automatic tenant isolation
"""

from .base_repository import BaseRepository
from .tenant_repository import TenantRepository
from .master_repository import MasterRepository
from .employee_repository import EmployeeRepository
from .user_repository import UserRepository
from .permission_repository import PermissionRepository

__all__ = [
    'BaseRepository',
    'TenantRepository',
    'MasterRepository',
    'EmployeeRepository',
    'UserRepository',
    'PermissionRepository'
]