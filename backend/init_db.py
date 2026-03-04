# init_db.py - StreemLyne_MT database initialiser
from app import app
from database import db
from models import ClientMaster, OpportunityDetails, CustomerFormData


def init_database():
    """
    Create all StreemLyne_MT tables and optionally seed a test client record.
    
    Note: CustomerFormData is kept as-is — verify it still exists in models.py.
    If it was also renamed, update the import above accordingly.
    """
    if not app.extensions.get("sqlalchemy"):
        db.init_app(app)

    with app.app_context():
        try:
            db.create_all()
            print("✅ Database tables created successfully.")

            # ── Optional: seed a test client ─────────────────────────────
            # ClientMaster requires tenant_id (FK → Tenant_Master).
            # Adjust tenant_id=1 to match a real seeded tenant, or skip
            # this block entirely and rely on setup_auth.py for seeding.
            if ClientMaster.query.count() == 0:
                test_client = ClientMaster(
                    tenant_id=1,                          # must exist in Tenant_Master
                    client_company_name="Test Company Ltd",
                    client_contact_name="Test Contact",
                    client_phone="01234567890",
                    client_email="test@example.com",
                )
                db.session.add(test_client)
                db.session.commit()
                print("✅ Seeded test client record.")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Error initialising database: {e}")
            raise


if __name__ == "__main__":
    init_database()