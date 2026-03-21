import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from typing import Dict, Set, List, Tuple
import aiohttp
from pathlib import Path
import subprocess

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties

# ========== КОНФИГУРАЦИЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("API_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN")))
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "qrte5j12uko0ue35ntrd4fg6e1v1la")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "c11it5b6eop696b2ewc50d7zd3umfa")

# Список стримеров (можно задать через переменную окружения)
STREAMERS_ENV = os.getenv("STREAMERS_TO_TRACK", "")
if STREAMERS_ENV:
    STREAMERS_TO_TRACK = [s.strip() for s in STREAMERS_ENV.split(",")]
else:
    STREAMERS_TO_TRACK = [
        "ke7oo", "knox_pl1y", "ne3enit", "nct2g", "griz_lgn", "nori_mr",
        "d00mt4k3r", "Tommy_Wer", "relaic67", "T1roff", "capybarchik_play",
        "Blhite4", "mushkanaushko", "Party4cH", "mrwolfek", "CatAClysm_OG",
        "maps_ik", "kykuryka", "GomeoStazIk", "korjik14_", "megushevskiy",
        "DenFv", "snr_slayman", "endiekey__", "Xypmah", "nolfiuu", "NorLiv",
        "0TV3CHAU", "art_mine", "Ehnenra__", "Zephyr_OK", "relight92",
        "windermake", "FireLegendik", "ILIADOD"
    ]

# ID чата (можно задать через переменную окружения)
ALLOWED_CHATS_ENV = os.getenv("ALLOWED_CHAT_IDS", "")
if ALLOWED_CHATS_ENV:
    ALLOWED_CHAT_IDS = {int(cid.strip()) for cid in ALLOWED_CHATS_ENV.split(",")}
else:
    ALLOWED_CHAT_IDS = {1689060454}  # Ваш ID

# Интервалы
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
GIF_UPDATE_INTERVAL = int(os.getenv("GIF_UPDATE_INTERVAL", "300"))

# Настройки прокси (если нужен)
PROXY_URL = os.getenv("PROXY_URL", None)

# Директория для данных
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
TEMP_DIR = DATA_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
notified_streamers: Dict[str, dict] = {}
twitch_access_token = None
token_expires_at = None
last_gif_update = {}

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_bot_session():
    """Создает сессию для бота"""
    session_params = {
        "timeout": aiohttp.ClientTimeout(total=60, connect=30),
        "connector": aiohttp.TCPConnector(
            ssl=False,
            limit=10,
            force_close=True,
            enable_cleanup_closed=True,
            ttl_dns_cache=300
        )
    }
    
    if PROXY_URL:
        session_params["proxy"] = PROXY_URL
        logger.info(f"Используется прокси: {PROXY_URL}")
    
    return AiohttpSession(**session_params)


# Создаем сессию и бота
session = create_bot_session()
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


def format_number_with_emoji(number: int) -> str:
    """Форматирует число с эмодзи цифр"""
    emoji_digits = {
        '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
        '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
    }
    return ''.join(emoji_digits[digit] for digit in str(number))


def get_random_viewers() -> int:
    return random.randint(4, 20)


