"""
Base Repository
Provides common CRUD operations with automatic tenant isolation
All repositories should inherit from this
"""

from database import db
from sqlalchemy import and_
from typing import List, Optional, Any, Type, TypeVar
from flask import g

# Generic type for models
T = TypeVar('T', bound=db.Model)


class BaseRepository:
    """
    Base repository with common database operations
    
    IMPORTANT: All queries automatically filter by tenant_id from Flask g context
    This ensures tenant isolation at the data access layer
    """
    
    def __init__(self, model: Type[T]):
        """
        Initialize repository with a model class
        
        Args:
            model: SQLAlchemy model class (e.g., TenantMaster, EmployeeMaster)
        """
        self.model = model
        self.session = db.session
    
    def _get_tenant_id(self) -> int:
        """
        Get current tenant_id from Flask g context
        
        Returns:
            tenant_id from request context
        
        Raises:
            RuntimeError: If tenant_id not found in context
        """
        tenant_id = getattr(g, 'tenant_id', None)
        if tenant_id is None:
            raise RuntimeError(
                "tenant_id not found in request context. "
                "Ensure tenant_context middleware is applied."
            )
        return tenant_id
    
    def _apply_tenant_filter(self, query, force_tenant: bool = True):
        """
        Apply tenant_id filter to query if model has tenant_id column
        
        Args:
            query: SQLAlchemy query object
            force_tenant: If True, always filter by tenant. If False, skip for master tables
        
        Returns:
            Filtered query
        """
        # Check if model has tenant_id column
        if hasattr(self.model, 'tenant_id') and force_tenant:
            tenant_id = self._get_tenant_id()
            return query.filter(self.model.tenant_id == tenant_id)
        return query
    
    def create(self, **kwargs) -> T:
        """
        Create a new record
        
        Args:
            **kwargs: Field values for the new record
        
        Returns:
            Created model instance
        
        Example:
            repo.create(employee_name="John Doe", email="john@example.com")
        """
        # Automatically add tenant_id if model has it
        if hasattr(self.model, 'tenant_id') and 'tenant_id' not in kwargs:
            kwargs['tenant_id'] = self._get_tenant_id()
        
        instance = self.model(**kwargs)
        self.session.add(instance)
        self.session.commit()
        return instance
    
    def get_by_id(self, record_id: Any, force_tenant: bool = True) -> Optional[T]:
        """
        Get a single record by primary key
        
        Args:
            record_id: Primary key value
            force_tenant: If True, filter by tenant_id
        
        Returns:
            Model instance or None if not found
        
        Example:
            employee = repo.get_by_id(5)
        """
        query = self.session.query(self.model).filter(
            self.model.__mapper__.primary_key[0] == record_id
        )
        query = self._apply_tenant_filter(query, force_tenant)
        return query.first()
    
    def get_all(self, force_tenant: bool = True) -> List[T]:
        """
        Get all records (filtered by tenant)
        
        Args:
            force_tenant: If True, filter by tenant_id
        
        Returns:
            List of model instances
        
        Example:
            employees = repo.get_all()
        """
        query = self.session.query(self.model)
        query = self._apply_tenant_filter(query, force_tenant)
        return query.all()
    
    def find_by(self, force_tenant: bool = True, **filters) -> List[T]:
        """
        Find records by field values
        
        Args:
            force_tenant: If True, filter by tenant_id
            **filters: Field name and value pairs
        
        Returns:
            List of matching model instances
        
        Example:
            employees = repo.find_by(designation_id=3, force_tenant=True)
        """
        query = self.session.query(self.model)
        query = self._apply_tenant_filter(query, force_tenant)
        
        for field, value in filters.items():
            if hasattr(self.model, field):
                query = query.filter(getattr(self.model, field) == value)
        
        return query.all()
    
    def find_one_by(self, force_tenant: bool = True, **filters) -> Optional[T]:
        """
        Find a single record by field values
        
        Args:
            force_tenant: If True, filter by tenant_id
            **filters: Field name and value pairs
        
        Returns:
            Model instance or None
        
        Example:
            user = repo.find_one_by(user_name="admin")
        """
        query = self.session.query(self.model)
        query = self._apply_tenant_filter(query, force_tenant)
        
        for field, value in filters.items():
            if hasattr(self.model, field):
                query = query.filter(getattr(self.model, field) == value)
        
        return query.first()
    
    def update(self, record_id: Any, **updates) -> Optional[T]:
        """
        Update a record by primary key
        
        Args:
            record_id: Primary key value
            **updates: Fields to update with new values
        
        Returns:
            Updated model instance or None if not found
        
        Example:
            repo.update(5, employee_name="Jane Doe", phone="555-0123")
        """
        instance = self.get_by_id(record_id)
        if instance:
            for field, value in updates.items():
                if hasattr(instance, field):
                    setattr(instance, field, value)
            self.session.commit()
        return instance
    
    def delete(self, record_id: Any) -> bool:
        """
        Delete a record by primary key
        
        Args:
            record_id: Primary key value
        
        Returns:
            True if deleted, False if not found
        
        Example:
            success = repo.delete(5)
        """
        instance = self.get_by_id(record_id)
        if instance:
            self.session.delete(instance)
            self.session.commit()
            return True
        return False
    
    def count(self, force_tenant: bool = True) -> int:
        """
        Count records (filtered by tenant)
        
        Args:
            force_tenant: If True, filter by tenant_id
        
        Returns:
            Number of records
        
        Example:
            total_employees = repo.count()
        """
        query = self.session.query(self.model)
        query = self._apply_tenant_filter(query, force_tenant)
        return query.count()
    
    def exists(self, record_id: Any, force_tenant: bool = True) -> bool:
        """
        Check if a record exists
        
        Args:
            record_id: Primary key value
            force_tenant: If True, filter by tenant_id
        
        Returns:
            True if exists, False otherwise
        
        Example:
            if repo.exists(5):
                print("Employee exists")
        """
        return self.get_by_id(record_id, force_tenant) is not None
    
    def paginate(self, page: int = 1, per_page: int = 20, force_tenant: bool = True):
        """
        Get paginated results
        
        Args:
            page: Page number (1-indexed)
            per_page: Records per page
            force_tenant: If True, filter by tenant_id
        
        Returns:
            Dict with items, total, page, per_page, pages
        
        Example:
            result = repo.paginate(page=2, per_page=10)
            for employee in result['items']:
                print(employee.employee_name)
        """
        query = self.session.query(self.model)
        query = self._apply_tenant_filter(query, force_tenant)
        
        total = query.count()
        items = query.limit(per_page).offset((page - 1) * per_page).all()
        
        return {
            'items': items,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page  # Ceiling division
        }
    
    def bulk_create(self, records: List[dict]) -> List[T]:
        """
        Create multiple records at once
        
        Args:
            records: List of dictionaries with field values
        
        Returns:
            List of created model instances
        
        Example:
            employees = repo.bulk_create([
                {'employee_name': 'John', 'email': 'john@example.com'},
                {'employee_name': 'Jane', 'email': 'jane@example.com'}
            ])
        """
        instances = []
        for record_data in records:
            # Auto-add tenant_id
            if hasattr(self.model, 'tenant_id') and 'tenant_id' not in record_data:
                record_data['tenant_id'] = self._get_tenant_id()
            
            instance = self.model(**record_data)
            instances.append(instance)
            self.session.add(instance)
        
        self.session.commit()
        return instances
    
    def commit(self):
        """Commit current transaction"""
        self.session.commit()
    
    def rollback(self):
        """Rollback current transaction"""
        self.session.rollback()