"""
Master Data Models for StreemLyne CRM
Reference/lookup tables for system-wide data

DEVELOPER: Dev A
CREATED: Day 1

THEORY:
-------
Master data = Reference data that is:
1. Relatively static (doesn't change often)
2. Shared across all tenants (not tenant-specific, except ServicesMaster)
3. Used for dropdowns, lookups, validation

Examples:
- Country list (rarely changes)
- Currency codes (USD, GBP, EUR - standardized)
- Units of measurement (kg, hours, days - standard)

CONTRAST WITH TRANSACTIONAL DATA:
----------------------------------
Master Data (this file):
- Countries, currencies, UOMs
- Changes rarely
- Seeded once during system setup

Transactional Data (other files):
- Clients, projects, invoices
- Changes constantly
- Created by users during normal operation

WHY SEPARATE TABLES FOR MASTER DATA?
-------------------------------------
Instead of storing country names directly in Client_Master:

❌ BAD:
Client 1: country = "United States"
Client 2: country = "USA"
Client 3: country = "U.S.A."
→ Same country, three different spellings!

✅ GOOD:
Country_Master: {id: 1, name: "United States"}
Client 1: country_id = 1
Client 2: country_id = 1
Client 3: country_id = 1
→ Consistent, normalized, easy to query
"""

from database import db
from datetime import datetime


