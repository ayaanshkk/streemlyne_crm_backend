# inspect_supabase_tables.py
"""
Check what tables actually exist in Supabase
Run this to see the current state
"""

from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv
import os

load_dotenv()

db_url = os.getenv('DATABASE_URL')
engine = create_engine(db_url)

print("=" * 70)
print("📊 SUPABASE DATABASE INSPECTION")
print("=" * 70)

# Get all tables
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT 
            table_name,
            (SELECT COUNT(*) 
             FROM information_schema.columns 
             WHERE table_name = t.table_name) as column_count
        FROM information_schema.tables t
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """))
    
    tables = result.fetchall()
    
    print(f"\n✅ Found {len(tables)} tables in database:\n")
    
    new_schema_tables = []
    old_schema_tables = []
    other_tables = []
    
    for table_name, col_count in tables:
        display = f"  • {table_name} ({col_count} columns)"
        
        # Categorize tables
        if table_name.endswith('_Master') or table_name.endswith('_Details') or \
           table_name.endswith('_Mapping') or table_name.endswith('_Plans') or \
           table_name.endswith('_Catalog'):
            new_schema_tables.append((table_name, col_count))
        elif table_name in ['customers', 'tenants', 'users', 'opportunities', 
                           'jobs', 'teams', 'assignments']:
            old_schema_tables.append((table_name, col_count))
        else:
            other_tables.append((table_name, col_count))

print("\n" + "=" * 70)
print("🆕 NEW SCHEMA TABLES (your 27 tables)")
print("=" * 70)
if new_schema_tables:
    for table_name, col_count in new_schema_tables:
        print(f"  ✅ {table_name} ({col_count} columns)")
else:
    print("  ⚠️  None found - tables don't exist yet!")

print("\n" + "=" * 70)
print("📦 OLD SCHEMA TABLES (existing system)")
print("=" * 70)
if old_schema_tables:
    for table_name, col_count in old_schema_tables:
        print(f"  ✅ {table_name} ({col_count} columns)")
else:
    print("  ℹ️  None found")

print("\n" + "=" * 70)
print("🔧 OTHER TABLES")
print("=" * 70)
if other_tables:
    for table_name, col_count in other_tables:
        print(f"  • {table_name} ({col_count} columns)")

# Check specific tables mentioned in error
print("\n" + "=" * 70)
print("🔍 CHECKING TABLES FROM ERROR MESSAGE")
print("=" * 70)

tables_to_check = ['Client_Master', 'Client_Interactions', 'Tenant_Master']

for table_name in tables_to_check:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = :table_name
            )
        """), {"table_name": table_name})
        
        exists = result.fetchone()[0]
        
        if exists:
            # Get columns
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = :table_name
                ORDER BY ordinal_position
            """), {"table_name": table_name})
            
            columns = result.fetchall()
            print(f"\n✅ {table_name} EXISTS ({len(columns)} columns):")
            for col_name, data_type, nullable in columns:
                null_str = "NULL" if nullable == "YES" else "NOT NULL"
                print(f"     • {col_name}: {data_type} {null_str}")
        else:
            print(f"\n❌ {table_name} DOES NOT EXIST")

# Check foreign key constraints
print("\n" + "=" * 70)
print("🔗 FOREIGN KEY CONSTRAINTS")
print("=" * 70)

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name,
            tc.constraint_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = 'public'
            AND (tc.table_name LIKE '%_Master' 
                 OR tc.table_name LIKE '%_Details'
                 OR tc.table_name = 'Client_Interactions')
        ORDER BY tc.table_name, kcu.column_name;
    """))
    
    fks = result.fetchall()
    
    if fks:
        print(f"\nFound {len(fks)} foreign keys in new schema tables:\n")
        for table, col, ref_table, ref_col, constraint in fks:
            print(f"  • {table}.{col} → {ref_table}.{ref_col}")
    else:
        print("\n⚠️  No foreign keys found in new schema tables")

print("\n" + "=" * 70)
print("✅ INSPECTION COMPLETE")
print("=" * 70)