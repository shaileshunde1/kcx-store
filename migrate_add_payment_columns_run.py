# migrate_add_payment_columns_run.py
# Run: python migrate_add_payment_columns_run.py

from app import app, db
from sqlalchemy import text

print("Starting migration script...")

with app.app_context():
    # obtain a Connection object
    with db.engine.connect() as conn:
        def try_exec(sql, name):
            try:
                conn.execute(text(sql))
                print(f"[OK]   {name}")
            except Exception as e:
                print(f"[SKIP] {name} -> {e}")

        # Add missing columns (idempotent)
        try_exec("ALTER TABLE 'order' ADD COLUMN razorpay_order_id VARCHAR(120)", "add razorpay_order_id")
        try_exec("ALTER TABLE 'order' ADD COLUMN razorpay_signature VARCHAR(300)", "add razorpay_signature")

        # Show final columns
        rows = conn.execute(text("PRAGMA table_info('order')")).fetchall()
        cols = [r[1] for r in rows]
        print("Now columns in 'order':", cols)

print("Migration finished.")
