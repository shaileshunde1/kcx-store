from flask import Flask, render_template, session, redirect, url_for, request, make_response, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from twilio.rest import Client
import csv
import os
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv
import razorpay
import hmac, hashlib
import traceback
import json

load_dotenv(override=True)
from utils.image_utils import save_product_image


PAYMENT_CREATED = "CREATED"
PAYMENT_PAID = "PAID"
PAYMENT_FAILED = "FAILED"

load_dotenv()

app = Flask(__name__)
app.secret_key = "mysecret"

# --- Upload configuration ---
UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "products")



def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# razorpay config
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

def get_razorpay_client():
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Admin auth config
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# --- DATABASE SETUP ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "store.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

from flask_migrate import Migrate
migrate = Migrate(app, db)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<Category {self.name}>"

# ---- Twilio SMS Config (local dev only) ----
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")           
client = Client(account_sid, auth_token)


# --- MODELS ---
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(255))
    is_bestseller = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(50))
    
    # NEW FIELDS
    is_new_launch = db.Column(db.Boolean, default=False)
    new_launch_date = db.Column(db.DateTime, nullable=True)
    sale_price = db.Column(db.Integer, nullable=True)  # If set, product is on sale

    images = db.relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

def cleanup_old_new_launches():
    """Automatically remove 'New Launch' badge from products older than 7 days"""
    from datetime import timedelta
    
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    old_launches = Product.query.filter(
        Product.is_new_launch == True,
        Product.new_launch_date != None,
        Product.new_launch_date < seven_days_ago
    ).all()
    
    for product in old_launches:
        product.is_new_launch = False
        product.new_launch_date = None
    
    if old_launches:
        db.session.commit()
        print(f"✓ Removed 'New Launch' from {len(old_launches)} products")
    
    return len(old_launches)


class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_url = db.Column(db.String(255), nullable=False)
    order_index = db.Column(db.Integer, default=0)  # For image ordering

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id", ondelete="CASCADE"),
        nullable=False
    )

    product = db.relationship(
        "Product",
        back_populates="images"
    )

class ProductVariant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    variant_type = db.Column(db.String(20), nullable=False)  # 'color' or 'size'
    name = db.Column(db.String(50), nullable=False)  # 'Red', 'Large', etc.
    code = db.Column(db.String(20))  # Color hex code
    price_adjustment = db.Column(db.Integer, default=0)
    image_indices = db.Column(db.Text)  # JSON string of image indices
    
    product = db.relationship("Product", backref="variants")

class GiftWrap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey("order_item.id"), nullable=False)
    wrap_type = db.Column(db.String(50), nullable=False)  # 'jute', 'newspaper', etc.
    wrap_price = db.Column(db.Integer, nullable=False)
    
    order_item = db.relationship("OrderItem", backref="gift_wrap")

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))
    address = db.Column(db.Text, nullable=False)
    city = db.Column(db.String(80))
    pincode = db.Column(db.String(20))
    notes = db.Column(db.Text)
    total_amount = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(30), default="Pending")
    payment_status = db.Column(db.String(30), default="Unpaid")
    razorpay_order_id = db.Column(db.String(120), nullable=True)
    razorpay_payment_id = db.Column(db.String(120), nullable=True)
    razorpay_signature = db.Column(db.String(300), nullable=True)

    items = db.relationship("OrderItem", backref="order", lazy=True)

    def __repr__(self):
        return f"<Order #{self.id} {self.status} {self.payment_status}>"
    
class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    product_name = db.Column(db.String(120), nullable=False)
    unit_price = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    
    def __repr__(self):
        return f"<OrderItem {self.product_name} x{self.quantity}>"


# ------------ CART HELPERS ------------

def get_cart():
    """Return the cart dict from session, create if missing."""
    if "cart" not in session:
        session["cart"] = {}
    return session["cart"]

