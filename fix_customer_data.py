"""
Database cleanup script to fix empty string values in preferred_contact_method column.
This script will update all customers with empty strings to NULL values.
"""

# Run this script from your backend directory where your Flask app is

from app import app  # Import your Flask app
from database import db  # Import your database instance
from models import Customer  # Import Customer model

def fix_customer_data():
    """Fix empty string values in preferred_contact_method"""
    with app.app_context():
        try:
            # Find all customers with empty string in preferred_contact_method
            # We need to use raw SQL since SQLAlchemy can't query the broken data
            result = db.session.execute(
                db.text("UPDATE customers SET preferred_contact_method = NULL WHERE preferred_contact_method = ''")
            )
            db.session.commit()
            
            print(f"✅ Successfully updated {result.rowcount} customers")
            print("The preferred_contact_method field has been set to NULL for customers with empty strings.")
            
            # Verify the fix
            customers_count = db.session.execute(
                db.text("SELECT COUNT(*) FROM customers WHERE preferred_contact_method IS NULL")
            ).scalar()
            
            print(f"📊 Total customers with NULL preferred_contact_method: {customers_count}")
            
        except Exception as e:
            print(f"❌ Error updating customers: {e}")
            db.session.rollback()

if __name__ == "__main__":
    print("🔧 Starting database cleanup...")
    print("This will fix the preferred_contact_method field for all customers.\n")
    fix_customer_data()
    print("\n✨ Database cleanup complete!")
    print("You can now restart your Flask app and the error should be gone.")
