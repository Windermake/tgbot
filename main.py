import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Set, List, Tuple, Optional
import aiohttp
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.enums import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8528588588:AAHU9n281SgZM64nbAwNtjWL4RriVRYO-yc"
TWITCH_CLIENT_ID = "qrte5j12uko0ue35ntrd4fg6e1v1la"
TWITCH_CLIENT_SECRET = "ceqt19ttojt3rd3gluamezwn3t6zri"
CHANNEL_ID = "@TCNAREZKI"  # Канал для отправки

# Приводим все логины к нижнему регистру для единообразия
STREAMERS_TO_TRACK = [
    "ke7oo", "knox_pl1y", "ne3enit", "nct2g", "griz_lgn", "nori_mr",
    "d00mt4k3r", "tommy_wer", "relaic67", "t1roff", "capybarchik_play",
    "blhite4", "mushkanaushko", "party4ch", "mrwolfek", "cataclysm_og",
    "maps_ik", "kykuryka", "gomeostazik", "korjik14_", "megushevskiy",
    "denfv", "snr_slayman", "endiekey__", "xypmah", "nolfiuu", "norliv",
    "0tv3chau", "art_mine", "ehnenra__", "zephyr_ok", "relight92",
    "windermake", "firelegendik", "iliadod"
]

CHECK_INTERVAL = 30
SCREENSHOT_UPDATE_INTERVAL = 120

SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# Хранилище активных стримов
notified_streamers: Dict[str, dict] = {}
twitch_access_token = None
token_expires_at = None

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def format_number_with_emoji(number: int) -> str:
    """Форматирует число с эмодзи цифрами"""
    emoji_digits = {
        '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
        '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
    }
    return ''.join(emoji_digits[digit] for digit in str(number))


def get_random_viewers() -> int:
    """Генерирует случайное количество зрителей"""
    return random.randint(4, 20)


async def take_screenshot(streamer_login: str, stream_info: dict) -> Optional[str]:
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
    """Форматирует текст уведомления"""
    title = stream_info['title']
    game_name = stream_info['game_name']
    
    formatted_viewers = format_number_with_emoji(random_viewers)
    
    text = (
        f"❤️ Стрим <b>«{title}»</b> уже идёт! {streamer_login}\n"
        f"Категория: {game_name}\n\n"
        f"{formatted_viewers} зрителей на стриме. Не хватает только тебя!\n\n"
        f"Пишите что вы от ТК ВКУСНО\n"
        f"<a href='https://twitch.tv/{streamer_login}'>https://twitch.tv/{streamer_login}</a>"
    )
    
    return text


# ========== РАБОТА С TWITCH API ==========
async def get_twitch_token() -> Optional[str]:
    """Получает или обновляет токен Twitch"""
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
                    logger.info(f"Twitch token получен, истекает через {expires_in} сек")
                    return twitch_access_token
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка получения токена. Статус: {response.status}, Ответ: {error_text}")
                    return None
    except Exception as e:
        logger.error(f"Ошибка при получении токена Twitch: {e}")
        return None


async def get_stream_info(streamer_login: str) -> Optional[dict]:
    """Получает актуальную информацию о конкретном стримере"""
    token = await get_twitch_token()
    if not token:
        return None

    try:
        url = "https://api.twitch.tv/helix/streams"
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}",
        }
        params = {'user_login': streamer_login.lower()}  # Приводим к нижнему регистру

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    streams = data.get("data", [])
                    if streams:
                        stream = streams[0]
                        return {
                            "user_name": stream["user_name"],
                            "title": stream["title"],
                            "game_name": stream["game_name"],
                            "viewer_count": stream["viewer_count"],
                            "started_at": stream["started_at"],
                            "thumbnail_url": stream["thumbnail_url"].format(width=640, height=360) if stream.get("thumbnail_url") else None,
                        }
                return None
    except Exception as e:
        logger.error(f"Ошибка при получении информации о стримере {streamer_login}: {e}")
        return None


async def check_streams() -> Dict[str, dict]:
    """Проверяет активные стримы"""
    token = await get_twitch_token()
    if not token:
        logger.error("Нет токена для доступа к Twitch API")
        return {}

    all_streams = {}
    
    # Обрабатываем стримеров пачками по 100
    for i in range(0, len(STREAMERS_TO_TRACK), 100):
        batch = STREAMERS_TO_TRACK[i:i + 100]
        
        try:
            url = "https://api.twitch.tv/helix/streams"
            headers = {
                "Client-ID": TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {token}",
            }
            
            params = []
            for login in batch:
                params.append(('user_login', login.lower()))  # Приводим к нижнему регистру
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        for stream in data.get("data", []):
                            login = stream["user_login"].lower()  # Приводим к нижнему регистру
                            all_streams[login] = {
                                "user_name": stream["user_name"],
                                "title": stream["title"],
                                "game_name": stream["game_name"],
                                "viewer_count": stream["viewer_count"],
                                "started_at": stream["started_at"],
                                "thumbnail_url": stream["thumbnail_url"].format(width=640, height=360) if stream.get("thumbnail_url") else None,
                            }
                            logger.info(f"📡 Найден стрим: {login} - {stream['title'][:50]}")
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка Twitch API при проверке пачки: {response.status} - {error_text}")
                        continue
                        
        except Exception as e:
            logger.error(f"Ошибка при проверке пачки стримеров: {e}")
            continue
    
    logger.info(f"Найдено активных стримов: {len(all_streams)}")
    return all_streams


