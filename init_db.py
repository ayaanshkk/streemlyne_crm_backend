# File: /backend/init_db.py

# Assuming your main Flask app instance is in 'app.py'
from app import app 
from database import db 
from models import Customer, Opportunity, CustomerFormData # Corrected 'Job' to 'Opportunity'

def init_database():
    """Initialize the database with all tables"""
    
    # Check if the database has been initialized with the app yet
    if not app.extensions.get('sqlalchemy'):
        db.init_app(app)

    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("Database tables created successfully!")
            
            # Optional: Create some test data
            if Customer.query.count() == 0:
                test_customer = Customer(
                    name="Test Customer",
                    address="123 Test Street",
                    phone="01234567890",
                    email="test@example.com",
                    status="Active"
                )
                db.session.add(test_customer)
                db.session.commit()
                print("Test customer created!")
                
        except Exception as e:
            print(f"Error initializing database: {e}")
            # Ensure rollback is called on the session
            db.session.rollback()

if __name__ == "__main__":
    init_database()