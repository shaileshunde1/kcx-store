# Run this ONCE to update your database
from app import app, db
from app import Product, ProductImage, ProductVariant, VariantImage, OrderItem

with app.app_context():
    # Add new columns to existing tables
    with db.engine.connect() as conn:
        try:
            conn.execute(db.text("ALTER TABLE product ADD COLUMN main_image_id INTEGER"))
            print("✓ Added main_image_id to product")
        except:
            print("→ main_image_id already exists")
        
        try:
            conn.execute(db.text("ALTER TABLE product_image ADD COLUMN display_order INTEGER DEFAULT 0"))
            print("✓ Added display_order to product_image")
        except:
            print("→ display_order already exists")
        
        try:
            conn.execute(db.text("ALTER TABLE order_item ADD COLUMN selected_size VARCHAR(50)"))
            conn.execute(db.text("ALTER TABLE order_item ADD COLUMN selected_color VARCHAR(50)"))
            conn.execute(db.text("ALTER TABLE order_item ADD COLUMN wrap_type VARCHAR(50)"))
            conn.execute(db.text("ALTER TABLE order_item ADD COLUMN wrap_price INTEGER DEFAULT 0"))
            print("✓ Added variant and wrap columns to order_item")
        except:
            print("→ order_item columns already exist")
        
        conn.commit()
    
    # Create new tables
    db.create_all()
    print("✓ Created ProductVariant and VariantImage tables")
    
    print("\n✅ Database migration completed!")