# ========== ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЯ ==========
async def send_stream_notification(chat_id: str, streamer_login: str, stream_info: dict):
    """Отправляет уведомление о начале стрима"""
    
    random_viewers = get_random_viewers()
    text = format_notification_text(streamer_login, stream_info, random_viewers)

    screenshot_path = await take_screenshot(streamer_login, stream_info)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🎬 Смотреть на Твиче",
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
        
        return {
            "message_id": message.message_id,
            "chat_id": chat_id,
            "stream_info": stream_info,
            "random_viewers": random_viewers,
            "last_screenshot_update": datetime.now(),
            "first_detected": datetime.now()
        }
    except Exception as e:
        logger.error(f"❌ Ошибка отправки сообщения: {e}")
        return None


async def update_stream_screenshot(streamer_login: str, notification_data: dict):
    """Обновляет скриншот в сообщении о стриме"""
    try:
        current_stream_info = await get_stream_info(streamer_login)
        if not current_stream_info:
            logger.warning(f"Не удалось получить актуальную информацию о стриме {streamer_login}")
            return False
        
        new_screenshot_path = await take_screenshot(streamer_login, current_stream_info)
        if not new_screenshot_path:
            logger.warning(f"Не удалось создать новый скриншот для {streamer_login}")
            return False
        
        random_viewers = get_random_viewers()
        text = format_notification_text(streamer_login, current_stream_info, random_viewers)
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🎬 Смотреть на Twitch",
                    url=f"https://twitch.tv/{streamer_login}"
                )]
            ]
        )
        
        with open(new_screenshot_path, 'rb') as photo:
            await bot.edit_message_media(
                chat_id=notification_data["chat_id"],
                message_id=notification_data["message_id"],
                media=InputMediaPhoto(
                    media=types.FSInputFile(new_screenshot_path),
                    caption=text,
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=keyboard
            )
        
        await delete_screenshot(new_screenshot_path)
        
        notification_data["stream_info"] = current_stream_info
        notification_data["random_viewers"] = random_viewers
        notification_data["last_screenshot_update"] = datetime.now()
        
        logger.info(f"🖼️ Обновлен скриншот для {streamer_login}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении скриншота для {streamer_login}: {e}")
        return False


async def delete_stream_notification(chat_id: str, message_id: int):
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
    """Фоновая задача проверки стримов"""
    logger.info("🚀 Запущена фоновая задача проверки стримов")
    
    await asyncio.sleep(5)

    while True:
        try:
            logger.info("🔍 Начинаю проверку стримов...")
            active_streams = await check_streams()
            active_logins = set(active_streams.keys())
            
            # Логируем активные стримы
            if active_logins:
                logger.info(f"🔴 Активные стримы: {', '.join(active_logins)}")
            else:
                logger.info("⚫ Нет активных стримов")
            
            # Проверяем каждый стример из списка
            for login in STREAMERS_TO_TRACK:
                login_lower = login.lower()  # Приводим к нижнему регистру для сравнения
                is_live = login_lower in active_logins
                was_notified = login_lower in notified_streamers

                # Стример начал стрим
                if is_live and not was_notified:
                    stream_info = active_streams[login_lower]
                    logger.info(f"🎬 ОБНАРУЖЕН НОВЫЙ СТРИМ: {login_lower} - {stream_info['title'][:50]}")
                    
                    # Отправляем уведомление в канал
                    result = await send_stream_notification(CHANNEL_ID, login_lower, stream_info)
                    if result:
                        notified_streamers[login_lower] = result
                        logger.info(f"✅ Уведомление для {login_lower} успешно отправлено")
                    else:
                        logger.error(f"❌ Не удалось отправить уведомление для {login_lower}")

                # Стример закончил стрим
                elif not is_live and was_notified:
                    logger.info(f"🏁 СТРИМ ЗАКОНЧИЛСЯ: {login_lower}")
                    stream_data = notified_streamers[login_lower]
                    await delete_stream_notification(
                        chat_id=stream_data["chat_id"],
                        message_id=stream_data["message_id"]
                    )
                    del notified_streamers[login_lower]
                    logger.info(f"🗑️ Удалено уведомление для {login_lower}")

            logger.info(f"📊 Статус: {len(notified_streamers)} активных уведомлений")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в фоновой задаче: {e}", exc_info=True)

        logger.info(f"💤 Следующая проверка через {CHECK_INTERVAL} секунд")
        await asyncio.sleep(CHECK_INTERVAL)


# ========== ФОНОВАЯ ЗАДАЧА ОБНОВЛЕНИЯ СКРИНШОТОВ ==========
async def update_screenshots_task():
    """Фоновая задача для обновления скриншотов"""
    logger.info("🖼️ Запущена фоновая задача обновления скриншотов")
    
    await asyncio.sleep(10)
    
    while True:
        try:
            if notified_streamers:
                logger.info(f"🔄 Обновляю скриншоты для {len(notified_streamers)} активных стримов...")
                
                for login, notification_data in list(notified_streamers.items()):
                    time_since_update = datetime.now() - notification_data.get("last_screenshot_update", datetime.min)
                    
                    if time_since_update.total_seconds() >= SCREENSHOT_UPDATE_INTERVAL:
                        logger.info(f"🖼️ Обновляю скриншот для {login}")
                        await update_stream_screenshot(login, notification_data)
            else:
                logger.debug("Нет активных стримов, обновление скриншотов не требуется")
                
        except Exception as e:
            logger.error(f"❌ Ошибка в задаче обновления скриншотов: {e}", exc_info=True)
        
        await asyncio.sleep(30)


# ========== КОМАНДЫ БОТА ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    text = (
        "🤖 <b>Бот для отслеживания стримов на Twitch</b>\n\n"
        "Я буду присылать уведомления в канал @TCNAREZKI, когда кто-то из списка стримеров начнет стрим.\n\n"
        "✨ <b>Особенности:</b>\n"
        "• 🎬 Уведомления приходят со скриншотом стрима\n"
        "• 🔄 Скриншоты обновляются каждые 2 минуты\n"
        "• 🎲 Рандомное количество зрителей (4-20)\n"
        "• 📝 Автообновление названия и категории стрима\n"
        "• 🗑️ Сообщение автоматически удаляется после окончания стрима\n"
        "• 🔕 Все уведомления БЕЗ ЗВУКА\n\n"
        f"📋 Отслеживается стримеров: {len(STREAMERS_TO_TRACK)}\n"
        f"🕒 Интервал проверки: {CHECK_INTERVAL} сек.\n"
        f"🖼️ Интервал обновления скриншотов: {SCREENSHOT_UPDATE_INTERVAL // 60} мин.\n\n"
        "Доступные команды:\n"
        "/list — список стримеров\n"
        "/status — статус бота"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("list"))
