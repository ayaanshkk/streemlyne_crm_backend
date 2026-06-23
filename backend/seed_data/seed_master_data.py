"""
Seed Master Data
Populates master tables with initial data
Run this ONCE after migration
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from models import (
    CountryMaster, CurrencyMaster, DesignationMaster,
    UOMMaster, StageMaster
)


def seed_countries():
    """Seed country master data"""
    countries = [
        {'country_name': 'United States', 'country_isd_code': '+1'},
        {'country_name': 'United Kingdom', 'country_isd_code': '+44'},
        {'country_name': 'Canada', 'country_isd_code': '+1'},
        {'country_name': 'Australia', 'country_isd_code': '+61'},
        {'country_name': 'India', 'country_isd_code': '+91'},
        {'country_name': 'Germany', 'country_isd_code': '+49'},
        {'country_name': 'France', 'country_isd_code': '+33'},
        {'country_name': 'United Arab Emirates', 'country_isd_code': '+971'},
        {'country_name': 'Singapore', 'country_isd_code': '+65'},
        {'country_name': 'Japan', 'country_isd_code': '+81'},
    ]
    
    for country_data in countries:
        existing = CountryMaster.query.filter_by(
            country_name=country_data['country_name']
        ).first()
        
        if not existing:
            country = CountryMaster(**country_data)
            db.session.add(country)
            print(f"✓ Added country: {country_data['country_name']}")
    
    db.session.commit()
    print("✓ Countries seeded successfully")


def seed_currencies():
    """Seed currency master data"""
    currencies = [
        {'currency_name': 'US Dollar', 'currency_code': 'USD'},
        {'currency_name': 'British Pound', 'currency_code': 'GBP'},
        {'currency_name': 'Euro', 'currency_code': 'EUR'},
        {'currency_name': 'Canadian Dollar', 'currency_code': 'CAD'},
        {'currency_name': 'Australian Dollar', 'currency_code': 'AUD'},
        {'currency_name': 'Indian Rupee', 'currency_code': 'INR'},
        {'currency_name': 'UAE Dirham', 'currency_code': 'AED'},
        {'currency_name': 'Singapore Dollar', 'currency_code': 'SGD'},
        {'currency_name': 'Japanese Yen', 'currency_code': 'JPY'},
    ]
    
    for currency_data in currencies:
        existing = CurrencyMaster.query.filter_by(
            currency_code=currency_data['currency_code']
        ).first()
        
        if not existing:
            currency = CurrencyMaster(**currency_data)
            db.session.add(currency)
            print(f"✓ Added currency: {currency_data['currency_name']}")
    
    db.session.commit()
    print("✓ Currencies seeded successfully")


def seed_designations():
    """Seed designation master data"""
    designations = [
        'CEO',
        'Managing Director',
        'Director',
        'Manager',
        'Senior Manager',
        'Team Lead',
        'Senior Executive',
        'Executive',
        'Sales Manager',
        'Sales Executive',
        'Account Manager',
        'Project Manager',
        'Technical Lead',
        'Developer',
        'Intern'
    ]
    
    for designation_desc in designations:
        existing = DesignationMaster.query.filter_by(
            designation_description=designation_desc
        ).first()
        
        if not existing:
            designation = DesignationMaster(designation_description=designation_desc)
            db.session.add(designation)
            print(f"✓ Added designation: {designation_desc}")
    
    db.session.commit()
    print("✓ Designations seeded successfully")


def seed_uoms():
    """Seed UOM (Unit of Measurement) master data"""
    uoms = [
        'Each',
        'Piece',
        'Unit',
        'Hour',
        'Day',
        'Week',
        'Month',
        'Year',
        'Kilogram',
        'Gram',
        'Liter',
        'Milliliter',
        'Meter',
        'Centimeter',
        'Square Meter',
        'Cubic Meter',
        'Box',
        'Carton',
        'Pack'
    ]
    
    for uom_desc in uoms:
        existing = UOMMaster.query.filter_by(uom_description=uom_desc).first()
        
        if not existing:
            uom = UOMMaster(uom_description=uom_desc)
            db.session.add(uom)
            print(f"✓ Added UOM: {uom_desc}")
    
    db.session.commit()
    print("✓ UOMs seeded successfully")


def seed_stages():
    """Seed stage master data"""
    stages = [
        {'stage_name': 'Prospect', 'stage_description': 'Initial contact', 'stage_type': 1},
        {'stage_name': 'Qualified', 'stage_description': 'Qualified lead', 'stage_type': 1},
        {'stage_name': 'Meeting Scheduled', 'stage_description': 'Meeting arranged', 'stage_type': 1},
        {'stage_name': 'Proposal Sent', 'stage_description': 'Proposal submitted', 'stage_type': 1},
        {'stage_name': 'Negotiation', 'stage_description': 'In negotiation', 'stage_type': 1},
        {'stage_name': 'Closed Won', 'stage_description': 'Deal won', 'stage_type': 1},
        {'stage_name': 'Closed Lost', 'stage_description': 'Deal lost', 'stage_type': 1},
    ]
    
    for stage_data in stages:
        existing = StageMaster.query.filter_by(
            stage_name=stage_data['stage_name']
        ).first()
        
        if not existing:
            stage = StageMaster(**stage_data)
            db.session.add(stage)
            print(f"✓ Added stage: {stage_data['stage_name']}")
    
    db.session.commit()
    print("✓ Stages seeded successfully")


def seed_master_data():
    """Main function to seed all master data"""
    print("\n" + "="*50)
    print("SEEDING MASTER DATA")
    print("="*50 + "\n")
    
    try:
        seed_countries()
        seed_currencies()
        seed_designations()
        seed_uoms()
        seed_stages()
        
        print("\n" + "="*50)
        print("✓ ALL MASTER DATA SEEDED SUCCESSFULLY")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"\n✗ Error seeding master data: {e}")
        db.session.rollback()
        raise


if __name__ == '__main__':
    # Import app to get database context
    from app import app
    
    with app.app_context():
        seed_master_data()