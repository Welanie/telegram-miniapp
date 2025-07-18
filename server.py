from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONFIG = {
    "user": "yan",
    "password": "12345",
    "host": "localhost",
    "port": 5432,
    "dbname": "TTGFiltered"
}
@app.get("/products")
def get_products():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name, category, price, image_base64, username FROM product_data LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    products = [
        {
            "name": row[0],
            "category": row[1],
            "price": row[2],
            "image_base64": row[3],
            "username": row[4],
        }
        for row in rows
    ]
    return products