def build_cart():
    """Convert session cart (id -> qty) to list of products, total and count."""
    cart = session.get("cart", {})
    items = []
    total = 0
    count = 0

    for product_id, qty in cart.items():
        product = Product.query.get(int(product_id))
        if product:
            # Use sale price if available, otherwise regular price
            effective_price = product.sale_price if product.sale_price else product.price
            items.append({"product": product, "quantity": qty})
            total += effective_price * qty
            count += qty

    return items, total, count

@app.context_processor
def inject_cart():
    items, total, count = build_cart()
    open_flag = session.pop("open_cart", False)

    return dict(
        cart_items_global=items,
        cart_total_global=total,
        cart_count_global=count,
        cart_open_global=open_flag,
        categories_global=[c.name for c in Category.query.order_by(Category.order_index).all()]
    )


# ------------ ROUTES ------------

@app.route("/")
def home():
    cleanup_old_new_launches()
    bestsellers = Product.query.filter_by(is_bestseller=True).all()
    
    # Get products by category for home page
    category_products = {}
    for category in Category.query.order_by(Category.order_index).all():
        products = Product.query.filter_by(category=category.name).limit(4).all()
        if products:
            category_products[category.name] = products
    
    return render_template("home.html", products=bestsellers, category_products=category_products)


@app.route("/shop")
def shop():
    category = request.args.get('category')
    
    if category and Category.query.filter_by(name=category).first():
        products = Product.query.filter_by(category=category)\
            .order_by(Product.is_new_launch.desc(), Product.id.desc()).all()
    else:
        products = Product.query\
            .order_by(Product.is_new_launch.desc(), Product.id.desc()).all()
    
    return render_template("shop.html", products=products, selected_category=category)

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    
    # GET VARIANTS FROM DATABASE
    color_variants = ProductVariant.query.filter_by(
        product_id=product_id, 
        variant_type='color'
    ).all()
    
    size_variants = ProductVariant.query.filter_by(
        product_id=product_id, 
        variant_type='size'
    ).all()
    
    # Convert to JSON-friendly format
    import json
    colors_data = []
    for cv in color_variants:
        colors_data.append({
            'id': cv.id,
            'name': cv.name,
            'code': cv.code,
            'priceAdj': cv.price_adjustment,
            'images': json.loads(cv.image_indices) if cv.image_indices else []
        })
    
    sizes_data = []
    for sv in size_variants:
        sizes_data.append({
            'id': sv.id,
            'name': sv.name,
            'priceAdj': sv.price_adjustment,
            'images': json.loads(sv.image_indices) if sv.image_indices else []
        })
    
    # DEBUGGING: Print to console
    print(f"DEBUG - Product {product_id}:")
    print(f"  Images in DB: {len(product.images)}")
    print(f"  Color variants: {len(colors_data)}")
    print(f"  Size variants: {len(sizes_data)}")
    for cv in colors_data:
        print(f"    Color '{cv['name']}' -> images: {cv['images']}")
    for sv in sizes_data:
        print(f"    Size '{sv['name']}' -> images: {sv['images']}")
    
    # Get suggested products
    if product.category:
        suggested = Product.query.filter(
            Product.category == product.category,
            Product.id != product_id
        ).limit(4).all()
        
        if len(suggested) < 4:
            additional = Product.query.filter(
                Product.id != product_id
            ).order_by(db.func.random()).limit(4 - len(suggested)).all()
            suggested.extend(additional)
    else:
        suggested = Product.query.filter(
            Product.id != product_id
        ).order_by(db.func.random()).limit(4).all()
    
    return render_template(
        "product.html", 
        product=product, 
        suggested_products=suggested,
        color_variants_json=json.dumps(colors_data),
        size_variants_json=json.dumps(sizes_data)
    )