async def create_gif_from_url(url: str, output_path: str, duration: int = 3, fps: int = 8) -> bool:
    """Создает GIF из URL"""
    try:
        frames_dir = TEMP_DIR / f"frames_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        frames_dir.mkdir(exist_ok=True)
        
        frames = []
        connector = aiohttp.TCPConnector(ssl=False)
        
        for i in range(duration * fps):
            frame_url = f"{url}?t={i/fps}"
            
            try:
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(frame_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            frame_path = frames_dir / f"frame_{i:03d}.jpg"
                            with open(frame_path, 'wb') as f:
                                f.write(await response.read())
                            frames.append(str(frame_path))
            except Exception as e:
                logger.warning(f"Ошибка загрузки кадра {i}: {e}")
        
        if len(frames) < 2:
            if frames:
                import shutil
                shutil.copy(frames[0], output_path)
                return True
            return False
        
        # Проверяем ffmpeg
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except:
            if frames:
                import shutil
                shutil.copy(frames[0], output_path)
                return True
            return False
        
        # Создаем GIF
        cmd = [
            'ffmpeg', '-framerate', str(fps), '-pattern_type', 'glob',
            '-i', f'{frames_dir}/frame_*.jpg',
            '-vf', 'scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse',
            '-loop', '0', '-y', output_path
        ]
        
        subprocess.run(cmd, capture_output=True)
        return Path(output_path).exists()
        
    except Exception as e:
        logger.error(f"Ошибка создания GIF: {e}")
        return False
    finally:
        try:
            for frame in frames:
                Path(frame).unlink()
            frames_dir.rmdir()
        except:
            pass


async def create_stream_gif(streamer_login: str, stream_info: dict, timestamp: bool = True) -> str:
    """Создает GIF из превью стрима"""
    try:
        thumbnail_url = stream_info.get('thumbnail_url')
        if not thumbnail_url:
            thumbnail_url = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{streamer_login}-640x360.jpg"
        
        if timestamp:
            filename = TEMP_DIR / f"{streamer_login}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.gif"
        else:
            filename = TEMP_DIR / f"{streamer_login}_current.gif"
        
        await create_gif_from_url(thumbnail_url, str(filename))
        return str(filename) if filename.exists() else None
    except Exception as e:
        logger.error(f"Ошибка создания GIF: {e}")
        return None


async def delete_temp_file(filepath: str):
    try:
        if filepath and Path(filepath).exists():
            Path(filepath).unlink()
    except:
        pass


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

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    data = await response.json()
                    twitch_access_token = data["access_token"]
                    expires_in = data.get("expires_in", 3600)
                    token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                    logger.info("Twitch token получен")
                    return twitch_access_token
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
        connector = aiohttp.TCPConnector(ssl=False)
        
        for i in range(0, len(STREAMERS_TO_TRACK), 100):
            batch = STREAMERS_TO_TRACK[i:i + 100]
            
            url = "https://api.twitch.tv/helix/streams"
            headers = {
                "Client-ID": TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {token}",
            }
            
            params = [('user_login', login) for login in batch]
            
            async with aiohttp.ClientSession(connector=connector) as session:
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
        return all_streams
    except Exception as e:
        logger.error(f"Ошибка проверки стримов: {e}")
        return {}


async def send_stream_notification(chat_id: int, streamer_login: str, stream_info: dict):
    random_viewers = get_random_viewers()
    text = format_notification_text(streamer_login, stream_info, random_viewers)
    gif_path = await create_stream_gif(streamer_login, stream_info, timestamp=True)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Смотреть на Twitch", url=f"https://twitch.tv/{streamer_login}")]
        ]
    )
    
    try:
        if gif_path and Path(gif_path).exists():
            message = await bot.send_animation(
                chat_id=chat_id,
                animation=types.FSInputFile(gif_path),
                caption=text,
                reply_markup=keyboard,
                disable_notification=True,
            )
        else:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                disable_notification=True,
            )
        
        return {
            "message_id": message.message_id,
            "chat_id": chat_id,
            "stream_info": stream_info,
            "current_gif": gif_path
        }
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        if gif_path:
            await delete_temp_file(gif_path)
        return None


async def delete_stream_notification(chat_id: int, message_id: int, gif_path: str = None):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        if gif_path:
            await delete_temp_file(gif_path)
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")


