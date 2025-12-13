# migration_debug.py
import traceback,sys
print("migration_debug.py starting...")

try:
    from app import app, db
    from sqlalchemy import text
    print("Imported app and db OK")
except Exception:
    print("IMPORT ERROR")
    traceback.print_exc()
    sys.exit(1)

try:
    with app.app_context():
        print("Entered app.app_context()")
        with db.engine.connect() as conn:
            print("Connected to engine")
            try:
                conn.execute(text("ALTER TABLE 'order' ADD COLUMN razorpay_order_id VARCHAR(120)"))
                print("[OK] added razorpay_order_id")
            except Exception as e:
                print("[SKIP/ERR] add razorpay_order_id ->", repr(e))
            try:
                conn.execute(text("ALTER TABLE 'order' ADD COLUMN razorpay_signature VARCHAR(300)"))
                print("[OK] added razorpay_signature")
            except Exception as e:
                print("[SKIP/ERR] add razorpay_signature ->", repr(e))

            rows = conn.execute(text("PRAGMA table_info('order')")).fetchall()
            cols = [r[1] for r in rows]
            print("Final columns in 'order':", cols)
except Exception:
    print("TOP-LEVEL ERROR")
    traceback.print_exc()

print("migration_debug.py finished.")
