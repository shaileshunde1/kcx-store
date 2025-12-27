# Run this in Python terminal or create a script fix_products.py
from app import app, db, Product

with app.app_context():
    fixed = 0
    no_images = 0
    
    for p in Product.query.all():
        if not p.image_url or p.image_url == '':
            if p.images and len(p.images) > 0:
                p.image_url = p.images[0].image_url
                fixed += 1
                print(f"✓ Fixed product {p.id}: {p.name}")
            else:
                no_images += 1
                print(f"✗ Product {p.id} has NO images: {p.name}")
    
    db.session.commit()
    print(f"\n✓ Fixed {fixed} products")
    print(f"✗ {no_images} products still have no images (need manual upload)")