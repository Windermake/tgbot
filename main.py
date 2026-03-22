import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from typing import Dict, List
import aiohttp
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

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
ALLOWED_CHATS_ENV = os.getenv("ALLOWED_CHAT_IDS", "")
if ALLOWED_CHATS_ENV:
    ALLOWED_CHAT_IDS = {int(cid.strip()) for cid in ALLOWED_CHATS_ENV.split(",")}
else:
    ALLOWED_CHAT_IDS = {1689060454}

# Интервалы
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))

# Директория для данных
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
TEMP_DIR = DATA_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
notified_streamers: Dict[str, dict] = {}
twitch_token = None
token_expires = None

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

dp = Dispatcher()


def format_number_with_emoji(number: int) -> str:
    """Форматирует число с эмодзи цифр"""
    emoji_digits = {
        '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
        '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
    }
    return ''.join(emoji_digits[digit] for digit in str(number))


def get_random_viewers() -> int:
    """Случайное число зрителей от 4 до 20"""
    return random.randint(4, 20)


def format_notification_text(streamer_login: str, stream_info: dict, random_viewers: int) -> str:
    """Форматирует текст уведомления"""
    title = stream_info['title']
    game_name = stream_info['game_name']
    formatted_viewers = format_number_with_emoji(random_viewers)
    
    # Время в эфире
    started_at = stream_info.get('started_at', '')
    time_info = ""
    if started_at:
        try:
            start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            duration = datetime.now() - start_time
            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            if hours > 0:
                time_info = f" (в эфире {hours}ч {minutes}мин)"
            else:
                time_info = f" (в эфире {minutes}мин)"
        except:
            pass
    
    text = (
        f"🔴 Стрим <b>«{title}»</b> уже идёт!{time_info}\n"
        f"Категория: {game_name}\n\n"
        f"{formatted_viewers} зрителей на стриме. Не хватает только тебя!\n\n"
        f"Кто с тг, пишите «сосо».\n"
        f"<a href='https://twitch.tv/{streamer_login}'>https://twitch.tv/{streamer_login}</a>"
    )
    
    return text


# ========== РАБОТА СО СКРИНШОТАМИ ==========
async def take_screenshot(streamer_login: str, stream_info: dict) -> str:
    """Делает скриншот стрима (просто скачивает превью)"""
    try:
        thumbnail_url = stream_info.get('thumbnail_url')
        if not thumbnail_url:
            thumbnail_url = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{streamer_login}-640x360.jpg"
        
        # Добавляем время, чтобы избежать кэширования
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = TEMP_DIR / f"{streamer_login}_{timestamp}.jpg"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    with open(filename, 'wb') as f:
                        f.write(await response.read())
                    logger.info(f"📸 Скриншот сохранен: {filename}")
                    return str(filename)
                else:
                    logger.error(f"Ошибка загрузки скриншота: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Ошибка создания скриншота: {e}")
        return None


async def delete_temp_file(filepath: str):
    """Удаляет временный файл"""
    try:
        if filepath and Path(filepath).exists():
            Path(filepath).unlink()
    except:
        pass


# ========== РАБОТА С TWITCH API ==========
async def get_twitch_token() -> str:
    global twitch_token, token_expires
    
    if twitch_token and token_expires and datetime.now() < token_expires:
        return twitch_token
    
    try:
        url = "https://id.twitch.tv/oauth2/token"
        data = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    data = await response.json()
                    twitch_token = data["access_token"]
                    token_expires = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))
                    logger.info("✅ Twitch token получен")
                    return twitch_token
                else:
                    logger.error(f"Ошибка получения токена: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Ошибка: {e}")
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
                async with session.get(url, headers=headers, params=params) as response:
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
                            logger.info(f"📺 Найден стрим: {login}")
        return all_streams
    except Exception as e:
        logger.error(f"Ошибка проверки стримов: {e}")
        return {}