@app.route("/create_order", methods=["POST"])
def create_order():
    data = request.get_json() or {}
    local_order_id = data.get("order_id")
    if not local_order_id:
        return jsonify({"error": "missing order_id"}), 400

    order = db.session.get(Order, local_order_id)
    if not order:
        return jsonify({"error": "order not found"}), 404

    try:
        amount_paisa = int(order.total_amount) * 100
    except Exception:
        amount_paisa = None

    if not isinstance(amount_paisa, int) or amount_paisa < 100:
        return jsonify({"error": "invalid_amount", "detail": f"amount_paisa={amount_paisa}"}), 400

    client = get_razorpay_client()

    try:
        razor_order = client.order.create({
            "amount": amount_paisa,
            "currency": "INR",
            "receipt": f"order_{order.id}",
            "payment_capture": 1
        })
    except Exception as e:
        print("ERROR creating razorpay order:", type(e), e)
        traceback.print_exc()
        return jsonify({"error": "razorpay_error", "detail": str(e)}), 500

    order.razorpay_order_id = razor_order.get("id")
    db.session.commit()

    return jsonify({
        "razorpay_order_id": razor_order.get("id"),
        "amount": amount_paisa,
        "currency": "INR",
        "key": RAZORPAY_KEY_ID
    })

@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    payload = request.get_json() or {}
    r_order_id = payload.get("razorpay_order_id")
    r_payment_id = payload.get("razorpay_payment_id")
    r_signature = payload.get("razorpay_signature")
    local_order_id = payload.get("local_order_id")

    if not all([r_order_id, r_payment_id, r_signature, local_order_id]):
        return jsonify({"error": "missing fields"}), 400

    client = get_razorpay_client()
    params = {
        "razorpay_order_id": r_order_id,
        "razorpay_payment_id": r_payment_id,
        "razorpay_signature": r_signature
    }

    try:
        client.utility.verify_payment_signature(params)
    except razorpay.errors.SignatureVerificationError as e:
        order = db.session.get(Order, local_order_id)
        if order:
            order.payment_status = PAYMENT_FAILED
            db.session.commit()
        return jsonify({"status": "failure", "error": str(e)}), 400

    order = db.session.get(Order, local_order_id)

    if order and order.payment_status != PAYMENT_PAID:
        order.payment_status = PAYMENT_PAID
        order.razorpay_payment_id = r_payment_id
        order.razorpay_signature = r_signature
        db.session.commit()

    return jsonify({"status": "success"})

@app.route("/razorpay_webhook", methods=["POST"])
def razorpay_webhook():
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    body = request.data
    signature = request.headers.get("X-Razorpay-Signature", "")

    if secret:
        computed = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed, signature):
            return "invalid signature", 400

    event = request.get_json()
    etype = event.get("event")

    if etype == "payment.captured":
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        r_payment_id = payment.get("id")
        r_order_id = payment.get("order_id")

        if not r_payment_id or not r_order_id:
            return jsonify({"ok": True})

        local_order = Order.query.filter_by(razorpay_order_id=r_order_id).first()

        if not local_order:
            return jsonify({"ok": True})

        if local_order.payment_status == PAYMENT_PAID:
            return jsonify({"ok": True})

        local_order.payment_status = PAYMENT_PAID
        local_order.razorpay_payment_id = r_payment_id
        db.session.commit()

    return jsonify({"ok": True})


# ------------- Admin: Product Management -------------

def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("is_admin"):
        return redirect(url_for("admin_orders"))

    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("Admin login successful", "success")
            nxt = request.args.get("next") or url_for("admin_orders")
            return redirect(nxt)
        else:
            flash("Wrong password", "danger")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Logged out", "info")
    return redirect(url_for("admin_login"))


@app.route("/admin/products")
@admin_required
def admin_products():
    products = Product.query.order_by(Product.id.desc()).all()
    return render_template("admin_products.html", products=products)

@app.route("/admin")
@admin_required
def admin_index():
    orders_count = Order.query.count()
    products_count = Product.query.count()
    today = datetime.utcnow().date()
    todays_count = Order.query.filter(db.func.date(Order.created_at) == today).count()
    return render_template("admin_index.html",
                           orders_count=orders_count,
                           products_count=products_count,
                           todays_count=todays_count)


