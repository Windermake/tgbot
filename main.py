import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

# Проверка
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

# Список стримеров
STREAMERS_TO_TRACK = ["windermake"]

# ID чата
ALLOWED_CHAT_IDS = {1689060454}

# Интервал проверки
CHECK_INTERVAL = 30

# Глобальные переменные
notified_streamers = set()
twitch_token = None
token_expires = None

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создаем диспетчер
dp = Dispatcher()


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


async def check_streams() -> List[str]:
    token = await get_twitch_token()
    if not token:
        return []
    
    try:
        url = "https://api.twitch.tv/helix/streams"
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}",
        }
        params = [('user_login', login) for login in STREAMERS_TO_TRACK]
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    streams = [s["user_login"] for s in data.get("data", [])]
                    return streams
                return []
    except Exception as e:
        logger.error(f"Ошибка проверки: {e}")
        return []


async def send_notification(bot: Bot, chat_id: int, streamer: str):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Смотреть", url=f"https://twitch.tv/{streamer}")]
        ]
    )
    
    text = f"🔴 Стример {streamer} начал стрим!\n\nhttps://twitch.tv/{streamer}"
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            disable_notification=True,
        )
        logger.info(f"✅ Уведомление отправлено {streamer}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False


async def check_task(bot: Bot):
    logger.info("🚀 Запущена проверка")
    await asyncio.sleep(5)
    
    while True:
        try:
            logger.info("🔍 Проверяю стримы...")
            active = await check_streams()
            logger.info(f"Активные: {active}")
            
            for streamer in STREAMERS_TO_TRACK:
                if streamer in active and streamer not in notified_streamers:
                    logger.info(f"🔴 СТРИМ НАЧАЛСЯ: {streamer}")
                    for chat_id in ALLOWED_CHAT_IDS:
                        success = await send_notification(bot, chat_id, streamer)
                        if success:
                            notified_streamers.add(streamer)
                elif streamer not in active and streamer in notified_streamers:
                    logger.info(f"⚫ СТРИМ ЗАКОНЧИЛСЯ: {streamer}")
                    notified_streamers.remove(streamer)
            
        except Exception as e:
            logger.error(f"Ошибка: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(f"🤖 Бот запущен!\nОтслеживается: {STREAMERS_TO_TRACK}\nИнтервал: {CHECK_INTERVAL} сек")


@dp.message(Command("status"))
async def status(message: Message):
    active = await check_streams()
    await message.answer(f"Активные стримы: {active if active else 'нет'}")


async def main():
    # Проверяем переменные
    logger.info(f"BOT_TOKEN: {'установлен' if BOT_TOKEN else 'НЕ УСТАНОВЛЕН'}")
    logger.info(f"TWITCH_CLIENT_ID: {'установлен' if TWITCH_CLIENT_ID else 'НЕ УСТАНОВЛЕН'}")
    logger.info(f"TWITCH_CLIENT_SECRET: {'установлен' if TWITCH_CLIENT_SECRET else 'НЕ УСТАНОВЛЕН'}")
    
    if not all([BOT_TOKEN, TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET]):
        logger.error("❌ Не все переменные окружения установлены!")
        return
    
    # Создаем бота
    session = AiohttpSession()
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Запускаем проверку
    asyncio.create_task(check_task(bot))
    
    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