async def send_stream_notification(bot: Bot, chat_id: int, streamer_login: str, stream_info: dict):
    """Отправляет уведомление со скриншотом"""
    random_viewers = get_random_viewers()
    text = format_notification_text(streamer_login, stream_info, random_viewers)
    screenshot_path = await take_screenshot(streamer_login, stream_info)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Смотреть на Twitch", url=f"https://twitch.tv/{streamer_login}")]
        ]
    )
    
    try:
        if screenshot_path and Path(screenshot_path).exists():
            with open(screenshot_path, 'rb') as photo:
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=types.FSInputFile(screenshot_path),
                    caption=text,
                    reply_markup=keyboard,
                    disable_notification=True,
                )
            logger.info(f"✅ Отправлено уведомление со скриншотом для {streamer_login}")
        else:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                disable_notification=True,
                disable_web_page_preview=False,
            )
            logger.info(f"✅ Отправлено текстовое уведомление для {streamer_login}")
        
        return {
            "message_id": message.message_id,
            "chat_id": chat_id,
            "stream_info": stream_info,
            "current_screenshot": screenshot_path
        }
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        if screenshot_path:
            await delete_temp_file(screenshot_path)
        return None


async def delete_stream_notification(bot: Bot, chat_id: int, message_id: int, screenshot_path: str = None):
    """Удаляет сообщение о стриме"""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        if screenshot_path:
            await delete_temp_file(screenshot_path)
        logger.info(f"🗑️ Удалено сообщение о стриме")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")


# ========== ФОНОВАЯ ЗАДАЧА ==========
async def check_streams_task(bot: Bot):
    logger.info("🚀 Запущена проверка стримов")
    await asyncio.sleep(5)
    
    while True:
        try:
            logger.info("🔍 Проверяю стримы...")
            active_streams = await check_streams()
            active_logins = set(active_streams.keys())
            
            if active_logins:
                logger.info(f"🎥 Активные стримы: {active_logins}")
            else:
                logger.info("📭 Активных стримов нет")
            
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
                        stream_data["message_id"],
                        stream_data.get("current_screenshot")
                    )
                    del notified_streamers[login]
        
        except Exception as e:
            logger.error(f"❌ Ошибка в задаче: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)


# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.id not in ALLOWED_CHAT_IDS:
        await message.answer("⛔ Доступ запрещен")
        return
    
    await message.answer(
        f"🤖 <b>Twitch Stream Monitor</b>\n\n"
        f"📋 Отслеживается: {len(STREAMERS_TO_TRACK)} стримеров\n"
        f"🕒 Интервал проверки: {CHECK_INTERVAL} сек\n\n"
        f"✨ <b>Особенности:</b>\n"
        f"• 📸 Скриншот со стрима\n"
        f"• 🎲 Рандомное количество зрителей (4-20)\n"
        f"• 🔕 Уведомления без звука\n"
        f"• 🗑️ Автоудаление после окончания стрима\n\n"
        f"Используйте /status для проверки статуса"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if message.chat.id not in ALLOWED_CHAT_IDS:
        return
    
    await message.answer("🔄 Проверяю статус...")
    
    active_streams = await check_streams()
    
    text = (
        f"📊 <b>Статус бота</b>\n\n"
        f"🎯 Отслеживается: {len(STREAMERS_TO_TRACK)} стримеров\n"
        f"🔴 Сейчас в эфире: {len(active_streams)}\n"
        f"🔔 Активных уведомлений: {len(notified_streamers)}\n"
        f"⏱️ Интервал: {CHECK_INTERVAL} сек\n"
    )
    
    if active_streams:
        text += "\n🟢 <b>Сейчас в эфире:</b>\n"
        for login, info in active_streams.items():
            text += f"• {info['user_name']} — {info['game_name']}\n"
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Доступные команды:</b>\n\n"
        "/start - Информация о боте\n"
        "/status - Статус стримов\n"
        "/help - Эта справка"
    )


# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 Запуск бота...")
    
    if not all([BOT_TOKEN, TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET]):
        logger.error("❌ Не все переменные окружения установлены!")
        return
    
    session = AiohttpSession()
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    logger.info(f"📁 DATA_DIR: {DATA_DIR}")
    logger.info(f"📋 ALLOWED_CHAT_IDS: {ALLOWED_CHAT_IDS}")
    
    # Запускаем фоновую задачу
    asyncio.create_task(check_streams_task(bot))
    
    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