@app.route("/admin/products/add", methods=["GET", "POST"])
@admin_required
def admin_product_add():
    if request.method == "POST":
        name = request.form.get("name")
        price = int(request.form.get("price") or 0)
        description = request.form.get("description")
        is_bestseller = request.form.get("is_bestseller") == "on"
        is_new_launch = request.form.get("is_new_launch") == "on"
        new_launch_date = datetime.utcnow() if is_new_launch else None
        category = request.form.get("category")
        
        sale_price_str = request.form.get("sale_price", "").strip()
        sale_price = int(sale_price_str) if sale_price_str else None

        p = Product(
            name=name,
            price=price,
            description=description,
            image_url=None,
            is_bestseller=is_bestseller,
            is_new_launch=is_new_launch,
            new_launch_date=new_launch_date,
            category=category,
            sale_price=sale_price
        )
        db.session.add(p)
        db.session.commit()

        # Handle multiple images
        files = request.files.getlist("images")
        for idx, file in enumerate(files):
            if file and file.filename:
                image_url = save_product_image(file)
                if idx == 0:
                    p.image_url = image_url
                db.session.add(
                    ProductImage(
                        product_id=p.id,
                        image_url=image_url,
                        order_index=idx
                    )
                )

        # Handle variants
        color_variants_json = request.form.get("color_variants", "[]")
        size_variants_json = request.form.get("size_variants", "[]")
        
        try:
            color_variants = json.loads(color_variants_json)
            for cv in color_variants:
                if cv.get('name'):
                    db.session.add(ProductVariant(
                        product_id=p.id,
                        variant_type='color',
                        name=cv.get('name'),
                        code=cv.get('code'),
                        price_adjustment=int(cv.get('price_adj', 0)),
                        image_indices=json.dumps(cv.get('images', []))
                    ))
        except:
            pass
        
        try:
            size_variants = json.loads(size_variants_json)
            for sv in size_variants:
                if sv.get('name'):
                    db.session.add(ProductVariant(
                        product_id=p.id,
                        variant_type='size',
                        name=sv.get('name'),
                        price_adjustment=int(sv.get('price_adj', 0)),
                        image_indices=json.dumps(sv.get('images', []))
                    ))
        except:
            pass

        db.session.commit()
        return redirect(url_for("admin_products"))

    # FOR GET REQUEST - adding new product (no existing variants)
    return render_template(
        "admin_product_form.html", 
        product=None, 
        categories=[c.name for c in Category.query.order_by(Category.order_index).all()],
        existing_color_variants=json.dumps([]),
        existing_size_variants=json.dumps([])
    )


