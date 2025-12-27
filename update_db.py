from app import app, db, Product
from datetime import datetime

with app.app_context():
    # Add the new column
    with db.engine.connect() as conn:
        try:
            conn.execute(db.text('ALTER TABLE product ADD COLUMN new_launch_date DATETIME'))
            conn.commit()
            print("✓ Column added successfully!")
        except Exception as e:
            print(f"Column might already exist: {e}")
    
    # Set current date for existing new launches
    products = Product.query.filter_by(is_new_launch=True).all()
    for p in products:
        if not p.new_launch_date:
            p.new_launch_date = datetime.utcnow()
    db.commit()
    print(f"✓ Updated {len(products)} existing new launch products")