class CountryMaster(db.Model):
    """
    Country reference data
    
    PURPOSE:
    --------
    - Standardize country names across system
    - Store ISD codes for phone number formatting
    - Used in: ClientMaster, shipping addresses, etc.
    
    DATA SOURCE:
    ------------
    Populated from ISO 3166 country list
    ~195 countries total
    
    EXAMPLE DATA:
    -------------
    country_id: 1
    country_name: "United States"
    country_isd_code: "+1"
    
    country_id: 44
    country_name: "United Kingdom"
    country_isd_code: "+44"
    
    USAGE IN CODE:
    --------------
    # Get all countries for dropdown
    countries = CountryMaster.query.order_by(CountryMaster.country_name).all()
    
    # Get country by ID
    country = CountryMaster.query.get(1)
    
    # Get country by name
    country = CountryMaster.query.filter_by(country_name="United States").first()
    """
    __tablename__ = 'country_master'
    
    country_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    country_name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    country_isd_code = db.Column(db.String(10))  # International dialing code
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Country {self.country_name}>'
    
    def to_dict(self):
        return {
            'country_id': self.country_id,
            'country_name': self.country_name,
            'country_isd_code': self.country_isd_code,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class CurrencyMaster(db.Model):
    """
    Currency reference data
    
    PURPOSE:
    --------
    - Standardize currency handling
    - Store ISO currency codes
    - Used for: invoices, proposals, pricing
    
    DATA SOURCE:
    ------------
    ISO 4217 currency codes
    ~170 active currencies
    
    EXAMPLE DATA:
    -------------
    currency_id: 1
    currency_name: "US Dollar"
    currency_code: "USD"
    
    currency_id: 2
    currency_name: "British Pound Sterling"
    currency_code: "GBP"
    
    currency_id: 3
    currency_name: "Euro"
    currency_code: "EUR"
    
    BUSINESS RULES:
    ---------------
    - currency_code is 3-letter ISO code (always uppercase)
    - currency_code is unique
    - Each client has a default_currency_id
    - Each invoice/proposal specifies currency_id
    
    USAGE IN CODE:
    --------------
    # Get currency for display
    currency = CurrencyMaster.query.get(invoice.currency_id)
    total_formatted = f"{currency.currency_code} {invoice.total_amount}"
    # Output: "USD 1,234.56"
    
    # Get all active currencies for dropdown
    currencies = CurrencyMaster.query.order_by(CurrencyMaster.currency_code).all()
    """
    __tablename__ = 'currency_master'
    
    currency_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    currency_name = db.Column(db.String(100), nullable=False)
    currency_code = db.Column(db.String(3), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=False), default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Currency {self.currency_code}>'
    
    def to_dict(self):
        return {
            'currency_id': self.currency_id,
            'currency_name': self.currency_name,
            'currency_code': self.currency_code,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def format_amount(self, amount):
        """
        Format amount with currency code
        
        Parameters:
        -----------
        amount : float
            The amount to format
        
        Returns:
        --------
        str : Formatted string like "USD 1,234.56"
        
        Usage:
        ------
        currency = CurrencyMaster.query.get(1)  # USD
        formatted = currency.format_amount(1234.56)
        # Returns: "USD 1,234.56"
        """
        return f"{self.currency_code} {amount:,.2f}"


class DesignationMaster(db.Model):
    """
    Employee designation/job titles
    
    PURPOSE:
    --------
    - Standardize job titles across organization
    - Used in EmployeeMaster
    - Helps with reporting (how many "Sales Managers" do we have?)
    
    EXAMPLE DATA:
    -------------
    designation_id: 1
    designation_description: "Managing Director"
    
    designation_id: 2
    designation_description: "Sales Manager"
    
    designation_id: 3
    designation_description: "Sales Representative"
    
    designation_id: 4
    designation_description: "Project Manager"
    
    BUSINESS RULES:
    ---------------
    - Designation names should be title case
    - Each designation is unique
    - Employees can only have ONE designation at a time
    
    USAGE IN CODE:
    --------------
    # Get all designations for dropdown
    designations = DesignationMaster.query.order_by(
        DesignationMaster.designation_description
    ).all()
    
    # Create new designation (admin function)
    new_designation = DesignationMaster(
        designation_description="Junior Developer"
    )
    db.session.add(new_designation)
    db.session.commit()
    """
    __tablename__ = 'designation_master'
    
    designation_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    designation_description = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Designation {self.designation_description}>'
    
    def to_dict(self):
        return {
            'designation_id': self.designation_id,
            'designation_description': self.designation_description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ServicesMaster(db.Model):
    """
    Services/Products catalog
    
    PURPOSE:
    --------
    - Define what services/products we offer
    - Used in: Proposals, Invoices, Energy Contracts
    - Tenant-scoped (each tenant has their own services)
    
    IMPORTANT:
    ----------
    This is the ONLY master table that is TENANT-SPECIFIC!
    
    Why? Because each tenant might offer different services:
    - Tenant "Acme Solar": Solar panel installation, Maintenance
    - Tenant "Beta Energy": Energy audit, Consulting
    
    EXAMPLE DATA:
    -------------
    service_id: 1
    tenant_id: 1
    service_code: "SOLAR-INSTALL"
    service_title: "Solar Panel Installation"
    service_description: "Complete solar panel installation service"
    service_rate: 5000.00
    currency_id: 1  # USD
    supplier_id: NULL
    date_from: 2025-01-01
    date_to: NULL  # Active indefinitely
    
    service_id: 2
    tenant_id: 1
    service_code: "MAINT-ANNUAL"
    service_title: "Annual Maintenance Contract"
    service_rate: 1200.00
    currency_id: 1
    
    BUSINESS RULES:
    ---------------
    - service_code should be unique within tenant (not enforced at DB level)
    - service_rate is the default/base rate (can be overridden in proposals)
    - date_from/date_to control when service is available
    - If supplier_id is set, this is a supplier-provided service
    
    TIME-BASED PRICING:
    -------------------
    You can have multiple services with same title but different rates
    for different time periods:
    
    service_id: 10
    service_title: "Solar Panel Installation"
    service_rate: 5000.00
    date_from: 2024-01-01
    date_to: 2024-12-31
    
    service_id: 11
    service_title: "Solar Panel Installation"
    service_rate: 5500.00  # Price increase!
    date_from: 2025-01-01
    date_to: NULL
    
    USAGE IN CODE:
    --------------
    # Get active services for current tenant
    today = datetime.now().date()
    services = ServicesMaster.query.filter_by(
        tenant_id=current_tenant_id
    ).filter(
        (ServicesMaster.date_from == None) | (ServicesMaster.date_from <= today),
        (ServicesMaster.date_to == None) | (ServicesMaster.date_to >= today)
    ).all()
    
    # Get service by code
    service = ServicesMaster.query.filter_by(
        tenant_id=current_tenant_id,
        service_code="SOLAR-INSTALL"
    ).first()
    """
    __tablename__ = 'services_master'
    
    service_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    
    # Tenant isolation
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('tenant_master.tenant_id'), 
                         nullable=False, index=True)
    
    # Service identification
    service_code = db.Column(db.String(50), index=True)
    service_title = db.Column(db.String(255), nullable=False)
    service_description = db.Column(db.Text)
    
    # Pricing
    service_rate = db.Column(db.Float)
    currency_id = db.Column(db.SmallInteger, db.ForeignKey('currency_master.currency_id'))
    
    # Optional supplier link (if service is outsourced)
    supplier_id = db.Column(db.SmallInteger, db.ForeignKey('supplier_master.supplier_id'))
    
    # Validity period
    date_from = db.Column(db.Date)
    date_to = db.Column(db.Date)
    
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    currency = db.relationship('CurrencyMaster', backref='services')
    supplier = db.relationship('SupplierMaster', backref='services')
    
    # Indexes for common queries
    __table_args__ = (
        db.Index('idx_service_tenant_active', 'tenant_id', 'date_from', 'date_to'),
        db.Index('idx_service_code_tenant', 'service_code', 'tenant_id'),
    )
    
    def __repr__(self):
        return f'<Service {self.service_code}: {self.service_title}>'
    
    def to_dict(self):
        return {
            'service_id': self.service_id,
            'tenant_id': self.tenant_id,
            'service_code': self.service_code,
            'service_title': self.service_title,
            'service_description': self.service_description,
            'service_rate': self.service_rate,
            'currency_id': self.currency_id,
            'currency_code': self.currency.currency_code if self.currency else None,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.supplier_company_name if self.supplier else None,
            'date_from': self.date_from.isoformat() if self.date_from else None,
            'date_to': self.date_to.isoformat() if self.date_to else None,
            'is_active': self.is_active(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def is_active(self, check_date=None):
        """
        Check if service is currently active based on dates
        
        Parameters:
        -----------
        check_date : date, optional
            Date to check against. If None, uses today.
        
        Returns:
        --------
        bool : True if service is active on check_date
        
        Business Logic:
        ---------------
        Service is active if:
        - date_from is None OR check_date >= date_from
        AND
        - date_to is None OR check_date <= date_to
        
        Usage:
        ------
        if service.is_active():
            # Can be added to new proposals
        else:
            # Historical service, can't use for new proposals
        
        # Check if service was active on specific date
        was_active = service.is_active(date(2024, 6, 15))
        """
        if check_date is None:
            check_date = datetime.now().date()
        
        # Check start date
        if self.date_from and check_date < self.date_from:
            return False
        
        # Check end date
        if self.date_to and check_date > self.date_to:
            return False
        
        return True
    
    def get_rate_on_date(self, check_date=None):
        """
        Get the applicable rate for this service on a given date
        
        Parameters:
        -----------
        check_date : date, optional
            Date to get rate for. If None, uses today.
        
        Returns:
        --------
        float : The service rate if active, None if not active
        
        Usage:
        ------
        # Get current rate
        rate = service.get_rate_on_date()
        
        # Get historical rate
        old_rate = service.get_rate_on_date(date(2023, 1, 1))
        """
        if self.is_active(check_date):
            return self.service_rate
        return None


class UOMMaster(db.Model):
    """
    Unit of Measurement reference data
    
    PURPOSE:
    --------
    - Standardize units across system
    - Used in: Proposals, Invoices (quantity + UOM)
    - Ensures consistency in billing
    
    EXAMPLE DATA:
    -------------
    uom_id: 1
    uom_description: "Each"
    
    uom_id: 2
    uom_description: "Hour"
    
    uom_id: 3
    uom_description: "Day"
    
    uom_id: 4
    uom_description: "Kilogram"
    
    uom_id: 5
    uom_description: "Square Meter"
    
    uom_id: 6
    uom_description: "Linear Meter"
    
    BUSINESS CONTEXT:
    -----------------
    Proposal line item might be:
    - Service: "Solar Panel Installation"
    - Quantity: 20
    - UOM: "Each"
    - Rate: $500 per Each
    - Total: $10,000
    
    Or:
    - Service: "Consulting"
    - Quantity: 40
    - UOM: "Hour"
    - Rate: $150 per Hour
    - Total: $6,000
    
    USAGE IN CODE:
    --------------
    # Get all UOMs for dropdown
    uoms = UOMMaster.query.order_by(UOMMaster.uom_description).all()
    
    # Format quantity with UOM
    uom = UOMMaster.query.get(proposal_detail.uom_id)
    formatted = f"{proposal_detail.quantity} {uom.uom_description}"
    # Output: "20 Each" or "40 Hours"
    """
    __tablename__ = 'uom_master'
    
    uom_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    uom_description = db.Column(db.String(50), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    def __repr__(self):
        return f'<UOM {self.uom_description}>'
    
    def to_dict(self):
        return {
            'uom_id': self.uom_id,
            'uom_description': self.uom_description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class StageMaster(db.Model):
    """
    Workflow stages for opportunities/projects
    
    PURPOSE:
    --------
    - Define stages in sales/project workflow
    - Track progression (preceding_stage_id creates a chain)
    - Different types for different processes
    
    STAGE TYPES:
    ------------
    stage_type: 1 = Opportunity stages
    stage_type: 2 = Project stages
    stage_type: 3 = General/Other
    
    EXAMPLE DATA FOR OPPORTUNITIES:
    --------------------------------
    stage_id: 1
    stage_name: "Lead"
    stage_description: "Initial inquiry received"
    preceding_stage_id: NULL  # First stage
    stage_type: 1  # Opportunity
    
    stage_id: 2
    stage_name: "Qualified"
    stage_description: "Lead has been qualified"
    preceding_stage_id: 1  # Comes after "Lead"
    stage_type: 1
    
    stage_id: 3
    stage_name: "Proposal Sent"
    stage_description: "Proposal has been sent to client"
    preceding_stage_id: 2  # Comes after "Qualified"
    stage_type: 1
    
    stage_id: 4
    stage_name: "Negotiation"
    stage_description: "In negotiation with client"
    preceding_stage_id: 3
    stage_type: 1
    
    stage_id: 5
    stage_name: "Won"
    stage_description: "Opportunity converted to project"
    preceding_stage_id: 4
    stage_type: 1
    
    stage_id: 6
    stage_name: "Lost"
    stage_description: "Opportunity lost to competitor or cancelled"
    preceding_stage_id: 4  # Can go from Negotiation to Lost
    stage_type: 1
    
    BUSINESS RULES:
    ---------------
    - Stages form a workflow (preceding_stage_id creates links)
    - Opportunities should progress through stages in order
    - Can have multiple "terminal" stages (Won, Lost)
    - Each stage type has its own workflow
    
    USAGE IN CODE:
    --------------
    # Get all opportunity stages in order
    stages = StageMaster.query.filter_by(
        stage_type=1  # Opportunity
    ).order_by(StageMaster.stage_id).all()
    
    # Get next possible stages
    current_stage = opportunity.stage_id
    next_stages = StageMaster.query.filter_by(
        preceding_stage_id=current_stage
    ).all()
    
    # Validate stage progression
    def can_move_to_stage(opportunity, new_stage_id):
        new_stage = StageMaster.query.get(new_stage_id)
        return new_stage.preceding_stage_id == opportunity.stage_id
    """
    __tablename__ = 'stage_master'
    
    stage_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    stage_name = db.Column(db.String(100), nullable=False)
    stage_description = db.Column(db.Text)
    
    # Self-referential foreign key for workflow
    preceding_stage_id = db.Column(db.SmallInteger, db.ForeignKey('stage_master.stage_id'))
    
    # Stage type categorization
    stage_type = db.Column(db.SmallInteger)  # 1=Opportunity, 2=Project, 3=General
    
    # Self-referential relationship
    next_stages = db.relationship('StageMaster', 
                                 backref=db.backref('preceding_stage', remote_side=[stage_id]))
    
    def __repr__(self):
        return f'<Stage {self.stage_name}>'
    
    def to_dict(self):
        return {
            'stage_id': self.stage_id,
            'stage_name': self.stage_name,
            'stage_description': self.stage_description,
            'preceding_stage_id': self.preceding_stage_id,
            'stage_type': self.stage_type,
            'stage_type_name': self.get_stage_type_name(),
            'next_stage_ids': [s.stage_id for s in self.next_stages]
        }
    
    def get_stage_type_name(self):
        """Get human-readable stage type"""
        types = {
            1: 'Opportunity',
            2: 'Project',
            3: 'General'
        }
        return types.get(self.stage_type, 'Unknown')
    
    def get_next_stages(self):
        """
        Get all stages that can follow this stage
        
        Returns:
        --------
        list of StageMaster : Possible next stages
        
        Usage:
        ------
        current_stage = StageMaster.query.get(opportunity.stage_id)
        next_options = current_stage.get_next_stages()
        
        # Show dropdown of next stages to user
        for stage in next_options:
            print(f"Can move to: {stage.stage_name}")
        """
        return self.next_stages


class SupplierMaster(db.Model):
    """
    Supplier/vendor information
    
    PURPOSE:
    --------
    - Track external suppliers/vendors
    - Used in: Energy contracts, Services (outsourced)
    - Not tenant-specific (suppliers can serve multiple tenants)
    
    EXAMPLE DATA:
    -------------
    supplier_id: 1
    supplier_company_name: "British Gas"
    supplier_contact_name: "John Smith"
    supplier_provisions: 1  # Energy supplier
    
    supplier_id: 2
    supplier_company_name: "Panel Pro Ltd"
    supplier_contact_name: "Jane Doe"
    supplier_provisions: 2  # Equipment supplier
    
    SUPPLIER PROVISIONS (TYPES):
    -----------------------------
    This field categorizes what the supplier provides:
    1 = Energy (gas, electricity)
    2 = Equipment (solar panels, hardware)
    3 = Services (installation, maintenance)
    4 = Other
    
    BUSINESS CONTEXT:
    -----------------
    Energy contracts link to suppliers:
    - Contract with "British Gas" for client
    - Contract tracks: rates, terms, MPAN numbers
    
    Services can reference suppliers:
    - Service "Solar Panel Installation"
    - Uses panels from supplier "Panel Pro Ltd"
    
    USAGE IN CODE:
    --------------
    # Get all energy suppliers
    energy_suppliers = SupplierMaster.query.filter_by(
        supplier_provisions=1
    ).order_by(SupplierMaster.supplier_company_name).all()
    
    # Get supplier details
    supplier = SupplierMaster.query.get(contract.supplier_id)
    """
    __tablename__ = 'supplier_master'
    
    supplier_id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    supplier_company_name = db.Column(db.String(255), nullable=False, index=True)
    supplier_contact_name = db.Column(db.String(255))
    supplier_provisions = db.Column(db.SmallInteger)  # Type of supplier
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Supplier {self.supplier_company_name}>'
    
    def to_dict(self):
        return {
            'supplier_id': self.supplier_id,
            'supplier_company_name': self.supplier_company_name,
            'supplier_contact_name': self.supplier_contact_name,
            'supplier_provisions': self.supplier_provisions,
            'supplier_provisions_name': self.get_provisions_name(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def get_provisions_name(self):
        """Get human-readable supplier type"""
        provisions = {
            1: 'Energy Supplier',
            2: 'Equipment Supplier',
            3: 'Service Provider',
            4: 'Other'
        }
        return provisions.get(self.supplier_provisions, 'Unknown')