@app.route("/admin/products/edit/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    
    if request.method == "POST":
        product.name = request.form.get("name")
        product.price = int(request.form.get("price") or 0)
        product.description = request.form.get("description")
        product.is_bestseller = request.form.get("is_bestseller") == "on"
        product.is_new_launch = request.form.get("is_new_launch") == "on"
        is_new_launch_checked = request.form.get("is_new_launch") == "on"
        
        # If marking as new launch for first time, set the date
        if is_new_launch_checked and not product.is_new_launch:
            product.new_launch_date = datetime.utcnow()
        # If unchecking new launch, clear the date
        elif not is_new_launch_checked:
            product.new_launch_date = None
        
        product.is_new_launch = is_new_launch_checked
        product.category = request.form.get("category")
        
        sale_price_str = request.form.get("sale_price", "").strip()
        product.sale_price = int(sale_price_str) if sale_price_str else None

        # Handle image order
        image_order_json = request.form.get("image_order", "")
        if image_order_json:
            try:
                image_order = json.loads(image_order_json)
                for idx, img_id in enumerate(image_order):
                    img = ProductImage.query.get(int(img_id))
                    if img:
                        img.order_index = idx
                        if idx == 0:
                            product.image_url = img.image_url
            except:
                pass

        # Handle new images
        files = request.files.getlist("images")
        if files and files[0].filename:
            current_max_index = db.session.query(db.func.max(ProductImage.order_index)).filter_by(product_id=product.id).scalar() or -1
            for idx, file in enumerate(files):
                if file and file.filename and allowed_file(file.filename):
                    image_url = save_product_image(file)
                    if not product.image_url:
                        product.image_url = image_url
                    db.session.add(
                        ProductImage(
                            product_id=product.id,
                            image_url=image_url,
                            order_index=current_max_index + idx + 1
                        )
                    )

        # Update variants
        ProductVariant.query.filter_by(product_id=product.id).delete()
        
        color_variants_json = request.form.get("color_variants", "[]")
        size_variants_json = request.form.get("size_variants", "[]")
        
        try:
            color_variants = json.loads(color_variants_json)
            for cv in color_variants:
                if cv.get('name'):
                    db.session.add(ProductVariant(
                        product_id=product.id,
                        variant_type='color',
                        name=cv.get('name'),
                        code=cv.get('code'),
                        price_adjustment=int(cv.get('price_adj', 0)),
                        image_indices=json.dumps(cv.get('images', []))
                    ))
        except:
            pass
        
        try:
            size_variants = json.loads(size_variants_json)
            for sv in size_variants:
                if sv.get('name'):
                    db.session.add(ProductVariant(
                        product_id=product.id,
                        variant_type='size',
                        name=sv.get('name'),
                        price_adjustment=int(sv.get('price_adj', 0)),
                        image_indices=json.dumps(sv.get('images', []))
                    ))
        except:
            pass

        db.session.commit()
        return redirect(url_for("admin_products"))

    # FOR GET REQUEST - Load existing variants
    color_vars = ProductVariant.query.filter_by(product_id=product.id, variant_type='color').all()
    size_vars = ProductVariant.query.filter_by(product_id=product.id, variant_type='size').all()

    existing_colors = []
    for cv in color_vars:
        existing_colors.append({
            'id': str(cv.id),
            'name': cv.name,
            'code': cv.code or '#000000',
            'price_adj': cv.price_adjustment,
            'images': json.loads(cv.image_indices) if cv.image_indices else []
        })

    existing_sizes = []
    for sv in size_vars:
        existing_sizes.append({
            'id': str(sv.id),
            'name': sv.name,
            'price_adj': sv.price_adjustment,
            'images': json.loads(sv.image_indices) if sv.image_indices else []
        })

    return render_template(
        "admin_product_form.html", 
        product=product, 
        categories=[c.name for c in Category.query.order_by(Category.order_index).all()],
        existing_color_variants=json.dumps(existing_colors),
        existing_size_variants=json.dumps(existing_sizes)
    )


@app.route("/admin/products/delete/<int:product_id>", methods=["POST"])
@admin_required
def admin_product_delete(product_id):
    product = Product.query.get_or_404(product_id)

    if product.image_url:
        try:
            path = os.path.join("static", product.image_url)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("admin_products"))

@app.route("/admin/orders")
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template("admin_orders.html", orders=orders)


@app.route("/admin/orders/<int:order_id>")
@admin_required
def admin_order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    items = OrderItem.query.filter_by(order_id=order.id).all()
    return render_template("admin_order_detail.html", order=order, items=items)


@app.route("/admin/orders/<int:order_id>/set-status", methods=["POST"])
@admin_required
def admin_set_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status")
    if new_status:
        order.status = new_status
        db.session.commit()
    return redirect(url_for("admin_order_detail", order_id=order_id))

