import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Set, List, Tuple
import aiohttp
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
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
ALLOWED_CHAT_IDS = {-1003526710254}

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
    """Форматирует число с эмодзи цифр"""
    emoji_digits = {
        '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
        '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
    }
    return ''.join(emoji_digits[digit] for digit in str(number))


def get_random_viewers() -> int:
    """Случайное число зрителей от 4 до 20"""
    return random.randint(4, 20)


async def take_screenshot(streamer_login: str, stream_info: dict) -> str:
    """Делает скриншот стрима с проверкой на валидность"""
    try:
        # Пробуем несколько вариантов URL
        urls_to_try = []
        
        # Вариант 1: стандартное превью Twitch
        thumbnail_url = stream_info.get('thumbnail_url')
        if thumbnail_url:
            urls_to_try.append(thumbnail_url)
        
        # Вариант 2: превью с другим размером
        urls_to_try.append(f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{streamer_login}-640x360.jpg")
        
        # Вариант 3: превью с высоким качеством
        urls_to_try.append(f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{streamer_login}-1920x1080.jpg")
        
        # Вариант 4: используем API для получения превью
        urls_to_try.append(f"https://api.twitch.tv/helix/streams?user_login={streamer_login}")
        
        filename = SCREENSHOTS_DIR / f"{streamer_login}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        
        async with aiohttp.ClientSession() as session:
            for url in urls_to_try:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            content_type = response.headers.get('Content-Type', '')
                            
                            # Проверяем, что это изображение, а не заглушка
                            if 'image' in content_type:
                                image_data = await response.read()
                                
                                # Проверяем, что размер изображения больше 10KB (заглушка обычно меньше)
                                if len(image_data) > 10000:
                                    with open(filename, 'wb') as f:
                                        f.write(image_data)
                                    logger.info(f"✅ Скриншот сохранен: {filename} (размер: {len(image_data)} байт)")
                                    return str(filename)
                                else:
                                    logger.warning(f"Скриншот слишком маленький ({len(image_data)} байт), пробуем следующий URL")
                            else:
                                logger.warning(f"Не изображение: {content_type}")
                    except asyncio.TimeoutError:
                        logger.warning(f"Таймаут при загрузке {url}")
                    except Exception as e:
                        logger.warning(f"Ошибка при загрузке {url}: {e}")
                
                # Небольшая пауза между попытками
                await asyncio.sleep(0.5)
        
        # Если не удалось загрузить нормальный скриншот, возвращаем None
        logger.error(f"Не удалось загрузить валидный скриншот для {streamer_login}")
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
    """Форматирует текст уведомления в нужном стиле"""
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
    """Проверяет активные стримы"""
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
    """Отправляет уведомление со скриншотом"""
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
        if screenshot_path and Path(screenshot_path).exists():
            # Проверяем размер файла перед отправкой
            file_size = Path(screenshot_path).stat().st_size
            if file_size > 10000:  # Если файл больше 10KB
                with open(screenshot_path, 'rb') as photo:
                    message = await bot.send_photo(
                        chat_id=chat_id,
                        photo=types.FSInputFile(screenshot_path),
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                        disable_notification=True,
                    )
                logger.info(f"✅ Отправлено уведомление со скриншотом для {streamer_login}")
                await delete_screenshot(screenshot_path)
            else:
                logger.warning(f"Скриншот слишком маленький ({file_size} байт), отправляю без фото")
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_notification=True,
                    disable_web_page_preview=False,
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
            logger.info(f"✅ Отправлено текстовое уведомление для {streamer_login}")
        
        return {
            "message_id": message.message_id,
            "chat_id": chat_id,
            "stream_info": stream_info,
            "random_viewers": random_viewers
        }
    except Exception as e:
        logger.error(f"❌ Ошибка отправки сообщения: {e}")
        if screenshot_path:
            await delete_screenshot(screenshot_path)
        return None


async def delete_stream_notification(chat_id: int, message_id: int):
    """Удаляет сообщение о стриме"""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"🗑️ Удалено сообщение о завершившемся стриме")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении сообщения: {e}")
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


# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    if message.chat.id not in ALLOWED_CHAT_IDS:
        await message.answer("⛔ Этот бот не предназначен для использования в этом чате.")
        return

    text = (
        "🤖 <b>Бот для отслеживания стримов на Twitch</b>\n\n"
        "Я буду присылать уведомления, когда кто-то из списка стримеров начнет стрим.\n\n"
        "✨ <b>Особенности:</b>\n"
        "• 📸 Уведомления приходят со скриншотом стрима\n"
        "• 🎲 Рандомное количество зрителей (4-20) для привлечения внимания\n"
        "• 🗑️ Сообщение автоматически удаляется после окончания стрима\n"
        "• 🔕 Все уведомления БЕЗ ЗВУКА\n\n"
        f"📋 Отслеживается стримеров: {len(STREAMERS_TO_TRACK)}\n"
        f"🕒 Интервал проверки: {CHECK_INTERVAL} сек.\n\n"
        "Используйте:\n"
        "/list — список стримеров\n"
        "/status — статус бота\n"
        "/help — помощь"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("list"))
async def cmd_list(message: Message):
    """Показывает список отслеживаемых стримеров"""
    if message.chat.id not in ALLOWED_CHAT_IDS:
        return

    await message.answer("🔄 Получаю список стримеров...")
    
    active_streams = await check_streams()
    active_logins = set(active_streams.keys())

    text = "📋 <b>Список отслеживаемых стримеров:</b>\n\n"
    for login in STREAMERS_TO_TRACK:
        status = "🟢 В ЭФИРЕ" if login in active_logins else "⚫ Не в эфире"
        notified = " (🔔 уведомление отправлено)" if login in notified_streamers else ""
        text += f"• {login} — {status}{notified}\n"

    if len(text) > 4000:
        text = text[:4000] + "\n\n... и другие"

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Показывает текущий статус бота"""
    if message.chat.id not in ALLOWED_CHAT_IDS:
        return

    await message.answer("🔄 Проверяю статус стримов...")
    
    active_streams = await check_streams()
    live_count = len(active_streams)

    text = (
        "📊 <b>Статус бота</b>\n\n"
        f"🎯 Отслеживается стримеров: {len(STREAMERS_TO_TRACK)}\n"
        f"🔴 Сейчас в эфире: {live_count}\n"
        f"🔔 Активных уведомлений: {len(notified_streamers)}\n"
        f"⏱️ Интервал проверки: {CHECK_INTERVAL} сек.\n"
        f"🎲 Режим зрителей: Рандом (4-20)\n"
        f"📸 Скриншоты: Включены\n"
        f"🗑️ Автоудаление: Включено\n"
    )

    if active_streams:
        text += "\n<b>Сейчас в эфире:</b>\n"
        for login, info in active_streams.items():
            text += f"• {info['user_name']} — {info['game_name']}\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Показывает справку"""
    if message.chat.id not in ALLOWED_CHAT_IDS:
        return
    
    text = (
        "📖 <b>Доступные команды:</b>\n\n"
        "/start — Начало работы и информация о боте\n"
        "/list — Показать список отслеживаемых стримеров\n"
        "/status — Текущий статус (кто в онлайне)\n"
        "/help — Эта справка\n\n"
        "🔕 Все уведомления приходят <b>БЕЗ ЗВУКА</b>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


# ========== ЗАПУСК ==========
async def main():
    # Очищаем папку со скриншотами при старте
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
