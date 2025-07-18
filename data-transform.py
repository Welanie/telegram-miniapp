import asyncio
import aiohttp
import json
import hashlib
from pymongo import MongoClient
import psycopg2
from psycopg2.extras import execute_values

# Config
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "telegram_monitor"
COLLECTION_NAME = "ads"

OLLAMA_API_URL = "http://localhost:11111/api/generate"
MODEL_NAME = "mistral"

POSTGRES_CONFIG = {
    "dbname": "TTGFiltered",
    "user": "yan",
    "password": "12345",
    "host": "localhost",
    "port": 5432
}

# Prompt for LLM
PROMPT_TEMPLATE = """
Extract the following product details from the message:

- name (product name, string)
- category (e.g. clothing, electronics, cosmetics, etc.)
- price (number, only digits, no currency)
- discounted_price (number, only digits, no currency)
- discount_percent (number, only digits, no "%" sign)
- username (string, extracted from @username or Telegram links like https://t.me/username, remove the '@' symbol)
- is_free (boolean, true if discount_percent is 100, false otherwise)

⚠️ If you cannot clearly extract or calculate all three of the following: price, discount_percent, and discounted_price — then do NOT return anything.

⚠️ Do NOT guess values. Only return a valid JSON object if all required fields are clearly present or calculable.

If the username is a link (e.g. https://t.me/username), extract just the "username" part.

Only return a single JSON object. Do not return a list or multiple JSONs.

Return a strict JSON object with only the fields mentioned above. No explanations, no extra formatting.

Text: "{text}"
"""

# --- Фильтрация по длине и ключевым словам
def should_process(text):
    if not text or len(text) < 50 or len(text) > 2000:
        return False
    keywords = ["скидка", "промокод", "%", "купи", "бесплатно", "акция", "цена", "руб", "₽", "товар"]
    return any(word in text.lower() for word in keywords)

def is_valid_data(d):
    if not isinstance(d, dict):
        return False
    if not d.get("name") or not isinstance(d.get("name"), str) or not d["name"].strip():
        return False
    for field in ["price", "discounted_price", "discount_percent"]:
        val = d.get(field)
        if val is None or not isinstance(val, (int, float)):
            return False
    return True

async def query_ollama(text):
    prompt = PROMPT_TEMPLATE.format(text=text)
    payload = {
        "model": f"{MODEL_NAME}:latest",
        "prompt": prompt,
        "max_tokens": 500,
        "stream": False
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(OLLAMA_API_URL, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            parsed = json.loads(data["response"])
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
            return parsed

def calculate_fingerprint(data):
    keys = ["name", "category", "price", "discounted_price", "discount_percent", "username", "is_free", "image_base64"]
    concat = ''.join(str(data.get(k, '')) for k in keys)
    return hashlib.md5(concat.encode('utf-8')).hexdigest()

def is_duplicate(conn, fingerprint, image_b64):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM product_data WHERE fingerprint = %s OR image_base64 = %s LIMIT 1;", (fingerprint, image_b64))
        return cur.fetchone() is not None

def save_to_postgres(conn, data):
    fingerprint = calculate_fingerprint(data)
    if is_duplicate(conn, fingerprint, data.get("image_base64")):
        return  # дубликат, не сохраняем

    cur = conn.cursor()
    insert_query = """
        INSERT INTO product_data
        (name, category, price, discounted_price, discount_percent, username, is_free, image_base64, fingerprint)
        VALUES %s
    """
    values = [(
        data["name"],
        data.get("category"),
        data["price"],
        data["discounted_price"],
        data["discount_percent"],
        data.get("username"),
        data.get("is_free"),
        data.get("image_base64"),
        fingerprint
    )]
    try:
        execute_values(cur, insert_query, values)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close()

async def main():
    mongo_client = MongoClient(MONGO_URI)
    collection = mongo_client[DB_NAME][COLLECTION_NAME]
    conn = psycopg2.connect(**POSTGRES_CONFIG)

    while True:
        doc = collection.find_one(
            {"parsed": False, "text": {"$exists": True, "$ne": ""}},
            sort=[("date", 1)]
        )

        if not doc:
            await asyncio.sleep(1)
            continue

        text = doc.get("text", "")
        if not should_process(text):
            collection.delete_one({"_id": doc["_id"]})
            continue

        try:
            result = await query_ollama(text)

            image_b64 = None
            if isinstance(doc.get("images"), list) and doc["images"]:
                image_b64 = doc["images"][0]
            elif isinstance(doc.get("image_base64"), str):
                image_b64 = doc["image_base64"]

            if is_valid_data(result):
                if image_b64:
                    result["image_base64"] = image_b64
                save_to_postgres(conn, result)
                collection.update_one({"_id": doc["_id"]}, {"$set": {"parsed": True}})
            else:
                collection.delete_one({"_id": doc["_id"]})
        except Exception:
            collection.delete_one({"_id": doc["_id"]})
            await asyncio.sleep(0.1)

if __name__ == "__main__":
    asyncio.run(main())