@app.route("/admin/products/delete-image/<int:image_id>", methods=["POST"])
@admin_required
def admin_delete_image(image_id):
    try:
        image = ProductImage.query.get_or_404(image_id)
        product = image.product
        
        try:
            image_path = os.path.join("static", image.image_url)
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            print(f"Error deleting image file: {e}")
        
        if product.image_url == image.image_url:
            remaining_images = ProductImage.query.filter(
                ProductImage.product_id == product.id,
                ProductImage.id != image_id
            ).first()
            
            if remaining_images:
                product.image_url = remaining_images.image_url
            else:
                product.image_url = None
        
        db.session.delete(image)
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error deleting image: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/admin/orders/export")
@admin_required
def admin_orders_export():
    orders = Order.query.order_by(Order.created_at.desc()).all()

    output = "Order ID,Created,Name,Phone,City,Total,Status,Payment Status\n"
    for o in orders:
        created = o.created_at.strftime("%Y-%m-%d %H:%M")
        line = f'{o.id},"{created}","{o.customer_name}","{o.phone}","{o.city or ""}",{o.total_amount},{o.status or ""},{o.payment_status or ""}\n'
        output += line

    response = make_response(output)
    response.headers["Content-Disposition"] = "attachment; filename=orders.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


# ----- CART ACTIONS -----

@app.route("/add/<int:product_id>")
def add_to_cart(product_id):
    cart = get_cart()
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session["cart"] = cart
    session["open_cart"] = True
    return redirect(request.referrer or url_for("shop"))


@app.route("/cart/increase/<int:product_id>")
def increase_quantity(product_id):
    cart = get_cart()
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session["cart"] = cart
    session["open_cart"] = True
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/decrease/<int:product_id>")
def decrease_quantity(product_id):
    cart = get_cart()
    pid = str(product_id)
    if pid in cart:
        cart[pid] -= 1
        if cart[pid] <= 0:
            cart.pop(pid)
    session["cart"] = cart
    session["open_cart"] = True
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/remove/<int:product_id>")
def remove_from_cart(product_id):
    cart = get_cart()
    cart.pop(str(product_id), None)
    session["cart"] = cart
    session["open_cart"] = True
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart")
def cart():
    items, total, count = build_cart()
    return render_template("cart.html", cart_items=items, total=total)


@app.route("/order-success/<int:order_id>")
def order_success(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("order_success.html", order=order)

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, total, count = build_cart()

    if not items:
        return redirect(url_for("shop"))

    if request.method == "POST":
        customer_name = request.form.get("name")
        phone = request.form.get("phone")
        email = request.form.get("email")
        address = request.form.get("address")
        city = request.form.get("city")
        pincode = request.form.get("pincode")
        notes = request.form.get("notes")

        order = Order(
            customer_name=customer_name,
            phone=phone,
            email=email,
            address=address,
            city=city,
            pincode=pincode,
            notes=notes,
            total_amount=total,
        )

        db.session.add(order)
        db.session.flush()

        for item in items:
            effective_price = item["product"].sale_price if item["product"].sale_price else item["product"].price
            oi = OrderItem(
                order_id=order.id,
                product_id=item["product"].id,
                product_name=item["product"].name,
                unit_price=effective_price,
                quantity=item["quantity"],
            )
            db.session.add(oi)

        db.session.commit()
        session["cart"] = {}

        print(">>> ABOUT TO SEND SMS FOR ORDER", order.id)

        try:
            client = Client(account_sid, auth_token)
            message_body = (
                f"KCX Crochet order #{order.id} | ₹{total} | "
                f"{customer_name}, {phone}, {city} {pincode}"
            )

            TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
            ADMIN_PHONE_NUMBER = os.getenv("ADMIN_PHONE_NUMBER")

            client.messages.create(
                body=message_body,
                from_=TWILIO_FROM_NUMBER,
                to=ADMIN_PHONE_NUMBER,
            )

            print("SMS Sent Successfully!")

        except Exception as e:
            print("SMS FAILED:", e)

        return redirect(url_for("order_success", order_id=order.id))

    return render_template("checkout.html", cart_items=items, total=total, count=count)

@app.route("/checkout_ajax", methods=["POST"])
def checkout_ajax():
    items, total, count = build_cart()

    if not items:
        return jsonify({"error": "cart_empty"}), 400

    customer_name = request.form.get("name") or "Customer"
    phone = request.form.get("phone") or ""
    email = request.form.get("email") or ""
    address = request.form.get("address") or ""
    city = request.form.get("city") or ""
    pincode = request.form.get("pincode") or ""
    notes = request.form.get("notes") or ""
    
    # ADD THIS: Get gift wrap data
    import json
    gift_wraps_json = request.form.get("gift_wraps", "{}")
    gift_wraps = {}
    try:
        gift_wraps = json.loads(gift_wraps_json)
    except:
        pass
    
    # Calculate total with gift wraps
    wrap_total = sum(wrap.get('price', 0) for wrap in gift_wraps.values())
    final_total = total + wrap_total

    order = Order(
        customer_name=customer_name,
        phone=phone,
        email=email,
        address=address,
        city=city,
        pincode=pincode,
        notes=notes,
        total_amount=final_total,  # CHANGE: Use final_total instead of total
        payment_status="Unpaid",
        status="Pending"
    )
    db.session.add(order)
    db.session.flush()

    for it in items:
        prod = it["product"]
        qty = it["quantity"]
        effective_price = prod.sale_price if prod.sale_price else prod.price
        oi = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=effective_price,
            quantity=qty
        )
        db.session.add(oi)
        db.session.flush()
        
        # ADD THIS: Handle gift wrap for this item
        product_id_str = str(prod.id)
        if product_id_str in gift_wraps:
            wrap_data = gift_wraps[product_id_str]
            db.session.add(GiftWrap(
                order_item_id=oi.id,
                wrap_type=wrap_data.get('type'),
                wrap_price=wrap_data.get('price')
            ))

    db.session.commit()

    return jsonify({"order_id": order.id, "total": final_total})  # CHANGE: Return final_total

