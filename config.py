import os
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    'api_id': int(os.getenv('API_ID')),
    'api_hash': os.getenv('API_HASH'),
    'phone': os.getenv('PHONE'),
    'mongo_uri': os.getenv('MONGO_URI', 'mongodb://localhost:27017'),
    'mongo_db': os.getenv('MONGO_DB', 'telegram_monitor'),
}