# ========== ФОНОВЫЕ ЗАДАЧИ ==========
async def check_streams_task():
    logger.info("🚀 Запущена проверка стримов")
    await asyncio.sleep(5)

    while True:
        try:
            active_streams = await check_streams()
            active_logins = set(active_streams.keys())

            for login in STREAMERS_TO_TRACK:
                is_live = login in active_logins
                was_notified = login in notified_streamers

                if is_live and not was_notified:
                    logger.info(f"🔴 СТРИМ НАЧАЛСЯ: {login}")
                    for chat_id in ALLOWED_CHAT_IDS:
                        result = await send_stream_notification(chat_id, login, active_streams[login])
                        if result:
                            notified_streamers[login] = result

                elif not is_live and was_notified:
                    logger.info(f"⚫ СТРИМ ЗАКОНЧИЛСЯ: {login}")
                    stream_data = notified_streamers[login]
                    await delete_stream_notification(
                        stream_data["chat_id"],
                        stream_data["message_id"],
                        stream_data.get("current_gif")
                    )
                    del notified_streamers[login]

        except Exception as e:
            logger.error(f"Ошибка в задаче: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def update_gifs_task():
    """Фоновая задача для обновления GIF"""
    logger.info("🎬 Запущена задача обновления GIF")
    await asyncio.sleep(10)
    
    while True:
        try:
            if notified_streamers:
                for login, stream_data in list(notified_streamers.items()):
                    last_update = last_gif_update.get(login)
                    if last_update and (datetime.now() - last_update).seconds >= GIF_UPDATE_INTERVAL:
                        logger.info(f"🎬 Обновляю GIF для {login}")
                        active_streams = await check_streams()
                        if login in active_streams:
                            new_gif = await create_stream_gif(login, active_streams[login], timestamp=False)
                            if new_gif:
                                random_viewers = get_random_viewers()
                                text = format_notification_text(login, active_streams[login], random_viewers)
                                
                                keyboard = InlineKeyboardMarkup(
                                    inline_keyboard=[
                                        [InlineKeyboardButton(
                                            text="🎬 Смотреть на Twitch",
                                            url=f"https://twitch.tv/{login}"
                                        )]
                                    ]
                                )
                                
                                try:
                                    with open(new_gif, 'rb') as gif:
                                        await bot.edit_message_media(
                                            chat_id=stream_data["chat_id"],
                                            message_id=stream_data["message_id"],
                                            media=InputMediaPhoto(
                                                media=types.FSInputFile(new_gif),
                                                caption=text
                                            ),
                                            reply_markup=keyboard
                                        )
                                    
                                    old_gif = stream_data.get('current_gif')
                                    if old_gif and old_gif != new_gif:
                                        await delete_temp_file(old_gif)
                                    
                                    stream_data['current_gif'] = new_gif
                                    last_gif_update[login] = datetime.now()
                                except Exception as e:
                                    logger.error(f"Ошибка обновления GIF: {e}")
        except Exception as e:
            logger.error(f"Ошибка в задаче обновления GIF: {e}", exc_info=True)
        
        await asyncio.sleep(GIF_UPDATE_INTERVAL)


# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.id not in ALLOWED_CHAT_IDS:
        await message.answer("⛔ Доступ запрещен")
        return
    
    await message.answer(
        f"🤖 Бот запущен!\n\n"
        f"📋 Отслеживается стримеров: {len(STREAMERS_TO_TRACK)}\n"
        f"🕒 Интервал проверки: {CHECK_INTERVAL} сек.\n"
        f"🎬 GIF обновляются каждые {GIF_UPDATE_INTERVAL // 60} мин.\n\n"
        f"Используйте /status для проверки статуса"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if message.chat.id not in ALLOWED_CHAT_IDS:
        return
    
    active_streams = await check_streams()
    
    text = (
        f"📊 Статус бота\n\n"
        f"🎯 Отслеживается: {len(STREAMERS_TO_TRACK)} стримеров\n"
        f"🔴 Сейчас в эфире: {len(active_streams)}\n"
        f"🔔 Активных уведомлений: {len(notified_streamers)}\n"
    )
    
    if active_streams:
        text += "\n🟢 Сейчас в эфире:\n"
        for login in active_streams:
            text += f"• {login}\n"
    
    await message.answer(text)


# ========== ЗАПУСК ==========
async def main():
    # Проверяем наличие токена
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN")
        return
    
    logger.info(f"🤖 Бот запущен. Отслеживается {len(STREAMERS_TO_TRACK)} стримеров")
    logger.info(f"📁 Директория данных: {DATA_DIR}")
    
    # Запускаем фоновые задачи
    asyncio.create_task(check_streams_task())
    asyncio.create_task(update_gifs_task())
    
    # Запускаем polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