# ----- CATEGORY MANAGEMENT ROUTES -----

@app.route("/admin/categories")
@admin_required
def admin_categories():
    categories = Category.query.order_by(Category.order_index).all()
    return render_template("admin_categories.html", categories=categories)

@app.route("/admin/categories/add", methods=["POST"])
@admin_required
def admin_category_add():
    name = request.form.get("name", "").strip()
    if name:
        existing = Category.query.filter_by(name=name).first()
        if not existing:
            max_order = db.session.query(db.func.max(Category.order_index)).scalar() or -1
            category = Category(name=name, order_index=max_order + 1)
            db.session.add(category)
            db.session.commit()
            flash(f"Category '{name}' added successfully!", "success")
        else:
            flash(f"Category '{name}' already exists!", "warning")
    return redirect(url_for("admin_categories"))

@app.route("/admin/categories/delete/<int:category_id>", methods=["POST"])
@admin_required
def admin_category_delete(category_id):
    category = Category.query.get_or_404(category_id)
    # Check if any products use this category
    products_count = Product.query.filter_by(category=category.name).count()
    if products_count > 0:
        flash(f"Cannot delete '{category.name}' - {products_count} products are using it!", "danger")
    else:
        db.session.delete(category)
        db.session.commit()
        flash(f"Category '{category.name}' deleted!", "success")
    return redirect(url_for("admin_categories"))

@app.route("/admin/categories/reorder", methods=["POST"])
@admin_required
def admin_category_reorder():
    data = request.get_json()
    order = data.get("order", [])
    for idx, cat_id in enumerate(order):
        category = Category.query.get(int(cat_id))
        if category:
            category.order_index = idx
    db.session.commit()
    return jsonify({"success": True})


# ------------ MAIN ------------

with app.app_context():
    db.create_all()
    # Initialize default categories if none exist
    if Category.query.count() == 0:
        default_categories = [
            "Seasonal", "Desk Buddies", "Keyrings", 
            "Mini Bouquet", "Yarn", "Bookmarks", "Forever Flowers"
        ]
        for idx, cat_name in enumerate(default_categories):
            db.session.add(Category(name=cat_name, order_index=idx))
        db.session.commit()
        print("✓ Default categories initialized")
    
if __name__ == "__main__":
    app.run(debug=True)

