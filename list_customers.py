from database import SessionLocal
from models import Customer

def list_customer_ids():
    db = SessionLocal()
    try:
        customers = db.query(Customer).all()
        customer_ids = [c.id for c in customers]
        print(f"Current Customer IDs in DB: {customer_ids}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    list_customer_ids()