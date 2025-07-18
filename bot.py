import asyncio
import asyncpg
import json
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

API_TOKEN = "8021392576:AAHHUo6BH2l9kgHdEsN5Bljzd31RUfYyNn8"
MINI_APP_URL = "https://welanie.github.io/telegram-miniapp/"
POSTGRES_CONFIG = {
    "user": "yan",
    "password": "12345",
    "host": "localhost",
    "port": 5432,
    "database": "TTGFiltered"
}

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

web_app_button = KeyboardButton(
    text="🚀 Открыть Mini App",
    web_app=WebAppInfo(url=MINI_APP_URL)
)
main_menu = ReplyKeyboardMarkup(
    keyboard=[[web_app_button]],
    resize_keyboard=True
)

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(**POSTGRES_CONFIG)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_users (
                id BIGINT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                user_data JSONB
            );
        """)

async def save_user_to_db(user):
    user_data = {
        "id": user.id,
        "is_bot": user.is_bot,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
        "language_code": user.language_code,
        "is_premium": user.is_premium
    }
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO telegram_users (id, first_name, last_name, user_data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE
            SET first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                user_data = EXCLUDED.user_data;
        """, user.id, user.first_name, user.last_name, json.dumps(user_data))

async def get_all_users():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, user_data FROM telegram_users")
    return {
        str(row['id']): json.loads(row['user_data']).get('username', f"id:{row['id']}")
        for row in rows
    }

@dp.message(Command("start"))
async def start_handler(message: Message):
    user = message.from_user
    await save_user_to_db(user)
    await message.answer(
        f"Привет, {user.first_name or 'друг'}!\n"
        "Нажми кнопку ниже, чтобы открыть Mini App 👇",
        reply_markup=main_menu
    )

@dp.message(Command("users"))
async def users_command(message: Message):
    users = await get_all_users()
    if not users:
        await message.answer("Список пользователей пуст.")
        return
    text = "👥 Пользователи:\n"
    for uid, uname in users.items():
        text += f"{uid}: @{uname}\n"
    await message.answer(text)

@dp.message(Command("send"))
async def send_command(message: Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❗ Пример: /send 123456789 Привет!")
        return
    parts = args.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("❗ Формат: /send <user_id> <сообщение>")
        return
    user_id_str, text = parts
    users = await get_all_users()
    if user_id_str not in users:
        await message.answer("❌ Такой пользователь не найден.")
        return
    try:
        await bot.send_message(chat_id=int(user_id_str), text=text)
        await message.answer(f"✅ Сообщение отправлено @{users[user_id_str]}")
    except Exception as e:
        await message.answer(f"Ошибка при отправке: {e}")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
