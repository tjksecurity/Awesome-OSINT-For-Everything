"""
PATCHED FLASK SHOP — Price Tampering Fix
=========================================
Educational purpose only.

PATCH SUMMARY
-------------
The root cause was that the server trusted the price field sent by the client.

FIX: Never accept price from the client. The server looks up the authoritative
price from its own PRODUCTS catalog using only the product_id supplied by the
client. The price field is ignored entirely even if the client sends one.

This is the correct pattern:
  - Accept only a *selector* (product_id) from the client.
  - Look up the price on the server side.
  - Never let the client influence the monetary value.

Changes from vulnerable version are marked with: # FIX
"""

from flask import Flask, request, jsonify, render_template_string
import sqlite3

app = Flask(__name__)
DB_PATH = "shop_patched.db"

PRODUCTS = {
    1: {"name": "Laptop",              "price": 999.99},
    2: {"name": "Headphones",          "price": 149.99},
    3: {"name": "Mechanical Keyboard", "price":  89.99},
    4: {"name": "USB-C Hub",           "price":  39.99},
    5: {"name": "Webcam",              "price":  59.99},
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            name       TEXT,
            quantity   INTEGER,
            price_paid REAL,
            timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------
# HTML template — price is NOT a form field anymore
# -----------------------------------------------------------------------
SHOP_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Patched-Shop (Educational)</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }
    .product { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
    button { background: #28a745; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
    button:hover { background: #1e7e34; }
    .note { background: #d4edda; padding: 15px; border-radius: 6px; margin-top: 20px; color: #155724; }
    pre { background: #2b2b2b; color: #f8f8f2; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 13px; }
  </style>
</head>
<body>
  <h1>Patched-Shop <span style="font-size:14px;color:green;">[PATCHED VERSION]</span></h1>

  <h2>Products</h2>
  {% for pid, p in products.items() %}
  <div class="product">
    <div><strong>{{ p.name }}</strong></div>
    <div>${{ "%.2f"|format(p.price) }}</div>
    <form method="POST" action="/checkout">
      <!-- FIX: Only product_id and quantity are sent. No price field. -->
      <input type="hidden" name="product_id" value="{{ pid }}">
      <input type="hidden" name="quantity"   value="1">
      <button type="submit">Buy Now</button>
    </form>
  </div>
  {% endfor %}

  <div class="note">
    <h3>Patch Applied</h3>
    <p>The <code>price</code> field has been <strong>removed from the form</strong>.
    The server now looks up the price using only <code>product_id</code>:</p>
    <pre># PATCHED checkout route
product = PRODUCTS.get(product_id)
if not product:
    return error 404

# Server-side price lookup — client has no influence
real_price = product["price"]          # FIX: ignore any client-sent price
total      = real_price * quantity     # FIX: compute total server-side</pre>
    <p>Even if an attacker manually crafts a POST with a fake price, the server
    ignores it completely.</p>
  </div>
</body>
</html>
"""

ORDERS_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Orders - Patched-Shop</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #ddd; padding: 10px; }
    th { background: #f2f2f2; }
    a { color: #007bff; text-decoration: none; }
  </style>
</head>
<body>
  <h1>Order Log (Patched) <a href="/" style="font-size:14px;">← Back</a></h1>
  <table>
    <tr><th>#</th><th>Product</th><th>Qty</th><th>Price Charged</th><th>Time</th></tr>
    {% for o in orders %}
    <tr>
      <td>{{ o[0] }}</td><td>{{ o[2] }}</td><td>{{ o[3] }}</td>
      <td>${{ "%.2f"|format(o[4]) }}</td><td>{{ o[5] }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""

# -----------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(SHOP_HTML, products=PRODUCTS)


@app.route("/products", methods=["GET"])
def list_products():
    return jsonify(PRODUCTS)


@app.route("/checkout", methods=["POST"])
def checkout():
    """
    PATCHED endpoint.
    Only accepts product_id and quantity from the client.
    Price is always looked up server-side.
    """
    try:
        product_id = int(request.form.get("product_id", 0))
        quantity   = int(request.form.get("quantity", 1))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid input"}), 400

    # FIX: Validate product exists
    product = PRODUCTS.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    # FIX: Price is always sourced from the server — never from the request
    real_price = product["price"]
    total      = real_price * quantity

    # FIX: Validate quantity is reasonable
    if quantity < 1 or quantity > 100:
        return jsonify({"error": "Quantity must be between 1 and 100"}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO orders (product_id, name, quantity, price_paid) VALUES (?,?,?,?)",
        (product_id, product["name"], quantity, real_price)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "status":        "Order placed",
        "product":       product["name"],
        "quantity":      quantity,
        "price_charged": round(real_price, 2),
        "total_charged": round(total, 2),
        "message":       f"Thank you! Charged ${total:.2f}",
        "note":          "Price was looked up server-side. Any client-sent price field was ignored.",
    })


@app.route("/orders", methods=["GET"])
def orders():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return render_template_string(ORDERS_HTML, orders=rows)


@app.route("/reset", methods=["POST"])
def reset():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM orders")
    conn.commit()
    conn.close()
    return jsonify({"status": "Orders cleared"})


if __name__ == "__main__":
    print("=" * 55)
    print("  Patched-Shop running at http://localhost:5001")
    print("  Order log:           http://localhost:5001/orders")
    print("  [EDUCATIONAL USE ONLY — patched version]")
    print("=" * 55)
    app.run(debug=True, port=5001)
