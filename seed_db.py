from app import app, db, Product

if __name__ == "__main__":
    with app.app_context():
        print("Creating tables if not exist...")
        db.create_all()

       
        Product.query.delete()
        db.session.commit()
        print("Old products cleared.")

        
        p1 = Product(
            name="Octopus Keychain",
            price=150,
            description="Your beloved buddy wherever life takes you.",
            image_url="products/octopus.jpg",
            is_bestseller=False
        )

        p2 = Product(
            name="Crochet Paw",
            price=150,
            description="Carry a little purr-fection wherever you go!",
            image_url="products/paw.jpg",
            is_bestseller=True
        )

        p3 = Product(
            name="Batman Keychain",
            price=150,
            description="Carry a bit of Gotham’s charm everywhere.",
            image_url="products/batman.jpg",
            is_bestseller=False
        )

        p4 = Product(
            name="Teddy Bear",
            price=350,
            description="Tiny hugs, big heart — your perfect pocket-sized friend.",
            image_url="products/teddy.jpg",
            is_bestseller=True
        )

        p5 = Product(
            name="Beige Sweatshirt",
            price=699,
            description="Cozy classic, made to love.",
            image_url="products/beige.jpg",
            is_bestseller=True
        )

        p6 = Product(
            name="Blue Sweatshirt",
            price=699,
            description="Pure comfort, wrapped in timeless blue.",
            image_url="products/blue.jpg",
            is_bestseller=False
        )

        p7 = Product(
            name="Bunny Keychain",
            price=200,
            description="Your adorable pocket-sized hop of joy.",
            image_url="products/bunny.jpg",
            is_bestseller=False
        )

        p8 = Product(
            name="Spiderman Couple Keychain",
            price=300,
            description="Two hearts linked by every web spun.",
            image_url="products/spidy.jpg",
            is_bestseller=True
        )

        p9 = Product(
            name="Heart Bookmark",
            price=150,
            description="A little heart to hold your story.",
            image_url="products/heart.jpg",
            is_bestseller=False
        )

        p10 = Product(
            name="Beanie",
            price=300,
            description="Snug softness, crafted with care.",
            image_url="products/beanie.jpg",
            is_bestseller=True
        )

        # ⬆️ Add more products like p5, p6, etc. if you want

        db.session.add_all([p1, p2, p3, p4,p5,p6,p7,p8,p9,p10])
        db.session.commit()

        print("New products added!")
        print("Products in DB:", Product.query.all())
