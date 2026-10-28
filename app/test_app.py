import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_health_and_ready(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").get_json()["status"] == "ready"


def test_list_and_filter(client):
    all_items = client.get("/products").get_json()
    assert all_items["count"] == 15
    books = client.get("/products?category=books").get_json()
    assert books["count"] == 2


def test_get_product_and_404(client):
    assert client.get("/products/101").get_json()["name"].startswith("Smartphone")
    assert client.get("/products/999").status_code == 404


def test_price_calculation(client):
    body = client.get("/products/101/price?qty=3").get_json()
    assert body["qty"] == 3
    assert 0 < body["unit_price"] < body["mrp"]
    assert body["total"] == pytest.approx(body["unit_price"] * 3, abs=0.05)


def test_price_validation(client):
    assert client.get("/products/101/price?qty=0").status_code == 400
    assert client.get("/products/101/price?qty=abc").status_code == 400


def test_served_by_header(client):
    assert client.get("/").headers["X-Served-By"]
