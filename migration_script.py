from database import db
from models import Customer

# Update all customers with empty string to None
customers = Customer.query.filter(
    (Customer.preferred_contact_method == '') | 
    (Customer.preferred_contact_method == None)
).all()

for customer in customers:
    customer.preferred_contact_method = None

db.session.commit()
print(f"Updated {len(customers)} customers")