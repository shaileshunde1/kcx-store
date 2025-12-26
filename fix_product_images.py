from app import app, db
from models import Product  # adjust if Product is in a different file

with app.app_context():
    products = Product.query.all()

    for p in products:
        if p.image_url:
            # normalize slashes
            clean = p.image_url.replace("\\", "/")

            # extract filename only
            filename = clean.split("/")[-1]

            # force products/ path
            p.image_url = f"products/{filename}"

    db.session.commit()
    print("Product image paths normalized successfully.")
