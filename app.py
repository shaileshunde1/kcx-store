from flask import Flask, render_template, session, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from twilio.rest import Client
import csv
from flask import make_response, request
import os
from werkzeug.utils import secure_filename
from functools import wraps
from flask import session, flash
from dotenv import load_dotenv
import razorpay
from flask import jsonify
import hmac, hashlib
from flask import jsonify
import traceback





load_dotenv()

app = Flask(__name__)
app.secret_key = "mysecret"

# --- Upload configuration ---
UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# razorpay config
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

def get_razorpay_client():
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


# Admin auth config
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")  # fallback for dev only



# --- DATABASE SETUP ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "store.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---- Twilio SMS Config (local dev only) ----
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")           
client = Client(account_sid, auth_token)


# --- MODELS ---
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(300), nullable=True)
    is_bestseller = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Product {self.name}>"
    
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

    # order workflow & payment fields
    status = db.Column(db.String(30), default="Pending")            # Pending / Confirmed / Shipped / Completed / Cancelled
    payment_status = db.Column(db.String(30), default="Unpaid")     # Unpaid / Paid / Failed

    # razorpay fields
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
            items.append({"product": product, "quantity": qty})
            total += product.price * qty
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
    )


# ------------ ROUTES ------------

@app.route("/")
def home():
    bestsellers = Product.query.filter_by(is_bestseller=True).all()
    return render_template("home.html", products=bestsellers)


@app.route("/shop")
def shop():
    products = Product.query.all()
    return render_template("shop.html", products=products)

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template("product.html", product=product)

@app.route("/create_order", methods=["POST"])
def create_order():
    data = request.get_json() or {}
    local_order_id = data.get("order_id")
    if not local_order_id:
        return jsonify({"error": "missing order_id"}), 400

    order = Order.query.get(local_order_id)
    if not order:
        return jsonify({"error": "order not found"}), 404

    # sanity-check amount
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
        # print full traceback to flask console for debugging
        print("ERROR creating razorpay order:", type(e), e)
        traceback.print_exc()
        # return the exception string to frontend (safe in dev)
        return jsonify({"error": "razorpay_error", "detail": str(e)}), 500

    # store returned razorpay order id
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
        order = Order.query.get(local_order_id)
        if order:
            order.payment_status = "Failed"
            db.session.commit()
        return jsonify({"status": "failure", "error": str(e)}), 400

    order = Order.query.get(local_order_id)
    if order:
        order.payment_status = "Paid"
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
        computed = hmac.new(bytes(secret, 'utf-8'), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, signature):
            return "invalid signature", 400

    event = request.get_json()
    etype = event.get("event")
    if etype == "payment.captured":
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        r_payment_id = payment.get("id")
        r_order_id = payment.get("order_id")
        local_order = Order.query.filter_by(razorpay_order_id=r_order_id).first()
        if local_order:
            local_order.payment_status = "Paid"
            local_order.razorpay_payment_id = r_payment_id
            db.session.commit()

    return jsonify({"ok": True})


# ------------- Admin: Product Management -------------

