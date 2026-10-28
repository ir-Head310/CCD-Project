"""Small static in-memory product catalogue (no database in scope)."""

_RAW = [
    (101, "Smartphone X12 (128 GB)", "electronics", 24999),
    (102, "Wireless Earbuds Pro", "electronics", 5999),
    (103, "4K Smart TV 55\"", "electronics", 52999),
    (104, "Laptop Air 14", "electronics", 64999),
    (105, "Smartwatch Fit 3", "electronics", 7999),
    (201, "Running Shoes Glide", "fashion", 4499),
    (202, "Denim Jacket", "fashion", 2999),
    (203, "Cotton Kurta Set", "fashion", 1799),
    (301, "Air Fryer 4L", "home", 6999),
    (302, "Mixer Grinder 750W", "home", 3499),
    (303, "Robot Vacuum Lite", "home", 15999),
    (401, "Protein Powder 1kg", "grocery", 2199),
    (402, "Basmati Rice 5kg", "grocery", 899),
    (501, "Bestseller Novel Box Set", "books", 1499),
    (502, "Competitive Exam Guide", "books", 699),
]

PRODUCTS = {
    pid: {"id": pid, "name": name, "category": cat, "mrp": mrp, "currency": "INR"}
    for pid, name, cat, mrp in _RAW
}
