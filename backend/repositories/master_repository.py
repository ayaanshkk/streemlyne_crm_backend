"""
Master Data Repository
Handles master data tables (Country, Currency, UOM, etc.)
These tables are NOT tenant-scoped
"""

from models import (
    CountryMaster, CurrencyMaster, DesignationMaster,
    ServicesMaster, UOMMaster, StageMaster, SupplierMaster
)
from .base_repository import BaseRepository
from typing import List, Optional


class MasterRepository:
    """
    Repository for master data tables
    These tables don't have tenant_id - they're shared across all tenants
    """
    
    def __init__(self):
        from database import db
        self.session = db.session
    
    # ============================================================
    # COUNTRY MASTER
    # ============================================================
    
    def get_all_countries(self) -> List[CountryMaster]:
        """Get all countries"""
        return self.session.query(CountryMaster).order_by(CountryMaster.country_name).all()
    
    def get_country_by_id(self, country_id: int) -> Optional[CountryMaster]:
        """Get country by ID"""
        return self.session.query(CountryMaster).get(country_id)
    
    def get_country_by_name(self, country_name: str) -> Optional[CountryMaster]:
        """Get country by name"""
        return self.session.query(CountryMaster).filter(
            CountryMaster.country_name == country_name
        ).first()
    
    def create_country(self, country_name: str, country_isd_code: str = None) -> CountryMaster:
        """Create a new country"""
        country = CountryMaster(
            country_name=country_name,
            country_isd_code=country_isd_code
        )
        self.session.add(country)
        self.session.commit()
        return country
    
    # ============================================================
    # CURRENCY MASTER
    # ============================================================
    
    def get_all_currencies(self) -> List[CurrencyMaster]:
        """Get all currencies"""
        return self.session.query(CurrencyMaster).order_by(CurrencyMaster.currency_name).all()
    
    def get_currency_by_id(self, currency_id: int) -> Optional[CurrencyMaster]:
        """Get currency by ID"""
        return self.session.query(CurrencyMaster).get(currency_id)
    
    def get_currency_by_code(self, currency_code: str) -> Optional[CurrencyMaster]:
        """Get currency by code (USD, GBP, etc.)"""
        return self.session.query(CurrencyMaster).filter(
            CurrencyMaster.currency_code == currency_code
        ).first()
    
    def create_currency(self, currency_name: str, currency_code: str) -> CurrencyMaster:
        """Create a new currency"""
        currency = CurrencyMaster(
            currency_name=currency_name,
            currency_code=currency_code
        )
        self.session.add(currency)
        self.session.commit()
        return currency
    
    # ============================================================
    # DESIGNATION MASTER
    # ============================================================
    
    def get_all_designations(self) -> List[DesignationMaster]:
        """Get all designations"""
        return self.session.query(DesignationMaster).order_by(
            DesignationMaster.designation_description
        ).all()
    
    def get_designation_by_id(self, designation_id: int) -> Optional[DesignationMaster]:
        """Get designation by ID"""
        return self.session.query(DesignationMaster).get(designation_id)
    
    def create_designation(self, designation_description: str) -> DesignationMaster:
        """Create a new designation"""
        designation = DesignationMaster(
            designation_description=designation_description
        )
        self.session.add(designation)
        self.session.commit()
        return designation
    
    # ============================================================
    # UOM MASTER
    # ============================================================
    
    def get_all_uoms(self) -> List[UOMMaster]:
        """Get all units of measurement"""
        return self.session.query(UOMMaster).order_by(UOMMaster.uom_description).all()
    
    def get_uom_by_id(self, uom_id: int) -> Optional[UOMMaster]:
        """Get UOM by ID"""
        return self.session.query(UOMMaster).get(uom_id)
    
    def create_uom(self, uom_description: str) -> UOMMaster:
        """Create a new UOM"""
        uom = UOMMaster(uom_description=uom_description)
        self.session.add(uom)
        self.session.commit()
        return uom
    
    # ============================================================
    # STAGE MASTER
    # ============================================================
    
    def get_all_stages(self) -> List[StageMaster]:
        """Get all stages"""
        return self.session.query(StageMaster).all()
    
    def get_stage_by_id(self, stage_id: int) -> Optional[StageMaster]:
        """Get stage by ID"""
        return self.session.query(StageMaster).get(stage_id)
    
    def create_stage(self, stage_name: str, stage_description: str = None,
                    preceding_stage_id: int = None, stage_type: int = None) -> StageMaster:
        """Create a new stage"""
        stage = StageMaster(
            stage_name=stage_name,
            stage_description=stage_description,
            preceding_stage_id=preceding_stage_id,
            stage_type=stage_type
        )
        self.session.add(stage)
        self.session.commit()
        return stage
    
    # ============================================================
    # SUPPLIER MASTER
    # ============================================================
    
    def get_all_suppliers(self) -> List[SupplierMaster]:
        """Get all suppliers"""
        return self.session.query(SupplierMaster).order_by(
            SupplierMaster.supplier_company_name
        ).all()
    
    def get_supplier_by_id(self, supplier_id: int) -> Optional[SupplierMaster]:
        """Get supplier by ID"""
        return self.session.query(SupplierMaster).get(supplier_id)
    
    def create_supplier(self, supplier_company_name: str,
                       supplier_contact_name: str = None,
                       supplier_provisions: int = None) -> SupplierMaster:
        """Create a new supplier"""
        supplier = SupplierMaster(
            supplier_company_name=supplier_company_name,
            supplier_contact_name=supplier_contact_name,
            supplier_provisions=supplier_provisions
        )
        self.session.add(supplier)
        self.session.commit()
        return supplier