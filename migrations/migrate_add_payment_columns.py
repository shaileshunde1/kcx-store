# migrate_add_payment_columns.py
from app import db, app
from sqlalchemy import text

with app.app_context():
    conn = db.engine
    try:
        conn.execute(text("ALTER TABLE 'order' ADD COLUMN payment_status VARCHAR(30) DEFAULT 'Unpaid'"))
        print("payment_status added")
    except Exception as e:
        print("payment_status probably exists or failed:", e)

    try:
        conn.execute(text("ALTER TABLE 'order' ADD COLUMN razorpay_order_id VARCHAR(120)"))
        print("razorpay_order_id added")
    except Exception as e:
        print("razorpay_order_id probably exists or failed:", e)

    try:
        conn.execute(text("ALTER TABLE 'order' ADD COLUMN razorpay_payment_id VARCHAR(120)"))
        print("razorpay_payment_id added")
    except Exception as e:
        print("razorpay_payment_id probably exists or failed:", e)

    try:
        conn.execute(text("ALTER TABLE 'order' ADD COLUMN razorpay_signature VARCHAR(300)"))
        print("razorpay_signature added")
    except Exception as e:
        print("razorpay_signature probably exists or failed:", e)

    print("Migration script finished.")
