import asyncio
from parser import TelegramMonitor


async def main():
    monitor = TelegramMonitor()

    try:
        await monitor.start()

        channels = await monitor.show_subscribed_channels()
        if not channels:
            return

        ads = await monitor.select_category_channels(channels, "Объявления")
        monitor.ads_ids = set((chat.id, type(chat)) for chat in ads)

        feedback = await monitor.select_category_channels(channels, "Отзывы")
        monitor.feedback_ids = set((chat.id, type(chat)) for chat in feedback)

        # Объединяем каналы без дубликатов
        seen_ids = set()
        all_selected = []
        for chat in ads + feedback:
            if chat.id not in seen_ids:
                all_selected.append(chat)
                seen_ids.add(chat.id)

        await monitor.track_new_messages(all_selected)

    except KeyboardInterrupt:
        await monitor.stop()
        print("\n⏹ Мониторинг остановлен")

    except Exception as e:
        print(f"Ошибка: {e}")
        await monitor.stop()


if __name__ == '__main__':
    asyncio.run(main())
