# setup_auth.py - Setup authentication system for StreemLyne_MT
from app import app
from database import db
from models import TenantMaster, EmployeeMaster, UserMaster
from werkzeug.security import generate_password_hash
from datetime import datetime


def setup_authentication():
    """
    Seed demo accounts for StreemLyne_MT.

    Schema hierarchy:
        TenantMaster  →  EmployeeMaster  →  UserMaster
    
    UserMaster has no name/email/role fields — those live on EmployeeMaster.
    Passwords are stored as hashes on UserMaster.password (varchar).
    """
    with app.app_context():
        print("Setting up Authentication System...")
        db.create_all()

        # ------------------------------------------------------------------
        # 1. Ensure a demo tenant exists
        # ------------------------------------------------------------------
        tenant = TenantMaster.query.filter_by(
            tenant_company_name="Aztec Interiors"
        ).first()

        if not tenant:
            tenant = TenantMaster(
                tenant_company_name="Aztec Interiors",
                tenant_contact_name="Admin User",
                onboarding_Date=datetime.utcnow().date(),
                is_active=True,
            )
            db.session.add(tenant)
            db.session.flush()  # Populate tenant_id before FK references
            print(f"✅ Created tenant: Aztec Interiors (id={tenant.tenant_id})")
        else:
            print(f"ℹ️  Tenant already exists (id={tenant.tenant_id})")

        # ------------------------------------------------------------------
        # 2. Demo accounts
        #    Each entry creates one EmployeeMaster row + one UserMaster row.
        #    role_ids is stored as a comma-separated string on EmployeeMaster
        #    (e.g. "1" = admin, "2" = manager, "3" = user — adjust to your
        #    Role_Master seed data).
        # ------------------------------------------------------------------
        demo_accounts = [
            {
                "employee_name": "Admin User",
                "email": "admin@aztecinteriors.com",
                "phone": None,
                "role_ids": "1",          # admin role_id in Role_Master
                "user_name": "admin",
                "plain_password": "Admin123!",
            },
            {
                "employee_name": "Demo User",
                "email": "demo@aztecinteriors.com",
                "phone": None,
                "role_ids": "3",          # standard user
                "user_name": "demo",
                "plain_password": "Demo123!",
            },
            {
                "employee_name": "Sarah Johnson",
                "email": "manager@aztecinteriors.com",
                "phone": "01234567891",
                "role_ids": "2",          # manager
                "user_name": "sarah.johnson",
                "plain_password": "Password123!",
            },
            {
                "employee_name": "Mike Wilson",
                "email": "designer@aztecinteriors.com",
                "phone": "01234567892",
                "role_ids": "3",
                "user_name": "mike.wilson",
                "plain_password": "Password123!",
            },
            {
                "employee_name": "Dave Matthews",
                "email": "installer@aztecinteriors.com",
                "phone": "01234567893",
                "role_ids": "3",
                "user_name": "dave.matthews",
                "plain_password": "Password123!",
            },
        ]

        for account in demo_accounts:
            # Check by email on EmployeeMaster (email is UNIQUE there)
            employee = EmployeeMaster.query.filter_by(
                email=account["email"]
            ).first()

            if not employee:
                employee = EmployeeMaster(
                    tenant_id=tenant.tenant_id,
                    employee_name=account["employee_name"],
                    email=account["email"],
                    phone=account["phone"],
                    role_ids=account["role_ids"],
                )
                db.session.add(employee)
                db.session.flush()  # Populate employee_id before FK reference
                print(f"✅ Created employee: {account['email']}")
            else:
                print(f"ℹ️  Employee already exists: {account['email']}")

            # Check by user_name on UserMaster (user_name is UNIQUE there)
            user = UserMaster.query.filter_by(
                user_name=account["user_name"]
            ).first()

            if not user:
                user = UserMaster(
                    employee_id=employee.employee_id,
                    user_name=account["user_name"],
                    password=generate_password_hash(account["plain_password"]),
                )
                db.session.add(user)
                print(f"✅ Created user login: {account['user_name']}")
            else:
                print(f"ℹ️  User login already exists: {account['user_name']}")

        db.session.commit()

        # ------------------------------------------------------------------
        # 3. Summary
        # ------------------------------------------------------------------
        print("\n" + "=" * 50)
        print("🔐 AUTHENTICATION SETUP COMPLETED")
        print("=" * 50)
        print("\nDemo Accounts:")
        print("  admin@aztecinteriors.com   / Admin123!    (role: admin)")
        print("  demo@aztecinteriors.com    / Demo123!     (role: user)")
        print("  manager@aztecinteriors.com / Password123! (role: manager)")
        print("  designer@aztecinteriors.com/ Password123! (role: user)")
        print("  installer@aztecinteriors.com/Password123! (role: user)")
        print(f"\nTotal employees: {EmployeeMaster.query.count()}")
        print(f"Total user logins: {UserMaster.query.count()}")
        print("\nNext Steps:")
        print("  1. Verify Role_Master is seeded with role_ids 1/2/3")
        print("  2. Add JWT_SECRET_KEY to your environment variables")
        print("  3. Register the auth blueprint in app.py")


if __name__ == "__main__":
    setup_authentication()