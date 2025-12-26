from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        conn.execute(text('ALTER TABLE product_image ADD COLUMN order_index INTEGER DEFAULT 0'))
        conn.commit()
        print("✅ Column added successfully!")