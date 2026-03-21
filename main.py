import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Set, List, Tuple
import aiohttp
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.enums import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8528588588:AAHU9n281SgZM64nbAwNtjWL4RriVRYO-yc"
TWITCH_CLIENT_ID = "qrte5j12uko0ue35ntrd4fg6e1v1la"
TWITCH_CLIENT_SECRET = "d4ohqyd0eyihepbn1ib9gvo8ooibge"

STREAMERS_TO_TRACK = [
    "ke7oo", "knox_pl1y", "ne3enit", "nct2g", "griz_lgn", "nori_mr",
    "d00mt4k3r", "Tommy_Wer", "relaic67", "T1roff", "capybarchik_play",
    "Blhite4", "mushkanaushko", "Party4cH", "mrwolfek", "CatAClysm_OG",
    "maps_ik", "kykuryka", "GomeoStazIk", "korjik14_", "megushevskiy",
    "DenFv", "snr_slayman", "endiekey__", "Xypmah", "nolfiuu", "NorLiv",
    "0TV3CHAU", "art_mine", "Ehnenra__", "Zephyr_OK", "relight92",
    "windermake", "FireLegendik", "ILIADOD"
]
ALLOWED_CHAT_IDS = {1689060454}

CHECK_INTERVAL = 30

SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)

notified_streamers: Dict[str, dict] = {}
twitch_access_token = None
token_expires_at = None

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def format_number_with_emoji(number: int) -> str:
    emoji_digits = {
        '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
        '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
    }
    return ''.join(emoji_digits[digit] for digit in str(number))


def get_random_viewers() -> int:
    """смешнявка с рандомными зрителями"""
    return random.randint(4, 20)


async def take_screenshot(streamer_login: str, stream_info: dict) -> str:
    """Делает скриншот стрима"""
    try:
        thumbnail_url = stream_info.get('thumbnail_url')
        if not thumbnail_url:
            thumbnail_url = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{streamer_login}-640x360.jpg"

        filename = SCREENSHOTS_DIR / f"{streamer_login}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail_url) as response:
                if response.status == 200:
                    with open(filename, 'wb') as f:
                        f.write(await response.read())
                    logger.info(f"Скриншот сохранен: {filename}")
                    return str(filename)
                else:
                    logger.error(f"Не удалось загрузить скриншот: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Ошибка при создании скриншота: {e}")
        return None


async def delete_screenshot(filepath: str):
    """Удаляет файл скриншота"""
    try:
        if filepath and Path(filepath).exists():
            Path(filepath).unlink()
            logger.info(f"Удален скриншот: {filepath}")
    except Exception as e:
        logger.error(f"Ошибка при удалении скриншота {filepath}: {e}")


def format_notification_text(streamer_login: str, stream_info: dict, random_viewers: int) -> str:
    title = stream_info['title']
    game_name = stream_info['game_name']
    
    formatted_viewers = format_number_with_emoji(random_viewers)
    
    text = (
        f"🔴 Стрим <b>«{title}»</b> уже идёт!\n"
        f"Категория: {game_name}\n\n"
        f"{formatted_viewers} зрителей на стриме. Не хватает только тебя!\n\n"
        f"Там чот интересное происходит\n"
        f"<a href='https://twitch.tv/{streamer_login}'>https://twitch.tv/{streamer_login}</a>"
    )
    
    return text


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
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    data = await response.json()
                    twitch_access_token = data["access_token"]
                    expires_in = data.get("expires_in", 3600)
                    token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                    logger.info(f"Twitch token получен")
                    return twitch_access_token
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка получения токена. Статус: {response.status}, Ответ: {error_text}")
                    return None
    except Exception as e:
        logger.error(f"Ошибка при получении токена Twitch: {e}")
        return None


async def check_streams() -> Dict[str, dict]:
    """Проверяет актив"""
    token = await get_twitch_token()
    if not token:
        logger.error("Нет токена для доступа к Twitch API")
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
            
            params: List[Tuple[str, str]] = []
            for login in batch:
                params.append(('user_login', login))
            
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
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка Twitch API {response.status}: {error_text}")
                        return {}
                        
        return all_streams
    except Exception as e:
        logger.error(f"Ошибка при проверке стримов: {e}")
        return {}


# ========== ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЯ ==========
async def send_stream_notification(chat_id: int, streamer_login: str, stream_info: dict):
    
    random_viewers = get_random_viewers()
    text = format_notification_text(streamer_login, stream_info, random_viewers)

    screenshot_path = await take_screenshot(streamer_login, stream_info)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🎬 Смотреть на Twitch",
                url=f"https://twitch.tv/{streamer_login}"
            )]
        ]
    )
    
    try:
        if screenshot_path:
            with open(screenshot_path, 'rb') as photo:
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=types.FSInputFile(screenshot_path),
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_notification=True,
                )
            await delete_screenshot(screenshot_path)
        else:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_notification=True,
                disable_web_page_preview=False,
            )
        
        logger.info(f"✅ Отправлено уведомление о стриме {streamer_login} (сообщение ID: {message.message_id})")
        
        # Сохраняем ID сообщения что бы удобно потом удалить эту парашу
        return {
            "message_id": message.message_id,
            "chat_id": chat_id,
            "stream_info": stream_info,
            "random_viewers": random_viewers
        }
    except Exception as e:
        logger.error(f"❌ Ошибка отправки сообщения: {e}")
        return None


async def delete_stream_notification(chat_id: int, message_id: int):
    """Удаляет сообщение о стриме"""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"🗑️ Удалено сообщение {message_id} о завершившемся стриме")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении сообщения {message_id}: {e}")
        return False


# ========== ФОНОВАЯ ЗАДАЧА ПРОВЕРКИ ==========
async def check_streams_task():
    logger.info("🚀 Запущена фоновая задача проверки стримов")
    
    await asyncio.sleep(5)

    while True:
        try:
            logger.info("🔍 Начинаю проверку стримов...")
            active_streams = await check_streams()
            active_logins = set(active_streams.keys())
            
            logger.info(f"Активные стримы: {active_logins}")
            logger.info(f"Уведомленные стримеры: {list(notified_streamers.keys())}")
            for login in STREAMERS_TO_TRACK:
                is_live = login in active_logins
                was_notified = login in notified_streamers

                # Стример начал стрим
                if is_live and not was_notified:
                    stream_info = active_streams[login]
                    logger.info(f"🔴 СТРИМ НАЧАЛСЯ: {login}")
                    for chat_id in ALLOWED_CHAT_IDS:
                        result = await send_stream_notification(chat_id, login, stream_info)
                        if result:
                            notified_streamers[login] = result

                # Стример закончил стрим
                elif not is_live and was_notified:
                    logger.info(f"⚫ СТРИМ ЗАКОНЧИЛСЯ: {login}")
                    stream_data = notified_streamers[login]
                    await delete_stream_notification(
                        chat_id=stream_data["chat_id"],
                        message_id=stream_data["message_id"]
                    )

                    del notified_streamers[login]

        except Exception as e:
            logger.error(f"❌ Ошибка в фоновой задаче: {e}", exc_info=True)

        logger.info(f"💤 Следующая проверка через {CHECK_INTERVAL} секунд")
        await asyncio.sleep(CHECK_INTERVAL)





async def main():
    for file in SCREENSHOTS_DIR.glob("*.jpg"):
        try:
            file.unlink()
        except:
            pass
    
    asyncio.create_task(check_streams_task())
    logger.info("🤖 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