def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            # preserve next path so we can redirect back after login
            return redirect(url_for("admin_login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    # if already logged in, go to admin orders
    if session.get("is_admin"):
        return redirect(url_for("admin_orders"))

    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["is_admin"] = True
            # optional: small flash message
            flash("Admin login successful", "success")
            nxt = request.args.get("next") or url_for("admin_orders")
            return redirect(nxt)
        else:
            flash("Wrong password", "danger")
            # fall through to show form again

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
    # quick metrics (non-expensive)
    orders_count = Order.query.count()
    products_count = Product.query.count()
    # today's orders
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
        is_bestseller = True if request.form.get("is_bestseller") == "on" else False

        image_file = request.files.get("image")
        image_path = None
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            # make filename unique: prefix with timestamp
            fname = f"{int(datetime.utcnow().timestamp())}_{filename}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
            # ensure folder exists
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            image_file.save(save_path)
            image_path = os.path.join("uploads", fname)  # store relative to static/

        p = Product(
            name=name,
            price=price,
            description=description,
            image_url=image_path,
            is_bestseller=is_bestseller
        )
        db.session.add(p)
        db.session.commit()
        return redirect(url_for("admin_products"))

    return render_template("admin_product_form.html", product=None)


@app.route("/admin/products/edit/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        product.name = request.form.get("name")
        product.price = int(request.form.get("price") or 0)
        product.description = request.form.get("description")
        product.is_bestseller = True if request.form.get("is_bestseller") == "on" else False

        image_file = request.files.get("image")
        if image_file and allowed_file(image_file.filename):
            # delete old file if exists
            if product.image_url:
                try:
                    old_path = os.path.join("static", product.image_url)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass

            filename = secure_filename(image_file.filename)
            fname = f"{int(datetime.utcnow().timestamp())}_{filename}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            image_file.save(save_path)
            product.image_url = os.path.join("uploads", fname)

        db.session.commit()
        return redirect(url_for("admin_products"))

    return render_template("admin_product_form.html", product=product)


@app.route("/admin/products/delete/<int:product_id>", methods=["POST"])
@admin_required
def admin_product_delete(product_id):
    product = Product.query.get_or_404(product_id)

    # delete image file if exists
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

    # 🔹 Tell frontend to open cart after this request
    session["open_cart"] = True

    # Go back to the page user was on (home/shop/product)
    return redirect(request.referrer or url_for("shop"))


@app.route("/cart/increase/<int:product_id>")
def increase_quantity(product_id):
    cart = get_cart()
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session["cart"] = cart

    # keep cart open
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

    # keep cart open
    session["open_cart"] = True

    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/remove/<int:product_id>")
def remove_from_cart(product_id):
    cart = get_cart()
    cart.pop(str(product_id), None)
    session["cart"] = cart

    # keep cart open
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

    # if cart is empty, don't allow checkout
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

        # create order
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
        db.session.flush()   # order.id available here

        # TODO: if you want to save each cart line item, loop items here
        # Save individual order items
        for item in items:
         oi = OrderItem(
        order_id=order.id,
        product_id=item["product"].id,
        product_name=item["product"].name,
        unit_price=item["product"].price,
        quantity=item["quantity"],
        )
        db.session.add(oi)


        db.session.commit()

        # clear cart
        session["cart"] = {}

        # ----- SMS NOTIFICATION -----
        print(">>> ABOUT TO SEND SMS FOR ORDER", order.id)

        try:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

            message_body = (
    f"KCX Crochet order #{order.id} | ₹{total} | "
    f"{customer_name}, {phone}, {city} {pincode}"
)


            client.messages.create(
                body=message_body,
                from_=TWILIO_FROM_NUMBER,
                to=ADMIN_PHONE_NUMBER,
            )

            print("SMS Sent Successfully!")

        except Exception as e:
            print("SMS FAILED:", e)
        # ----------------------------

        return redirect(url_for("order_success", order_id=order.id))

    # GET request → show checkout page
    return render_template("checkout.html", cart_items=items, total=total, count=count)

@app.route("/checkout_ajax", methods=["POST"])
def checkout_ajax():
    # build cart and totals like your checkout handler
    items, total, count = build_cart()

    if not items:
        return jsonify({"error": "cart_empty"}), 400

    # read form fields
    customer_name = request.form.get("name") or "Customer"
    phone = request.form.get("phone") or ""
    email = request.form.get("email") or ""
    address = request.form.get("address") or ""
    city = request.form.get("city") or ""
    pincode = request.form.get("pincode") or ""
    notes = request.form.get("notes") or ""

    # create Order and OrderItems (same as your checkout logic)
    order = Order(
        customer_name=customer_name,
        phone=phone,
        email=email,
        address=address,
        city=city,
        pincode=pincode,
        notes=notes,
        total_amount=total,
        payment_status="Unpaid",
        status="Pending"
    )
    db.session.add(order)
    db.session.flush()  # gives order.id

    # save each item
    for it in items:
        prod = it["product"]
        qty = it["quantity"]
        oi = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            unit_price=prod.price,
            quantity=qty
        )
        db.session.add(oi)

    db.session.commit()

    # keep cart until payment succeeds or clear here if you prefer
    # session["cart"] = {}

    # tell frontend to open cart? not needed here
    return jsonify({"order_id": order.id, "total": total})



# ------------ MAIN ------------

with app.app_context():
    db.create_all()
    
if __name__ == "__main__":
    app.run(debug=True)



