# C:\streemlyne_crm_backend\backend\models\core.py
"""
Core Business Models for StreemLyne CRM
Handles clients, opportunities, projects, employees, and users

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


# ============================================================
# CLIENT MASTER
# ============================================================

class ClientMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Client_Master"""
    __tablename__ = 'Client_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    client_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    country_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Country_Master.country_id'))
    default_currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    client_company_name = db.Column(db.String(255), nullable=False)
    client_contact_name = db.Column(db.String(255))
    address = db.Column(db.String(500))
    post_code = db.Column(db.String(20))
    client_phone = db.Column(db.String(50))
    client_email = db.Column(db.String(255))
    client_website = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', back_populates='clients')
    country = db.relationship('CountryMaster', backref='clients')
    default_currency = db.relationship('CurrencyMaster', backref='default_currency_clients')
    opportunities = db.relationship('OpportunityDetails', back_populates='client', lazy='dynamic')
    projects = db.relationship('ClientInteractions', back_populates='client', lazy='dynamic')
    proposals = db.relationship('ProposalMaster', back_populates='client', lazy='dynamic')
    invoices = db.relationship('InvoiceMaster', back_populates='client', lazy='dynamic')
    customer_auths = db.relationship('CustomerAuth', back_populates='client', lazy='dynamic')
    case_documents = db.relationship('CaseDocuments', back_populates='client', lazy='dynamic')
    customer_documents = db.relationship('CustomerDocuments', back_populates='client', lazy='dynamic')

    def __repr__(self):
        return f'<ClientMaster {self.client_id}: {self.client_company_name}>'

    def to_dict(self):
        return {
            'client_id': self.client_id,
            'tenant_id': self.tenant_id,
            'client_company_name': self.client_company_name,
            'client_contact_name': self.client_contact_name,
            'address': self.address,
            'country_id': self.country_id,
            'country_name': self.country.country_name if self.country else None,
            'post_code': self.post_code,
            'client_phone': self.client_phone,
            'client_email': self.client_email,
            'client_website': self.client_website,
            'default_currency_id': self.default_currency_id,
            'default_currency_code': self.default_currency.currency_code if self.default_currency else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# CLIENT INTERACTIONS
# ============================================================

class ClientInteractions(db.Model):
    """SCHEMA: StreemLyne_MT.Client_Interactions"""
    __tablename__ = 'Client_Interactions'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    interaction_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    contact_date = db.Column(db.Date, nullable=False)
    contact_method = db.Column(db.SmallInteger, nullable=False)  # 1=Phone, 2=Email, 3=In-person, 4=Other
    notes = db.Column(db.String(1000))
    next_steps = db.Column(db.String(500))
    reminder_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='interactions')

    def __repr__(self):
        return f'<ClientInteractions {self.interaction_id} for Client {self.client_id}>'

    def to_dict(self):
        return {
            'interaction_id': self.interaction_id,
            'client_id': self.client_id,
            'contact_date': self.contact_date.isoformat() if self.contact_date else None,
            'contact_method': self.contact_method,
            'contact_method_name': self.get_contact_method_name(),
            'notes': self.notes,
            'next_steps': self.next_steps,
            'reminder_date': self.reminder_date.isoformat() if self.reminder_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def get_contact_method_name(self):
        return {1: 'Phone', 2: 'Email', 3: 'In-person', 4: 'Other'}.get(self.contact_method, 'Unknown')


# ============================================================
# EMPLOYEE MASTER
# ============================================================

class EmployeeMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Employee_Master"""
    __tablename__ = 'Employee_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    employee_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    employee_designation_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Designation_Master.designation_id'))
    employee_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(255), unique=True)
    date_of_birth = db.Column(db.Date)
    date_of_joining = db.Column(db.Date)
    id_type = db.Column(db.String(50))
    id_number = db.Column(db.String(100))
    role_ids = db.Column(db.String(255))  # Comma-separated role IDs
    commission_percentage = db.Column(db.Float(precision=24))
    created_on = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_on = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', back_populates='employees')
    designation = db.relationship('DesignationMaster', backref='employees')
    owned_opportunities = db.relationship(
        'OpportunityDetails',
        foreign_keys='OpportunityDetails.opportunity_owner_employee_id',
        back_populates='opportunity_owner'
    )
    assigned_opportunities = db.relationship(
        'OpportunityDetails',
        foreign_keys='OpportunityDetails.assigned_to_employee_id',
        back_populates='assigned_employee'
    )
    managed_projects = db.relationship('ProjectDetails', back_populates='employee')
    energy_contracts = db.relationship('EnergyContractMaster', back_populates='employee')
    user = db.relationship('UserMaster', back_populates='employee', uselist=False)

    def __repr__(self):
        return f'<EmployeeMaster {self.employee_id}: {self.employee_name}>'

    def get_roles(self) -> list:
        """Get list of role IDs from the comma-separated role_ids field"""
        if not self.role_ids:
            return []
        try:
            return [int(rid.strip()) for rid in self.role_ids.split(',') if rid.strip()]
        except (ValueError, AttributeError):
            return []
    
    def add_role(self, role_id: int) -> None:
        """Add a role ID to the comma-separated role_ids field"""
        current_roles = self.get_roles()
        if role_id not in current_roles:
            current_roles.append(role_id)
            self.role_ids = ','.join(map(str, current_roles))
    
    def remove_role(self, role_id: int) -> None:
        """Remove a role ID from the comma-separated role_ids field"""
        current_roles = self.get_roles()
        if role_id in current_roles:
            current_roles.remove(role_id)
            self.role_ids = ','.join(map(str, current_roles)) if current_roles else None
    
    def to_dict(self):
        return {
            'employee_id': self.employee_id,
            'tenant_id': self.tenant_id,
            'employee_name': self.employee_name,
            'employee_designation_id': self.employee_designation_id,
            'designation_name': self.designation.designation_description if self.designation else None,
            'phone': self.phone,
            'email': self.email,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'date_of_joining': self.date_of_joining.isoformat() if self.date_of_joining else None,
            'id_type': self.id_type,
            'id_number': self.id_number,
            'role_ids': self.role_ids,
            'commission_percentage': self.commission_percentage,
            'created_on': self.created_on.isoformat() if self.created_on else None,
            'updated_on': self.updated_on.isoformat() if self.updated_on else None
        }


# ============================================================
# USER MASTER
# ============================================================

class UserMaster(db.Model):
    """SCHEMA: StreemLyne_MT.User_Master"""
    __tablename__ = 'User_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    user_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    user_name = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.Date, onupdate=datetime.utcnow)

    employee = db.relationship('EmployeeMaster', back_populates='user')
    roles = db.relationship('RoleMaster', secondary='StreemLyne_MT.User_Role_Mapping', backref='users')

    def __repr__(self):
        return f'<UserMaster {self.user_id}: {self.user_name}>'

    def set_password(self, password: str) -> None:
        self.password = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password, password)

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'employee_id': self.employee_id,
            'user_name': self.user_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ============================================================
# USER ROLE MAPPING
# ============================================================

class UserRoleMapping(db.Model):
    """SCHEMA: StreemLyne_MT.User_Role_Mapping"""
    __tablename__ = 'User_Role_Mapping'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    user_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Role_Master.role_id'), primary_key=True)

    def __repr__(self):
        return f'<UserRoleMapping User:{self.user_id} Role:{self.role_id}>'


# ============================================================
# CUSTOMER AUTH
# ============================================================

class CustomerAuth(db.Model):
    """SCHEMA: StreemLyne_MT.Customer_Auth"""
    __tablename__ = 'Customer_Auth'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    customer_user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='customer_auths')
    password_resets = db.relationship('CustomerPasswordReset', back_populates='customer_user', lazy='dynamic')

    def __repr__(self):
        return f'<CustomerAuth {self.email}>'

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'customer_user_id': self.customer_user_id,
            'client_id': self.client_id,
            'tenant_id': self.tenant_id,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class CustomerPasswordReset(db.Model):
    """SCHEMA: StreemLyne_MT.Customer_Password_Reset"""
    __tablename__ = 'Customer_Password_Reset'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_user_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Customer_Auth.customer_user_id'))
    token = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=False), nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    customer_user = db.relationship('CustomerAuth', back_populates='password_resets')

    def __repr__(self):
        return f'<CustomerPasswordReset {self.id} for User:{self.customer_user_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'customer_user_id': self.customer_user_id,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'used': self.used,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# OPPORTUNITY DETAILS
# ============================================================

class OpportunityDetails(db.Model):
    """SCHEMA: StreemLyne_MT.Opportunity_Details"""
    __tablename__ = 'Opportunity_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    opportunity_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    opportunity_owner_employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    assigned_to_employee_id = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    stage_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Stage_Master.stage_id'), nullable=False)
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'))
    service_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'))
    opportunity_title = db.Column(db.String(255), nullable=False)
    opportunity_description = db.Column(db.Text)
    opportunity_date = db.Column(db.Date)
    opportunity_value = db.Column(db.SmallInteger)
    mpan_mpr = db.Column(db.String(50))
    business_name = db.Column(db.String(255))
    contact_person = db.Column(db.String(255))
    tel_number = db.Column(db.String(50))
    email = db.Column(db.String(255))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    Misc_Col1 = db.Column(db.String(255))
    deleted_at = db.Column(db.DateTime(timezone=False))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='opportunities')
    opportunity_owner = db.relationship(
        'EmployeeMaster',
        foreign_keys=[opportunity_owner_employee_id],
        back_populates='owned_opportunities'
    )
    assigned_employee = db.relationship(
        'EmployeeMaster',
        foreign_keys=[assigned_to_employee_id],
        back_populates='assigned_opportunities'
    )
    stage = db.relationship('StageMaster', back_populates='opportunities')
    currency = db.relationship('CurrencyMaster', backref='opportunities')
    service = db.relationship('ServicesMaster', backref='opportunities')
    projects = db.relationship('ProjectDetails', back_populates='opportunity', lazy='dynamic')
    case_documents = db.relationship('CaseDocuments', back_populates='opportunity', lazy='dynamic')
    customer_documents = db.relationship('CustomerDocuments', back_populates='opportunity', lazy='dynamic')

    def __repr__(self):
        return f'<OpportunityDetails {self.opportunity_id}: {self.opportunity_title}>'

    def to_dict(self):
        return {
            'opportunity_id': self.opportunity_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'opportunity_title': self.opportunity_title,
            'opportunity_description': self.opportunity_description,
            'opportunity_date': self.opportunity_date.isoformat() if self.opportunity_date else None,
            'opportunity_owner_employee_id': self.opportunity_owner_employee_id,
            'opportunity_owner_name': self.opportunity_owner.employee_name if self.opportunity_owner else None,
            'assigned_to_employee_id': self.assigned_to_employee_id,
            'assigned_employee_name': self.assigned_employee.employee_name if self.assigned_employee else None,
            'stage_id': self.stage_id,
            'stage_name': self.stage.stage_name if self.stage else None,
            'opportunity_value': self.opportunity_value,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'tenant_id': self.tenant_id,
            'service_id': self.service_id,
            'mpan_mpr': self.mpan_mpr,
            'business_name': self.business_name,
            'contact_person': self.contact_person,
            'tel_number': self.tel_number,
            'email': self.email,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'Misc_Col1': self.Misc_Col1,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# PROJECT DETAILS
# ============================================================

class ProjectDetails(db.Model):
    """SCHEMA: StreemLyne_MT.Project_Details"""
    __tablename__ = 'Project_Details'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    project_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    client_id = db.Column(db.SmallInteger, nullable=False)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)
    project_title = db.Column(db.String(255), nullable=False)
    project_description = db.Column(db.Text)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    address = db.Column(db.String(500))
    Misc_Col1 = db.Column(db.String(255))
    Misc_Col2 = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=False), onupdate=datetime.utcnow)

    opportunity = db.relationship('OpportunityDetails', back_populates='projects')
    employee = db.relationship('EmployeeMaster', back_populates='managed_projects')
    energy_contracts = db.relationship('EnergyContractMaster', back_populates='project', lazy='dynamic')
    invoices = db.relationship('InvoiceMaster', back_populates='project', lazy='dynamic')

    def __repr__(self):
        return f'<ProjectDetails {self.project_id}: {self.project_title}>'

    def to_dict(self):
        return {
            'project_id': self.project_id,
            'client_id': self.client_id,
            'opportunity_id': self.opportunity_id,
            'opportunity_title': self.opportunity.opportunity_title if self.opportunity else None,
            'employee_id': self.employee_id,
            'employee_name': self.employee.employee_name if self.employee else None,
            'project_title': self.project_title,
            'project_description': self.project_description,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'address': self.address,
            'Misc_Col1': self.Misc_Col1,
            'Misc_Col2': self.Misc_Col2,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ============================================================
# CASE DOCUMENTS
# ============================================================

class CaseDocuments(db.Model):
    """SCHEMA: StreemLyne_MT.Case_Documents"""
    __tablename__ = 'Case_Documents'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    uploaded_by = db.Column(db.String(255), nullable=False)
    document_type = db.Column(db.String(100))
    file_name = db.Column(db.String(255), nullable=False)
    blob_url = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    opportunity = db.relationship('OpportunityDetails', back_populates='case_documents')
    client = db.relationship('ClientMaster', back_populates='case_documents')

    def __repr__(self):
        return f'<CaseDocuments {self.id}: {self.file_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'opportunity_id': self.opportunity_id,
            'client_id': self.client_id,
            'tenant_id': self.tenant_id,
            'uploaded_by': self.uploaded_by,
            'document_type': self.document_type,
            'file_name': self.file_name,
            'blob_url': self.blob_url,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# CUSTOMER DOCUMENTS
# ============================================================

class CustomerDocuments(db.Model):
    """SCHEMA: StreemLyne_MT.Customer_Documents"""
    __tablename__ = 'Customer_Documents'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'))
    file_url = db.Column(db.Text, nullable=False)
    file_name = db.Column(db.Text, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)

    client = db.relationship('ClientMaster', back_populates='customer_documents')
    opportunity = db.relationship('OpportunityDetails', back_populates='customer_documents')

    def __repr__(self):
        return f'<CustomerDocuments {self.id}: {self.file_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'client_id': self.client_id,
            'opportunity_id': self.opportunity_id,
            'file_url': self.file_url,
            'file_name': self.file_name,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None
        }


# ============================================================
# ENERGY CONTRACT MASTER
# ============================================================

class EnergyContractMaster(db.Model):
    """SCHEMA: StreemLyne_MT.Energy_Contract_Master"""
    __tablename__ = 'Energy_Contract_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    energy_contract_master_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    project_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'))
    employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)
    supplier_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Supplier_Master.supplier_id'), nullable=False)
    service_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Services_Master.service_id'), nullable=False)
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Currency_Master.currency_id'))
    contract_start_date = db.Column(db.Date, nullable=False)
    contract_end_date = db.Column(db.Date, nullable=False)
    terms_of_sale = db.Column(db.String(500), nullable=False)
    unit_rate = db.Column(db.Float(precision=24), nullable=False)
    document_details = db.Column(db.String(500))
    mpan_number = db.Column(db.String(50))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=datetime.utcnow)

    project = db.relationship('ProjectDetails', back_populates='energy_contracts')
    employee = db.relationship('EmployeeMaster', back_populates='energy_contracts')
    supplier = db.relationship('SupplierMaster', backref='energy_contracts')
    service = db.relationship('ServicesMaster', backref='energy_contracts')
    currency = db.relationship('CurrencyMaster', backref='energy_contracts')

    def __repr__(self):
        return f'<EnergyContractMaster {self.energy_contract_master_id}>'

    def to_dict(self):
        return {
            'energy_contract_master_id': self.energy_contract_master_id,
            'project_id': self.project_id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.employee_name if self.employee else None,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.supplier_company_name if self.supplier else None,
            'service_id': self.service_id,
            'service_title': self.service.service_title if self.service else None,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'contract_start_date': self.contract_start_date.isoformat() if self.contract_start_date else None,
            'contract_end_date': self.contract_end_date.isoformat() if self.contract_end_date else None,
            'terms_of_sale': self.terms_of_sale,
            'unit_rate': self.unit_rate,
            'document_details': self.document_details,
            'mpan_number': self.mpan_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }