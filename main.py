import asyncio
import logging
import random
import os
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import aiohttp
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("API_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN")))
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "qrte5j12uko0ue35ntrd4fg6e1v1la")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "c11it5b6eop696b2ewc50d7zd3umfa")

# Список стримеров
STREAMERS_TO_TRACK = [
    "windermake",
    "ke7oo", "knox_pl1y", "ne3enit", "nct2g", "griz_lgn", "nori_mr",
    "d00mt4k3r", "Tommy_Wer", "relaic67", "T1roff", "capybarchik_play",
    "Blhite4", "mushkanaushko", "Party4cH", "mrwolfek", "CatAClysm_OG",
    "maps_ik", "kykuryka", "GomeoStazIk", "korjik14_", "megushevskiy",
    "DenFv", "snr_slayman", "endiekey__", "Xypmah", "nolfiuu", "NorLiv",
    "0TV3CHAU", "art_mine", "Ehnenra__", "Zephyr_OK", "relight92",
    "FireLegendik", "ILIADOD"
]

# ID чата
ALLOWED_CHAT_IDS = {1689060454}

# Интервалы
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

# Директория для данных
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
TEMP_DIR = DATA_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
notified_streamers: Dict[str, dict] = {}
twitch_access_token = None
token_expires_at = None
should_stop = False

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def format_number_with_emoji(number: int) -> str:
    """Форматирует число с эмодзи цифр"""
    emoji_digits = {
        '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
        '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
    }
    return ''.join(emoji_digits[digit] for digit in str(number))


def get_random_viewers() -> int:
    return random.randint(4, 20)


def format_notification_text(streamer_login: str, stream_info: dict, random_viewers: int) -> str:
    title = stream_info['title']
    game_name = stream_info['game_name']
    formatted_viewers = format_number_with_emoji(random_viewers)
    
    started_at = stream_info.get('started_at', '')
    time_info = ""
    if started_at:
        try:
            start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            duration = datetime.now() - start_time
            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            time_info = f" (в эфире {hours}ч {minutes}мин)"
        except:
            pass
    
    return (
        f"🔴 Стрим <b>«{title}»</b> уже идёт!{time_info}\n"
        f"Категория: {game_name}\n\n"
        f"{formatted_viewers} зрителей на стриме. Не хватает только тебя!\n\n"
        f"Кто с тг, пишите «сосо».\n"
        f"<a href='https://twitch.tv/{streamer_login}'>https://twitch.tv/{streamer_login}</a>"
    )


# ========== РАБОТА С TWITCH API ==========
async def get_twitch_token() -> str:
    global twitch_access_token, token_expires_at

    if twitch_access_token and token_expires_at and datetime.now() < token_expires_at - timedelta(minutes=10):
        return twitch_access_token

    try:
        url = "https://id.twitch.tv/oauth2/token"
        data = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    twitch_access_token = data["access_token"]
                    expires_in = data.get("expires_in", 3600)
                    token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                    logger.info("✅ Twitch token получен")
                    return twitch_access_token
                logger.error(f"Ошибка получения токена: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка получения токена: {e}")
        return None


async def check_streams() -> Dict[str, dict]:
    token = await get_twitch_token()
    if not token:
        return {}

    try:
        all_streams = {}
        
        for i in range(0, len(STREAMERS_TO_TRACK), 100):
            batch = STREAMERS_TO_TRACK[i:i + 100]
            
            url = "https://api.twitch.tv/helix/streams"
            headers = {
                "Client-ID": TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {token}",
            }
            
            params = [('user_login', login) for login in batch]
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        data = await response.json()
                        for stream in data.get("data", []):
                            login = stream["user_login"]
                            all_streams[login] = {
                                "user_name": stream["user_name"],
                                "title": stream["title"],
                                "game_name": stream["game_name"],
                                "viewer_count": stream["viewer_count"],
                                "started_at": stream["started_at"],
                                "thumbnail_url": stream["thumbnail_url"].format(width=640, height=360) if stream.get("thumbnail_url") else None,
                            }
        return all_streams
    except Exception as e:
        logger.error(f"Ошибка проверки стримов: {e}")
        return {}


