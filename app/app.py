"""Product Service: a CPU-heavy Flask microservice that simulates an e-commerce
catalogue lookup plus flash-sale price/discount calculation.

The pricing endpoint deliberately burns CPU (iterated SHA-256 "risk scoring")
so that request volume maps to CPU utilisation, which is what the Kubernetes
HPA scales on.
"""
import hashlib
import json
import logging
import os
import socket
import sys
import time

from flask import Flask, abort, g, jsonify, render_template, request

from catalog import PRODUCTS

POD_NAME = os.environ.get("POD_NAME", socket.gethostname())
APP_VERSION = os.environ.get("APP_VERSION", "dev")
# Hash rounds per pricing request (~1.6 us each on a laptop core); 3000 is about 5 ms of CPU.
WORK_ITERATIONS = int(os.environ.get("WORK_ITERATIONS", "3000"))
SALE_DISCOUNT_PCT = float(os.environ.get("SALE_DISCOUNT_PCT", "40"))


class JsonFormatter(logging.Formatter):
    """One JSON object per line so Azure Monitor / Container Insights can parse logs."""

    def format(self, record):
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "pod": POD_NAME,
            "version": APP_VERSION,
            "msg": record.getMessage(),
        }
        entry.update(getattr(record, "extra_fields", {}))
        return json.dumps(entry)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger("product-service")
log.addHandler(handler)
log.setLevel(logging.INFO)
log.propagate = False

app = Flask(__name__)
_started_at = time.time()
_ready = True


def burn_cpu(seed: str, iterations: int) -> str:
    digest = seed.encode()
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()


def compute_price(product: dict, qty: int) -> dict:
    # The "fraud/risk score" is the CPU-intensive part; it nudges the discount slightly.
    risk_hash = burn_cpu(f"{product['id']}:{qty}:{time.time_ns()}", WORK_ITERATIONS)
    risk_score = int(risk_hash[:4], 16) / 0xFFFF  # 0..1
    discount_pct = SALE_DISCOUNT_PCT - risk_score * 5
    if qty >= 3:
        discount_pct += 5  # bulk bonus
    discount_pct = max(0.0, min(discount_pct, 90.0))
    unit = round(product["mrp"] * (1 - discount_pct / 100), 2)
    return {
        "product_id": product["id"],
        "name": product["name"],
        "qty": qty,
        "mrp": product["mrp"],
        "discount_pct": round(discount_pct, 2),
        "unit_price": unit,
        "total": round(unit * qty, 2),
        "risk_score": round(risk_score, 4),
    }


def find_product(product_id: int) -> dict:
    product = PRODUCTS.get(product_id)
    if product is None:
        abort(404, description=f"product {product_id} not found")
    return product


@app.before_request
def _start_timer():
    g.t0 = time.perf_counter()


@app.after_request
def _log_and_tag(response):
    # X-Served-By lets the load test / demo show requests spreading across pods.
    response.headers["X-Served-By"] = POD_NAME
    if request.path not in ("/healthz", "/readyz", "/whoami"):
        latency_ms = (time.perf_counter() - g.t0) * 1000
        log.info(
            "request",
            extra={"extra_fields": {
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "latency_ms": round(latency_ms, 2),
            }},
        )
    return response


@app.get("/")
def index():
    return jsonify(service="product-service", version=APP_VERSION, pod=POD_NAME)


@app.get("/shop")
def shop():
    # Demo storefront: product grid plus a live panel showing which pod answers.
    return render_template("shop.html", pod=POD_NAME, version=APP_VERSION)


@app.get("/whoami")
def whoami():
    # Cheap endpoint the storefront polls to show load balancing across pods.
    return jsonify(pod=POD_NAME, version=APP_VERSION)


@app.get("/healthz")
def healthz():
    # Liveness: the process is up and able to serve.
    return jsonify(status="ok", uptime_s=round(time.time() - _started_at, 1))


@app.get("/readyz")
def readyz():
    # Readiness: catalogue loaded and not draining.
    if not _ready or not PRODUCTS:
        return jsonify(status="not-ready"), 503
    return jsonify(status="ready")


@app.get("/products")
def list_products():
    category = request.args.get("category")
    items = [p for p in PRODUCTS.values() if category is None or p["category"] == category]
    return jsonify(count=len(items), products=items)


@app.get("/products/<int:product_id>")
def get_product(product_id: int):
    return jsonify(find_product(product_id))


@app.get("/products/<int:product_id>/price")
def get_price(product_id: int):
    product = find_product(product_id)
    try:
        qty = int(request.args.get("qty", "1"))
    except ValueError:
        abort(400, description="qty must be an integer")
    if not 1 <= qty <= 10:
        abort(400, description="qty must be between 1 and 10")
    return jsonify(compute_price(product, qty))


@app.errorhandler(400)
@app.errorhandler(404)
def _client_error(err):
    return jsonify(error=err.description), err.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
