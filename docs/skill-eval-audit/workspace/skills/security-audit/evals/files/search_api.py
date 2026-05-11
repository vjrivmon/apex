import sqlite3

from fastapi import APIRouter

router = APIRouter()
_db = sqlite3.connect("shop.db", check_same_thread=False)


@router.get("/api/products/search")
def search_products(query: str, limit: int = 50):
    cur = _db.cursor()
    sql = f"SELECT id, name, price FROM products WHERE name LIKE '%{query}%' LIMIT {limit}"
    cur.execute(sql)
    rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "price": r[2]} for r in rows]


@router.get("/api/products/{product_id}")
def get_product(product_id: int):
    cur = _db.cursor()
    cur.execute("SELECT id, name, price FROM products WHERE id = ?", (product_id,))
    row = cur.fetchone()
    if row is None:
        return {"error": "not found"}
    return {"id": row[0], "name": row[1], "price": row[2]}
