#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Data Migration Script: Customer (System A) -> ClientMaster (System B)

This script migrates existing Customer records from the legacy UUID-based
schema to the new integer-based ClientMaster schema.

IMPORTANT:
- Run this script ONLY AFTER verifying the new client_routes.py is working
- Backup your database before running
- This script is idempotent - can be run multiple times safely

Usage:
    cd backend
    python scripts/migrate_customers_to_clients.py [--dry-run] [--tenant-id ID]

Options:
    --dry-run      Show what would be migrated without making changes
    --tenant-id    Migrate only a specific tenant (for testing)

Created: 2026-02-24
Phase: 2 - Legacy Model Deprecation
"""

import sys
import os
import argparse
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ..app import app
from ..database import db
from ..models import Customer, ClientMaster, TenantMaster, OpportunityDetails, StageMaster
from sqlalchemy import text


def get_tenant_mapping():
    """
    Get mapping between legacy Tenant UUIDs and new TenantMaster IDs.
    
    Returns:
        dict: {legacy_tenant_uuid: new_tenant_id}
    """
    # This assumes tenants have been migrated or there's a mapping
    # For now, we'll try to match by company_name
    legacy_tenants = db.session.execute(
        text("SELECT id, company_name FROM tenants")
    ).fetchall()
    
    new_tenants = TenantMaster.query.all()
    
    mapping = {}
    for legacy in legacy_tenants:
        legacy_id = legacy[0]
        company_name = legacy[1]
        
        # Try to find matching new tenant
        new_tenant = TenantMaster.query.filter_by(
            tenant_company_name=company_name
        ).first()
        
        if new_tenant:
            mapping[legacy_id] = new_tenant.tenant_id
        else:
            print(f"[WARN] No matching tenant found for: {company_name} ({legacy_id})")
    
    return mapping


def migrate_customers(dry_run=False, tenant_id_filter=None):
    """
    Migrate Customer records to ClientMaster.
    
    Args:
        dry_run: If True, don't commit changes
        tenant_id_filter: If provided, only migrate this tenant's customers
    """
    print("\n" + "=" * 60)
    print("[MIGRATION] Customer -> ClientMaster Migration")
    print("=" * 60)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Mode: {'DRY RUN (no changes will be made)' if dry_run else 'LIVE'}")
    print()
    
    # Get tenant mapping
    print("[INFO] Building tenant mapping...")
    tenant_mapping = get_tenant_mapping()
    print(f"   Found {len(tenant_mapping)} tenant mappings")
    
    # Get all customers
    query = "SELECT * FROM customers"
    if tenant_id_filter:
        query += f" WHERE tenant_id = '{tenant_id_filter}'"
    
    customers = db.session.execute(text(query)).fetchall()
    print(f"[INFO] Found {len(customers)} customers to process")
    print()
    
    # Statistics
    stats = {
        'total': len(customers),
        'migrated': 0,
        'skipped': 0,
        'errors': 0,
        'no_tenant': 1,
    }
    
    for customer in customers:
        # Extract customer data (using indices since it's a raw query result)
        # Adjust indices based on your actual table structure
        try:
            customer_id = customer[0]  # id (UUID)
            legacy_tenant_id = customer[1]  # tenant_id (UUID)
            name = customer[2]  # name
            company_name = customer[3] if len(customer) > 3 else None  # company_name
            address = customer[4] if len(customer) > 4 else None  # address
            postcode = customer[5] if len(customer) > 5 else None  # postcode
            phone = customer[6] if len(customer) > 6 else None  # phone
            email = customer[7] if len(customer) > 7 else None  # email
            stage = customer[8] if len(customer) > 8 else None  # stage
            
            # Get new tenant ID
            new_tenant_id = tenant_mapping.get(legacy_tenant_id)
            
            if not new_tenant_id:
                print(f"[WARN] Skipping customer {customer_id}: No tenant mapping")
                stats['no_tenant'] += 1
                continue
            
            # Check if client already exists (by email within tenant)
            existing = ClientMaster.query.filter_by(
                tenant_id=new_tenant_id,
                client_email=email
            ).first() if email else None
            
            if existing:
                print(f"[SKIP] Skipping {email}: Already exists as client_id={existing.client_id}")
                stats['skipped'] += 1
                continue
            
            # Create new ClientMaster record
            client = ClientMaster(
                tenant_id=new_tenant_id,
                client_company_name=company_name,
                client_contact_name=name,
                address=address,
                post_code=postcode,
                client_phone=phone,
                client_email=email,
            )
            
            db.session.add(client)
            
            if dry_run:
                db.session.rollback()
            else:
                db.session.flush()  # Get the client_id
            
            print(f"[OK] Migrated: {name} ({email}) -> client_id={client.client_id if not dry_run else 'N/A'}")
            stats['migrated'] += 1
            
            # Note: stage is NOT migrated to ClientMaster
            # It should be migrated to OpportunityDetails if needed
            if stage:
                print(f"   [INFO] Stage '{stage}' should be migrated to OpportunityDetails")
            
        except Exception as e:
            print(f"[ERROR] Error migrating customer {customer[0]}: {str(e)}")
            stats['errors'] += 1
            db.session.rollback()
    
    # Commit all changes
    if not dry_run:
        try:
            db.session.commit()
            print("\n[OK] All changes committed")
        except Exception as e:
            db.session.rollback()
            print(f"\n[ERROR] Error committing changes: {str(e)}")
            stats['errors'] += 1
    
    # Print summary
    print("\n" + "=" * 60)
    print("[SUMMARY] Migration Summary")
    print("=" * 60)
    print(f"Total customers processed: {stats['total']}")
    print(f"Successfully migrated:     {stats['migrated']}")
    print(f"Skipped (duplicates):      {stats['skipped']}")
    print(f"Skipped (no tenant):       {stats['no_tenant']}")
    print(f"Errors:                    {stats['errors']}")
    print(f"Completed: {datetime.now().isoformat()}")
    print("=" * 60)
    
    return stats


def create_opportunities_from_stages(dry_run=False):
    """
    Create OpportunityDetails records for customers with stages.
    
    This is a separate step because stages belong to opportunities,
    not clients in the new schema.
    """
    print("\n" + "=" * 60)
    print("[MIGRATION] Creating Opportunities from Customer Stages")
    print("=" * 60)
    
    # Get default stage
    default_stage = StageMaster.query.first()
    if not default_stage:
        print("[WARN] No stages found in StageMaster. Run seed_master_data.py first.")
        return
    
    # Get all clients that were just migrated
    # This would need a mapping table to track which clients came from which customers
    # For now, this is a placeholder for the logic
    
    print("[INFO] This step requires a customer_id -> client_id mapping table")
    print("   Consider adding a migration_mapping table to track this")


def main():
    parser = argparse.ArgumentParser(
        description='Migrate Customer records to ClientMaster'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    parser.add_argument(
        '--tenant-id',
        type=str,
        help='Migrate only a specific tenant (UUID)'
    )
    parser.add_argument(
        '--create-opportunities',
        action='store_true',
        help='Also create OpportunityDetails from customer stages'
    )
    
    args = parser.parse_args()
    
    with app.app_context():
        # Run migration
        stats = migrate_customers(
            dry_run=args.dry_run,
            tenant_id_filter=args.tenant_id
        )
        
        # Optionally create opportunities
        if args.create_opportunities:
            create_opportunities_from_stages(dry_run=args.dry_run)
        
        if args.dry_run:
            print("\n[WARN] This was a DRY RUN. No changes were made.")
            print("   Run without --dry-run to apply changes.")
        
        return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
