"""
VULNERABLE FLASK SHOP - Price Tampering Target
================================================
Educational purpose only. This app intentionally trusts
the price value sent by the client — a classic insecure design flaw.

VULNERABILITY: The server accepts the item price directly from the POST
request body without verifying it against a server-side price database.
An attacker can modify the price field to pay any amount they choose.
"""

from flask import Flask, request, jsonify, render_template_string
import sqlite3
import os

app = Flask(__name__)
DB_PATH = "shop.db"

# -----------------------------------------------------------------------
# Product catalog (server knows the real prices, but never checks them)
# -----------------------------------------------------------------------
PRODUCTS = {
    1: {"name": "Laptop",       "price": 999.99},
    2: {"name": "Headphones",   "price": 149.99},
    3: {"name": "Mechanical Keyboard", "price": 89.99},
    4: {"name": "USB-C Hub",    "price": 39.99},
    5: {"name": "Webcam",       "price": 59.99},
}

# -----------------------------------------------------------------------
# Database setup
# -----------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            name      TEXT,
            quantity  INTEGER,
            price_paid REAL,
            real_price REAL,
            tampered  INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------
# HTML template (shop UI)
# -----------------------------------------------------------------------
SHOP_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Vuln-Shop (Educational)</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }
    .product { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
    button { background: #007bff; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
    button:hover { background: #0056b3; }
    #cart { background: #f8f9fa; padding: 15px; border-radius: 6px; margin-top: 20px; }
    #result { margin-top: 15px; padding: 10px; border-radius: 4px; }
    .success { background: #d4edda; color: #155724; }
    .warning { background: #fff3cd; color: #856404; font-weight: bold; }
    pre { background: #2b2b2b; color: #f8f8f2; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 13px; }
  </style>
</head>
<body>
  <h1>Vuln-Shop <span style="font-size:14px;color:red;">[INTENTIONALLY VULNERABLE — EDUCATIONAL]</span></h1>

  <h2>Products</h2>
  {% for pid, p in products.items() %}
  <div class="product">
    <div><strong>{{ p.name }}</strong></div>
    <div>${{ "%.2f"|format(p.price) }}</div>
    <form method="POST" action="/checkout">
      <!-- BUG: price is a hidden field controlled by the client -->
      <input type="hidden" name="product_id" value="{{ pid }}">
      <input type="hidden" name="price"      value="{{ p.price }}">
      <input type="hidden" name="quantity"   value="1">
      <button type="submit">Buy Now</button>
    </form>
  </div>
  {% endfor %}

  <div id="cart">
    <h3>Notice for Testers</h3>
    <p>The checkout form sends the <code>price</code> field directly to the server.
    The server <strong>does not validate</strong> that price against the real catalog price.
    Modify the <code>price</code> field to any value to exploit this vulnerability.</p>
    <p>Example raw POST request to tamper:</p>
    <pre>POST /checkout HTTP/1.1
Host: localhost:5000
Content-Type: application/x-www-form-urlencoded

product_id=1&price=0.01&quantity=1</pre>
  </div>
</body>
</html>
"""

ORDERS_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Orders - Vuln-Shop</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
    th { background: #f2f2f2; }
    .tampered { background: #ffe0e0; color: #a00; font-weight: bold; }
    a { color: #007bff; text-decoration: none; }
  </style>
</head>
<body>
  <h1>Order Log <a href="/" style="font-size:14px;">← Back to Shop</a></h1>
  <table>
    <tr>
      <th>#</th><th>Product</th><th>Qty</th>
      <th>Price Paid</th><th>Real Price</th><th>Tampered?</th><th>Time</th>
    </tr>
    {% for o in orders %}
    <tr class="{{ 'tampered' if o[6] else '' }}">
      <td>{{ o[0] }}</td>
      <td>{{ o[2] }}</td>
      <td>{{ o[3] }}</td>
      <td>${{ "%.2f"|format(o[4]) }}</td>
      <td>${{ "%.2f"|format(o[5]) }}</td>
      <td>{{ "YES ⚠️" if o[6] else "No" }}</td>
      <td>{{ o[7] }}</td>
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
    """JSON endpoint — useful for the exploit script."""
    return jsonify(PRODUCTS)


@app.route("/checkout", methods=["POST"])
def checkout():
    """
    VULNERABLE endpoint.
    Accepts price directly from the request without server-side validation.
    """
    try:
        product_id  = int(request.form.get("product_id", 0))
        price_paid  = float(request.form.get("price", 0))
        quantity    = int(request.form.get("quantity", 1))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid input"}), 400

    product = PRODUCTS.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    real_price = product["price"]
    # ⚠️  VULNERABILITY: we trust price_paid from the client
    total_charged = price_paid * quantity
    tampered = abs(price_paid - real_price) > 0.01

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO orders (product_id, name, quantity, price_paid, real_price, tampered) VALUES (?,?,?,?,?,?)",
        (product_id, product["name"], quantity, price_paid, real_price, int(tampered))
    )
    conn.commit()
    conn.close()

    return jsonify({
        "status":        "Order placed",
        "product":       product["name"],
        "quantity":      quantity,
        "price_paid":    round(price_paid, 2),
        "total_charged": round(total_charged, 2),
        "real_price":    real_price,
        "tampered":      tampered,
        "message": (
            f"WARNING: Price mismatch! Real price ${real_price}, paid ${price_paid}"
            if tampered else
            f"Thank you! Charged ${total_charged:.2f}"
        )
    })


@app.route("/orders", methods=["GET"])
def orders():
    """View all orders — shows tampered ones highlighted."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return render_template_string(ORDERS_HTML, orders=rows)


@app.route("/reset", methods=["POST"])
def reset():
    """Clear all orders (for demo resets)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM orders")
    conn.commit()
    conn.close()
    return jsonify({"status": "Orders cleared"})


if __name__ == "__main__":
    print("=" * 55)
    print("  Vuln-Shop running at http://localhost:5000")
    print("  Order log:           http://localhost:5000/orders")
    print("  [EDUCATIONAL USE ONLY — intentionally vulnerable]")
    print("=" * 55)
    app.run(debug=True, port=5000)
