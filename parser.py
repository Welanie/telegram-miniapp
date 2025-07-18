import os
import json
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat

from pymongo import MongoClient

from config import CONFIG, logger
import base64
import io


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(i) for i in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    elif hasattr(obj, 'to_dict'):
        return sanitize(obj.to_dict())
    elif hasattr(obj, '__dict__'):
        return sanitize(vars(obj))
    elif isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    else:
        return str(obj)


class TelegramMonitor:
    def __init__(self):
        self.client = None
        self.last_messages = {}
        self.ads_ids = set()
        self.feedback_ids = set()
        self.mongo_client = MongoClient(CONFIG['mongo_uri'])
        self.mongo_db = self.mongo_client[CONFIG['mongo_db']]

    async def start(self):
        self.client = TelegramClient(
            f'session_{CONFIG["phone"]}',
            CONFIG['api_id'],
            CONFIG['api_hash']
        )
        await self.client.connect()

        if not await self.client.is_user_authorized():
            await self.client.send_code_request(CONFIG['phone'])
            code = input("Введите код из Telegram: ")
            await self.client.sign_in(CONFIG['phone'], code)

    async def show_subscribed_channels(self):
        dialogs = await self.client.get_dialogs()
        chats = [
            dialog.entity for dialog in dialogs
            if isinstance(dialog.entity, (Channel, Chat)) and not dialog.is_user
        ]

        if not chats:
            print("Нет доступных каналов или групп.")
            return None

        print("\nДоступные каналы и группы:")
        for idx, chat in enumerate(chats, start=1):
            title = getattr(chat, 'title', 'Без названия')
            username = getattr(chat, 'username', None)
            url = f"t.me/{username}" if username else f"ID: {chat.id}"
            print(f"{idx}. {title} ({url})")

        return chats

    async def select_category_channels(self, channels, label):
        while True:
            try:
                print(f"\nВыберите каналы и группы для категории: {label}")
                choice = input("Введите номера через запятую (или 0 для всех): ").strip()
                if choice == '0':
                    selected = channels
                else:
                    indices = [int(x.strip()) - 1 for x in choice.split(',') if x.strip().isdigit()]
                    selected = [channels[i] for i in indices if 0 <= i < len(channels)]

                if not selected:
                    raise ValueError

                print(f"\n✅ Вы выбрали для '{label}':")
                for chat in selected:
                    title = getattr(chat, 'title', 'Без названия')
                    print(f"• {title}")

                return selected
            except (ValueError, IndexError):
                print("❌ Некорректный ввод. Попробуйте снова.")

    @staticmethod
    def serialize_message(message):
        peer = message.peer_id
        if hasattr(peer, 'channel_id'):
            chat_id = peer.channel_id
        elif hasattr(peer, 'chat_id'):
            chat_id = peer.chat_id
        elif hasattr(peer, 'user_id'):
            chat_id = peer.user_id
        else:
            chat_id = None

        chat = message.chat
        return {
            "id": message.id,
            "chat_id": chat_id,
            "chat_title": getattr(chat, 'title', None) if chat else None,
            "chat_username": getattr(chat, 'username', None) if chat else None,
            "date": message.date.astimezone(timezone(timedelta(hours=2))).strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": int(message.date.timestamp()),
            "text": message.text,
            "raw": sanitize(message.to_dict())
        }

    async def save_message(self, message):
        try:
            chat = message.chat
            if chat is None and message.peer_id:
                try:
                    chat = await self.client.get_entity(message.peer_id)
                except Exception as e:
                    logger.error(f"Не удалось получить чат: {e}")
                    return None

            if chat is None:
                return None

            chat_key = (getattr(chat, 'id', None), type(chat))

            if chat_key in self.ads_ids:
                category = 'ads'
            elif chat_key in self.feedback_ids:
                category = 'feedback'
            else:
                return None

            message_data = self.serialize_message(message)
            message_data["parsed"] = False  # ✅ Флаг для будущей обработки

            # ✅ Попытка сохранить изображение, если оно есть
            if message.media:
                try:
                    image_bytes = await message.download_media(bytes)
                    if image_bytes:
                        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                        message_data["image_base64"] = image_b64
                except Exception as img_err:
                    logger.warning(f"⚠️ Не удалось скачать изображение: {img_err}")

            collection = self.mongo_db[category]
            collection.insert_one(message_data)

            return True

        except Exception as e:
            logger.error(f"Ошибка при сохранении сообщения: {e}")
            return None

    async def track_new_messages(self, channels):
        print("\n✔ Мониторинг активен. Новые сообщения:")

        for channel in channels:
            last_msg = await self.client.get_messages(channel, limit=1)
            if last_msg:
                self.last_messages[channel.id] = last_msg[0].id

        @self.client.on(events.NewMessage(chats=channels))
        async def handler(event):
            try:
                if event.chat_id not in self.last_messages or event.message.id > self.last_messages[event.chat_id]:
                    self.last_messages[event.chat_id] = event.message.id
                    saved = await self.save_message(event.message)
                    if not saved:
                        logger.error("Ошибка сохранения сообщения")
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}")

        await self.client.run_until_disconnected()

    async def stop(self):
        await self.client.disconnect()
