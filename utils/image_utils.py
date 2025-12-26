import os
import uuid
import time
from PIL import Image
from flask import current_app

# Allowed input formats from admin
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}

def save_product_image(file):
    """
    Saves an uploaded product image in static/products
    - Auto-renames file
    - Forces lowercase
    - Converts to JPG
    - Safe for Windows + Linux
    - Returns DB-safe path: products/<filename>.jpg
    """

    # 1. Validate extension
    if "." not in file.filename:
        raise ValueError("Invalid file")

    ext = file.filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported image type")

    # 2. Generate safe unique filename
    filename = f"{int(time.time())}_{uuid.uuid4().hex}.jpg"

    # 3. Absolute path to static/products
    save_path = os.path.join(
        current_app.root_path,
        "static",
        "products",
        filename
    )

    # 4. Ensure directory exists (safety)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # 5. Open, normalize, and save image
    image = Image.open(file)
    image = image.convert("RGB")  # removes alpha, normalizes
    image.save(save_path, "JPEG", quality=90)

    # 6. Return DB-safe relative path
    return f"products/{filename}"