async def cmd_list(message: Message):
    """Показывает список отслеживаемых стримеров"""
    await message.answer("🔄 Получаю список стримеров...")
    
    active_streams = await check_streams()
    active_logins = set(active_streams.keys())

    text = "📋 <b>Список отслеживаемых стримеров:</b>\n\n"
    for login in STREAMERS_TO_TRACK:
        login_lower = login.lower()
        status = "🟢 В ЭФИРЕ" if login_lower in active_logins else "⚫ Не в эфире"
        notified = " (🔔 уведомление отправлено)" if login_lower in notified_streamers else ""
        text += f"• {login} — {status}{notified}\n"

    if len(text) > 4000:
        text = text[:4000] + "\n\n... и другие"

    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Показывает текущий статус бота"""
    await message.answer("🔄 Проверяю статус стримов...")
    
    active_streams = await check_streams()
    live_count = len(active_streams)

    text = (
        "📊 <b>Статус бота</b>\n\n"
        f"🎯 Отслеживается стримеров: {len(STREAMERS_TO_TRACK)}\n"
        f"🔴 Сейчас в эфире: {live_count}\n"
        f"🔔 Активных уведомлений: {len(notified_streamers)}\n"
        f"📢 Канал для уведомлений: {CHANNEL_ID}\n"
        f"⏱️ Интервал проверки: {CHECK_INTERVAL} сек.\n"
        f"🖼️ Интервал обновления скриншотов: {SCREENSHOT_UPDATE_INTERVAL // 60} мин.\n"
        f"🎲 Режим зрителей: Рандом (4-20)\n"
        f"🗑️ Автоудаление: Включено\n"
    )

    if active_streams:
        text += "\n<b>Сейчас в эфире:</b>\n"
        for login, info in active_streams.items():
            last_update = notified_streamers.get(login, {}).get("last_screenshot_update")
            first_detected = notified_streamers.get(login, {}).get("first_detected")
            
            if first_detected:
                duration = datetime.now() - first_detected
                text += f"• {info['user_name']} — {info['game_name']} (в эфире {duration.seconds//60} мин)"
            else:
                text += f"• {info['user_name']} — {info['game_name']}"
            
            if last_update:
                text += f" [скриншот: {last_update.strftime('%H:%M:%S')}]"
            text += "\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


# ========== ЗАПУСК БОТА ==========
async def main():
    """Главная функция запуска бота"""
    # Очищаем старые скриншоты при запуске
    old_files = list(SCREENSHOTS_DIR.glob("*.jpg"))
    if old_files:
        logger.info(f"Очищаю {len(old_files)} старых скриншотов...")
        for file in old_files:
            try:
                file.unlink()
            except:
                pass
    
    # Запускаем фоновые задачи
    asyncio.create_task(check_streams_task())
    asyncio.create_task(update_screenshots_task())
    
    logger.info("🤖 Бот запущен и готов к работе")
    logger.info(f"📢 Уведомления будут отправляться в канал: {CHANNEL_ID}")
    logger.info(f"👥 Отслеживается стримеров: {len(STREAMERS_TO_TRACK)}")
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