async def send_stream_notification(bot: Bot, chat_id: int, streamer_login: str, stream_info: dict):
    """Отправляет уведомление о начале стрима (без GIF)"""
    random_viewers = get_random_viewers()
    text = format_notification_text(streamer_login, stream_info, random_viewers)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Смотреть на Twitch", url=f"https://twitch.tv/{streamer_login}")]
        ]
    )
    
    # Пробуем отправить с ретраями
    max_retries = 3
    for attempt in range(max_retries):
        try:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_notification=True,
                disable_web_page_preview=False,
                request_timeout=30  # Таймаут на отправку
            )
            
            logger.info(f"✅ Отправлено уведомление о стриме {streamer_login}")
            
            return {
                "message_id": message.message_id,
                "chat_id": chat_id,
                "stream_info": stream_info,
                "random_viewers": random_viewers
            }
            
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Таймаут при отправке (попытка {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                logger.error(f"❌ Не удалось отправить уведомление после {max_retries} попыток")
                return None
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return None


async def delete_stream_notification(bot: Bot, chat_id: int, message_id: int):
    """Удаляет сообщение о стриме"""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"🗑️ Удалено сообщение о стриме")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")


# ========== ФОНОВЫЕ ЗАДАЧИ ==========
async def check_streams_task(bot: Bot):
    logger.info("🚀 Запущена проверка стримов")
    await asyncio.sleep(5)

    while not should_stop:
        try:
            logger.info("🔍 Проверяю стримы...")
            active_streams = await check_streams()
            active_logins = set(active_streams.keys())
            
            if active_logins:
                logger.info(f"🎥 Найдены активные стримы: {active_logins}")
            else:
                logger.info("📭 Активных стримов не найдено")

            for login in STREAMERS_TO_TRACK:
                is_live = login in active_logins
                was_notified = login in notified_streamers

                if is_live and not was_notified:
                    logger.info(f"🔴 СТРИМ НАЧАЛСЯ: {login}")
                    for chat_id in ALLOWED_CHAT_IDS:
                        result = await send_stream_notification(bot, chat_id, login, active_streams[login])
                        if result:
                            notified_streamers[login] = result

                elif not is_live and was_notified:
                    logger.info(f"⚫ СТРИМ ЗАКОНЧИЛСЯ: {login}")
                    stream_data = notified_streamers[login]
                    await delete_stream_notification(
                        bot,
                        stream_data["chat_id"],
                        stream_data["message_id"]
                    )
                    del notified_streamers[login]

        except Exception as e:
            logger.error(f"❌ Ошибка в задаче: {e}", exc_info=True)

        logger.info(f"💤 Следующая проверка через {CHECK_INTERVAL} секунд")
        await asyncio.sleep(CHECK_INTERVAL)


# ========== СОЗДАНИЕ ДИСПЕТЧЕРА ==========
dp = Dispatcher()


# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.id not in ALLOWED_CHAT_IDS:
        await message.answer("⛔ Доступ запрещен")
        return
    
    await message.answer(
        f"🤖 Бот запущен!\n\n"
        f"📋 Отслеживается стримеров: {len(STREAMERS_TO_TRACK)}\n"
        f"🕒 Интервал проверки: {CHECK_INTERVAL} сек.\n\n"
        f"Используйте /status для проверки статуса"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if message.chat.id not in ALLOWED_CHAT_IDS:
        return
    
    await message.answer("🔄 Проверяю статус...")
    
    active_streams = await check_streams()
    
    text = (
        f"📊 Статус бота\n\n"
        f"🎯 Отслеживается: {len(STREAMERS_TO_TRACK)} стримеров\n"
        f"🔴 Сейчас в эфире: {len(active_streams)}\n"
        f"🔔 Активных уведомлений: {len(notified_streamers)}\n"
    )
    
    if active_streams:
        text += "\n🟢 Сейчас в эфире:\n"
        for login, info in active_streams.items():
            text += f"• {info['user_name']}\n"
    
    await message.answer(text)


# ========== ЗАПУСК ==========
async def main():
    global should_stop
    
    # Обработка сигналов
    def signal_handler():
        global should_stop
        logger.info("Получен сигнал остановки")
        should_stop = True
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан!")
        return
    
    # Создаем сессию с увеличенными таймаутами
    session = AiohttpSession(
        timeout=aiohttp.ClientTimeout(total=60, connect=30, sock_read=30)
    )
    bot_instance = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    logger.info(f"🤖 Бот запущен. Отслеживается {len(STREAMERS_TO_TRACK)} стримеров")
    logger.info(f"📁 Директория данных: {DATA_DIR}")
    
    # Запускаем фоновую задачу
    asyncio.create_task(check_streams_task(bot_instance))
    
    # Запускаем polling
    try:
        await dp.start_polling(bot_instance)
    except Exception as e:
        logger.error(f"Ошибка в polling: {e}")
    finally:
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
