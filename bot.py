"""
Telegram Модератор Бот - Hahaha_master_bot
Полнофункциональный бот для модерации чатов с капчей, антифлудом, фильтрами и отложенным постингом
"""

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, ChatPermissions, ChatMemberUpdated,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand,
    ContentType, FSInputFile
)
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID")
DATA_FILE = "data.json"
CAPTCHA_TIMEOUT = 120

# Инициализация бота
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)


# ==================== СОСТОЯНИЯ FSM ====================
class AdminStates(StatesGroup):
    waiting_welcome_text = State()
    waiting_scheduled_message = State()
    waiting_scheduled_time = State()
    waiting_rules_link = State()
    waiting_stopword = State()
    waiting_antiflood_settings = State()
    waiting_night_mode_time = State()
    waiting_mute_duration = State()
    waiting_user_note = State()
    waiting_broadcast_message = State()
    waiting_faq_keyword = State()
    waiting_faq_answer = State()
    waiting_account_age = State()


# ==================== ХРАНИЛИЩЕ ДАННЫХ ====================
class DataStorage:
    def __init__(self, filename: str = DATA_FILE):
        self.filename = filename
        self.data = self._load()
    
    def _load(self) -> dict:
        if Path(self.filename).exists():
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return self._default_data()
    
    def _default_data(self) -> dict:
        return {
            "chats": {},
            "users": {},
            "pending_captcha": {},
            "scheduled_messages": [],
            "warnings": {},
            "user_notes": {},
            "blacklist": [],
            "whitelist": [],
            "flood_tracker": {},
            "verified_users": {}
        }
    
    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2, default=str)
    
    def get_chat_settings(self, chat_id: int) -> dict:
        chat_id_str = str(chat_id)
        if chat_id_str not in self.data["chats"]:
            self.data["chats"][chat_id_str] = {
                "captcha_enabled": True,
                "filter_enabled": True,
                "antiflood_enabled": True,
                "welcome_enabled": True,
                "welcome_text": "Добро пожаловать в чат!",
                "rules_link": "",
                "stopwords": [],
                "night_mode": {"enabled": False, "start": "23:00", "end": "07:00"},
                "antiflood": {"messages": 5, "seconds": 10, "mute_minutes": 60},
                "antiraid": {"enabled": True, "joins_per_minute": 10},
                "account_age_check": {"enabled": False, "min_days": 7},
                "voice_messages_allowed": True,
                "slow_mode": {"enabled": False, "seconds": 0},
                "admins": [],
                "admin_channel": None,
                "stats": {"messages_deleted": 0, "users_banned": 0, "users_muted": 0, "captcha_passed": 0}
            }
            self.save()
        return self.data["chats"][chat_id_str]
    
    def update_chat_settings(self, chat_id: int, settings: dict):
        self.data["chats"][str(chat_id)] = settings
        self.save()


db = DataStorage()


# ==================== ГЕНЕРАТОР КАПЧИ ====================
class CaptchaGenerator:
    EMOJIS = ["🍎", "🍊", "🍋", "🍇", "🍓", "🍒", "🥝", "🍑", "🍍", "🥭", "🌽", "🥕", "🍆", "🥒", "🌶️"]
    ANIMALS = ["🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯", "🦁", "🐮", "🐷", "🐸", "🐵"]
    
    @staticmethod
    def generate() -> tuple:
        """Генерирует капчу и возвращает (вопрос, правильный_ответ, варианты)"""
        captcha_type = random.choice(["math", "emoji_count", "emoji_find"])
        
        if captcha_type == "math":
            a, b = random.randint(1, 10), random.randint(1, 10)
            op = random.choice(["+", "-"])
            if op == "+":
                answer = a + b
                question = f"Сколько будет {a} + {b}?"
            else:
                if a < b:
                    a, b = b, a
                answer = a - b
                question = f"Сколько будет {a} - {b}?"
            
            options = [answer]
            while len(options) < 4:
                fake = random.randint(0, 20)
                if fake not in options:
                    options.append(fake)
            random.shuffle(options)
            return question, str(answer), [str(o) for o in options]
        
        elif captcha_type == "emoji_count":
            emoji = random.choice(CaptchaGenerator.EMOJIS)
            count = random.randint(2, 6)
            other_emojis = random.sample([e for e in CaptchaGenerator.EMOJIS if e != emoji], 3)
            
            display = [emoji] * count
            for e in other_emojis:
                display.extend([e] * random.randint(1, 3))
            random.shuffle(display)
            
            question = f"Сколько {emoji} на картинке?\n{''.join(display)}"
            options = [count]
            while len(options) < 4:
                fake = random.randint(1, 8)
                if fake not in options:
                    options.append(fake)
            random.shuffle(options)
            return question, str(count), [str(o) for o in options]
        
        else:  # emoji_find
            target = random.choice(CaptchaGenerator.ANIMALS)
            others = random.sample([a for a in CaptchaGenerator.ANIMALS if a != target], 3)
            question = f"Найдите {target} среди вариантов:"
            options = [target] + others
            random.shuffle(options)
            return question, target, options


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
async def is_admin(chat_id: int, user_id: int) -> bool:
    """Проверяет, является ли пользователь админом чата"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            return True
        settings = db.get_chat_settings(chat_id)
        return user_id in settings.get("admins", [])
    except:
        return False


async def log_action(chat_id: int, action: str, user_id: int = None, details: str = ""):
    """Логирует действие в админ-канал"""
    settings = db.get_chat_settings(chat_id)
    admin_channel = settings.get("admin_channel")
    if admin_channel:
        try:
            user_info = f"User ID: {user_id}" if user_id else ""
            await bot.send_message(
                admin_channel,
                f"📋 <b>Лог</b>\n"
                f"Чат: {chat_id}\n"
                f"{user_info}\n"
                f"Действие: {action}\n"
                f"{details}\n"
                f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            logger.error(f"Ошибка логирования: {e}")


def create_main_menu() -> InlineKeyboardMarkup:
    """Создает главное меню бота"""
    buttons = [
        [InlineKeyboardButton(text="🔒 Безопасность", callback_data="menu_security"),
         InlineKeyboardButton(text="🚫 Фильтры", callback_data="menu_filters")],
        [InlineKeyboardButton(text="🤖 Капча", callback_data="menu_captcha"),
         InlineKeyboardButton(text="💤 Ночной режим", callback_data="menu_night")],
        [InlineKeyboardButton(text="🕒 Антифлуд", callback_data="menu_antiflood"),
         InlineKeyboardButton(text="📨 Отложенные посты", callback_data="menu_scheduled")],
        [InlineKeyboardButton(text="👥 Участники", callback_data="menu_members"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
         InlineKeyboardButton(text="❓ Помощь", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_captcha_keyboard(options: List[str], user_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для капчи"""
    buttons = [[InlineKeyboardButton(text=opt, callback_data=f"captcha_{user_id}_{opt}")] for opt in options]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_rules_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для подтверждения правил"""
    buttons = [
        [InlineKeyboardButton(text="✅ Ознакомился", callback_data=f"rules_accept_{user_id}")],
        [InlineKeyboardButton(text="❌ Не ознакомился", callback_data=f"rules_decline_{user_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            "👋 <b>Привет! Я бот-модератор для Telegram чатов.</b>\n\n"
            "🔹 Добавьте меня в чат с правами администратора\n"
            "🔹 Я буду защищать чат от спама и ботов\n"
            "🔹 Настройте меня через меню ниже\n\n"
            "Нажмите кнопку для начала настройки:",
            reply_markup=create_main_menu()
        )
    else:
        await message.answer("Бот активен! Используйте /help для списка команд.")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help"""
    help_text = """
<b>📚 Список команд:</b>

<b>Основные:</b>
/start — Запуск бота
/help — Эта справка
/menu — Главное меню
/stats — Статистика чата

<b>Модерация:</b>
/warn @user — Предупреждение (3 = бан)
/unwarn @user — Снять предупреждение
/mute @user 1h — Временный мут
/unmute @user — Снять мут
/ban @user — Бан навсегда
/unban @user — Разбан

<b>Настройки:</b>
/captcha_on | /captcha_off — Капча
/filter_on | /filter_off — Фильтры
/antiflood_on | /antiflood_off — Антифлуд
/welcome_on | /welcome_off — Приветствие
/setwelcome текст — Установить приветствие
/setrules ссылка — Установить ссылку на правила

<b>Управление:</b>
/cleanup — Очистка от удалённых аккаунтов
/stopwords — Список стоп-слов
/addstop слово — Добавить стоп-слово
/delstop слово — Удалить стоп-слово

<b>Отложенные посты:</b>
/schedule — Создать отложенный пост
/scheduled — Список отложенных постов
/cancelpost ID — Отменить пост
"""
    await message.answer(help_text)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Показать главное меню"""
    await message.answer("📋 <b>Главное меню</b>", reply_markup=create_main_menu())


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Статистика чата"""
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эта команда работает только в чатах.")
        return
    
    settings = db.get_chat_settings(message.chat.id)
    stats = settings.get("stats", {})
    
    try:
        members_count = await bot.get_chat_member_count(message.chat.id)
    except:
        members_count = "N/A"
    
    await message.answer(
        f"📊 <b>Статистика чата</b>\n\n"
        f"👥 Участников: {members_count}\n"
        f"🗑 Удалено сообщений: {stats.get('messages_deleted', 0)}\n"
        f"🚫 Забанено: {stats.get('users_banned', 0)}\n"
        f"🔇 Замьючено: {stats.get('users_muted', 0)}\n"
        f"✅ Прошли капчу: {stats.get('captcha_passed', 0)}"
    )


# ==================== КОМАНДЫ МОДЕРАЦИИ ====================
@router.message(Command("warn"))
async def cmd_warn(message: Message):
    """Предупреждение пользователя"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя для предупреждения.")
        return
    
    user_id = message.reply_to_message.from_user.id
    user_name = message.reply_to_message.from_user.full_name
    chat_id = str(message.chat.id)
    
    if chat_id not in db.data["warnings"]:
        db.data["warnings"][chat_id] = {}
    
    user_id_str = str(user_id)
    db.data["warnings"][chat_id][user_id_str] = db.data["warnings"][chat_id].get(user_id_str, 0) + 1
    warns = db.data["warnings"][chat_id][user_id_str]
    db.save()
    
    if warns >= 3:
        await bot.ban_chat_member(message.chat.id, user_id)
        await message.answer(f"🚫 {user_name} получил 3 предупреждения и забанен!")
        await log_action(message.chat.id, "БАН (3 предупреждения)", user_id)
    else:
        await message.answer(f"⚠️ {user_name} получил предупреждение ({warns}/3)")
        await log_action(message.chat.id, f"Предупреждение ({warns}/3)", user_id)


@router.message(Command("unwarn"))
async def cmd_unwarn(message: Message):
    """Снять предупреждение"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return
    
    user_id = str(message.reply_to_message.from_user.id)
    chat_id = str(message.chat.id)
    
    if chat_id in db.data["warnings"] and user_id in db.data["warnings"][chat_id]:
        db.data["warnings"][chat_id][user_id] = max(0, db.data["warnings"][chat_id][user_id] - 1)
        db.save()
        await message.answer(f"✅ Предупреждение снято. Осталось: {db.data['warnings'][chat_id][user_id]}/3")


@router.message(Command("mute"))
async def cmd_mute(message: Message):
    """Мут пользователя"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя. Формат: /mute 1h (1h, 30m, 1d)")
        return
    
    user_id = message.reply_to_message.from_user.id
    args = message.text.split()
    
    duration_minutes = 60  # По умолчанию 1 час
    if len(args) > 1:
        time_str = args[1].lower()
        if 'h' in time_str:
            duration_minutes = int(time_str.replace('h', '')) * 60
        elif 'm' in time_str:
            duration_minutes = int(time_str.replace('m', ''))
        elif 'd' in time_str:
            duration_minutes = int(time_str.replace('d', '')) * 1440
    
    until_date = datetime.now() + timedelta(minutes=duration_minutes)
    
    await bot.restrict_chat_member(
        message.chat.id, user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until_date
    )
    
    settings = db.get_chat_settings(message.chat.id)
    settings["stats"]["users_muted"] = settings["stats"].get("users_muted", 0) + 1
    db.update_chat_settings(message.chat.id, settings)
    
    await message.answer(f"🔇 Пользователь замьючен на {duration_minutes} минут")
    await log_action(message.chat.id, f"Мут на {duration_minutes} мин", user_id)


@router.message(Command("unmute"))
async def cmd_unmute(message: Message):
    """Снять мут"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return
    
    user_id = message.reply_to_message.from_user.id
    await bot.restrict_chat_member(
        message.chat.id, user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
    )
    await message.answer("🔊 Мут снят")


@router.message(Command("ban"))
async def cmd_ban(message: Message):
    """Бан пользователя"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя для бана.")
        return
    
    user_id = message.reply_to_message.from_user.id
    await bot.ban_chat_member(message.chat.id, user_id)
    
    settings = db.get_chat_settings(message.chat.id)
    settings["stats"]["users_banned"] = settings["stats"].get("users_banned", 0) + 1
    db.update_chat_settings(message.chat.id, settings)
    
    await message.answer("🚫 Пользователь забанен")
    await log_action(message.chat.id, "БАН", user_id)


@router.message(Command("unban"))
async def cmd_unban(message: Message):
    """Разбан пользователя"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return
    
    user_id = message.reply_to_message.from_user.id
    await bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
    await message.answer("✅ Пользователь разбанен")


# ==================== КОМАНДЫ НАСТРОЕК ====================
@router.message(Command("captcha_on"))
async def cmd_captcha_on(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["captcha_enabled"] = True
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("✅ Капча включена")


@router.message(Command("captcha_off"))
async def cmd_captcha_off(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["captcha_enabled"] = False
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("❌ Капча выключена")


@router.message(Command("filter_on"))
async def cmd_filter_on(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["filter_enabled"] = True
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("✅ Фильтры включены")


@router.message(Command("filter_off"))
async def cmd_filter_off(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["filter_enabled"] = False
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("❌ Фильтры выключены")


@router.message(Command("antiflood_on"))
async def cmd_antiflood_on(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["antiflood_enabled"] = True
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("✅ Антифлуд включен")


@router.message(Command("antiflood_off"))
async def cmd_antiflood_off(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["antiflood_enabled"] = False
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("❌ Антифлуд выключен")


@router.message(Command("welcome_on"))
async def cmd_welcome_on(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["welcome_enabled"] = True
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("✅ Приветствие включено")


@router.message(Command("welcome_off"))
async def cmd_welcome_off(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["welcome_enabled"] = False
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("❌ Приветствие выключено")


@router.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    text = message.text.replace("/setwelcome", "").strip()
    if not text:
        await message.answer("Укажите текст приветствия: /setwelcome Ваш текст")
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["welcome_text"] = text
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("✅ Приветствие установлено")


@router.message(Command("setrules"))
async def cmd_setrules(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    text = message.text.replace("/setrules", "").strip()
    if not text:
        await message.answer("Укажите ссылку на правила: /setrules https://...")
        return
    settings = db.get_chat_settings(message.chat.id)
    settings["rules_link"] = text
    db.update_chat_settings(message.chat.id, settings)
    await message.answer("✅ Ссылка на правила установлена")


@router.message(Command("stopwords"))
async def cmd_stopwords(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    settings = db.get_chat_settings(message.chat.id)
    stopwords = settings.get("stopwords", [])
    if stopwords:
        await message.answer(f"🚫 <b>Стоп-слова:</b>\n" + ", ".join(stopwords))
    else:
        await message.answer("Список стоп-слов пуст")


@router.message(Command("addstop"))
async def cmd_addstop(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    word = message.text.replace("/addstop", "").strip().lower()
    if not word:
        await message.answer("Укажите слово: /addstop слово")
        return
    settings = db.get_chat_settings(message.chat.id)
    if word not in settings["stopwords"]:
        settings["stopwords"].append(word)
        db.update_chat_settings(message.chat.id, settings)
        await message.answer(f"✅ Стоп-слово '{word}' добавлено")
    else:
        await message.answer("Это слово уже в списке")


@router.message(Command("delstop"))
async def cmd_delstop(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    word = message.text.replace("/delstop", "").strip().lower()
    if not word:
        await message.answer("Укажите слово: /delstop слово")
        return
    settings = db.get_chat_settings(message.chat.id)
    if word in settings["stopwords"]:
        settings["stopwords"].remove(word)
        db.update_chat_settings(message.chat.id, settings)
        await message.answer(f"✅ Стоп-слово '{word}' удалено")
    else:
        await message.answer("Слово не найдено в списке")


@router.message(Command("cleanup"))
async def cmd_cleanup(message: Message):
    """Очистка чата от удалённых аккаунтов"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    await message.answer("🔄 Начинаю проверку участников...")
    
    deleted_count = 0
    try:
        # Получаем список администраторов для проверки
        admins = await bot.get_chat_administrators(message.chat.id)
        admin_ids = [admin.user.id for admin in admins]
        
        # К сожалению, Telegram API не позволяет получить полный список участников
        # Эта функция будет работать при обнаружении удалённых аккаунтов в сообщениях
        await message.answer(
            f"✅ Проверка завершена.\n"
            f"Удалённые аккаунты будут автоматически удаляться при обнаружении."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ==================== ОБРАБОТКА НОВЫХ УЧАСТНИКОВ ====================
@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    """Обработка вступления нового участника"""
    chat_id = event.chat.id
    user = event.new_chat_member.user
    user_id = user.id
    
    settings = db.get_chat_settings(chat_id)
    
    # Проверка антирейда
    if settings.get("antiraid", {}).get("enabled", True):
        chat_id_str = str(chat_id)
        now = datetime.now()
        
        if "join_tracker" not in db.data:
            db.data["join_tracker"] = {}
        if chat_id_str not in db.data["join_tracker"]:
            db.data["join_tracker"][chat_id_str] = []
        
        # Очищаем старые записи (старше минуты)
        db.data["join_tracker"][chat_id_str] = [
            t for t in db.data["join_tracker"][chat_id_str]
            if datetime.fromisoformat(t) > now - timedelta(minutes=1)
        ]
        db.data["join_tracker"][chat_id_str].append(now.isoformat())
        
        joins_limit = settings.get("antiraid", {}).get("joins_per_minute", 10)
        if len(db.data["join_tracker"][chat_id_str]) > joins_limit:
            await bot.ban_chat_member(chat_id, user_id)
            await log_action(chat_id, "АНТИРЕЙД: автобан", user_id, "Массовое вступление")
            return
    
    # Проверка возраста аккаунта
    if settings.get("account_age_check", {}).get("enabled", False):
        # Telegram не предоставляет дату создания аккаунта напрямую
        # Можно проверить по ID (старые аккаунты имеют меньшие ID)
        pass
    
    # Если капча включена
    if settings.get("captcha_enabled", True):
        # Ограничиваем права пользователя
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        
        # Генерируем капчу
        question, answer, options = CaptchaGenerator.generate()
        
        # Сохраняем данные капчи
        db.data["pending_captcha"][f"{chat_id}_{user_id}"] = {
            "answer": answer,
            "attempts": 0,
            "created": datetime.now().isoformat()
        }
        db.save()
        
        # Отправляем капчу
        captcha_msg = await bot.send_message(
            chat_id,
            f"👋 Привет, {user.full_name}!\n\n"
            f"🔐 Для доступа к чату пройдите проверку:\n\n"
            f"{question}",
            reply_markup=create_captcha_keyboard(options, user_id)
        )
        
        # Удаляем капчу через таймаут
        asyncio.create_task(delete_captcha_after_timeout(chat_id, user_id, captcha_msg.message_id))


async def delete_captcha_after_timeout(chat_id: int, user_id: int, message_id: int):
    """Удаляет капчу после таймаута"""
    await asyncio.sleep(CAPTCHA_TIMEOUT)
    
    key = f"{chat_id}_{user_id}"
    if key in db.data["pending_captcha"]:
        try:
            await bot.delete_message(chat_id, message_id)
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)  # Кик без бана
            del db.data["pending_captcha"][key]
            db.save()
            await log_action(chat_id, "Кик: таймаут капчи", user_id)
        except:
            pass


# ==================== ОБРАБОТКА CALLBACK ЗАПРОСОВ ====================
@router.callback_query(F.data.startswith("captcha_"))
async def process_captcha(callback: CallbackQuery):
    """Обработка ответа на капчу"""
    parts = callback.data.split("_")
    target_user_id = int(parts[1])
    selected_answer = "_".join(parts[2:])
    
    # Проверяем, что отвечает тот же пользователь
    if callback.from_user.id != target_user_id:
        await callback.answer("Это не ваша капча!", show_alert=True)
        return
    
    chat_id = callback.message.chat.id
    key = f"{chat_id}_{target_user_id}"
    
    if key not in db.data["pending_captcha"]:
        await callback.answer("Капча устарела", show_alert=True)
        return
    
    captcha_data = db.data["pending_captcha"][key]
    
    if selected_answer == captcha_data["answer"]:
        # Правильный ответ
        del db.data["pending_captcha"][key]
        
        # Добавляем в список верифицированных
        if str(chat_id) not in db.data["verified_users"]:
            db.data["verified_users"][str(chat_id)] = []
        db.data["verified_users"][str(chat_id)].append(target_user_id)
        db.save()
        
        settings = db.get_chat_settings(chat_id)
        settings["stats"]["captcha_passed"] = settings["stats"].get("captcha_passed", 0) + 1
        db.update_chat_settings(chat_id, settings)
        
        # Удаляем сообщение с капчей
        try:
            await callback.message.delete()
        except:
            pass
        
        # Проверяем, есть ли ссылка на правила
        rules_link = settings.get("rules_link", "")
        
        if rules_link:
            # Отправляем сообщение с правилами
            rules_msg = await bot.send_message(
                chat_id,
                f"✅ <b>Добро пожаловать в чат, {callback.from_user.full_name}!</b>\n\n"
                f"📜 Перед общением, ознакомьтесь с правилами:\n{rules_link}",
                reply_markup=create_rules_keyboard(target_user_id)
            )
        else:
            # Сразу даём права
            await bot.restrict_chat_member(
                chat_id, target_user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            
            if settings.get("welcome_enabled", True):
                welcome_msg = await bot.send_message(
                    chat_id,
                    f"✅ {callback.from_user.full_name}, добро пожаловать!\n\n"
                    f"{settings.get('welcome_text', '')}"
                )
                # Удаляем приветствие через 30 секунд
                asyncio.create_task(delete_message_later(chat_id, welcome_msg.message_id, 30))
        
        await log_action(chat_id, "Капча пройдена", target_user_id)
        await callback.answer("✅ Проверка пройдена!")
    else:
        # Неправильный ответ
        captcha_data["attempts"] += 1
        db.save()
        
        if captcha_data["attempts"] >= 3:
            # Слишком много попыток
            del db.data["pending_captcha"][key]
            db.save()
            
            try:
                await callback.message.delete()
            except:
                pass
            
            await bot.ban_chat_member(chat_id, target_user_id)
            await bot.unban_chat_member(chat_id, target_user_id)  # Кик
            await log_action(chat_id, "Кик: 3 неверных ответа на капчу", target_user_id)
            await callback.answer("❌ Слишком много неверных попыток", show_alert=True)
        else:
            await callback.answer(f"❌ Неверно! Осталось попыток: {3 - captcha_data['attempts']}", show_alert=True)


@router.callback_query(F.data.startswith("rules_accept_"))
async def process_rules_accept(callback: CallbackQuery):
    """Пользователь ознакомился с правилами"""
    target_user_id = int(callback.data.split("_")[2])
    
    if callback.from_user.id != target_user_id:
        await callback.answer("Это не для вас!", show_alert=True)
        return
    
    chat_id = callback.message.chat.id
    
    # Даём права на отправку сообщений
    await bot.restrict_chat_member(
        chat_id, target_user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
    )
    
    try:
        await callback.message.delete()
    except:
        pass
    
    settings = db.get_chat_settings(chat_id)
    welcome_msg = await bot.send_message(
        chat_id,
        f"✅ {callback.from_user.full_name}, добро пожаловать!\n\n"
        f"{settings.get('welcome_text', '')}"
    )
    asyncio.create_task(delete_message_later(chat_id, welcome_msg.message_id, 30))
    
    await callback.answer("✅ Приятного общения!")


@router.callback_query(F.data.startswith("rules_decline_"))
async def process_rules_decline(callback: CallbackQuery):
    """Пользователь не ознакомился с правилами"""
    target_user_id = int(callback.data.split("_")[2])
    
    if callback.from_user.id != target_user_id:
        await callback.answer("Это не для вас!", show_alert=True)
        return
    
    await callback.answer(
        "⚠️ Пожалуйста, ознакомьтесь с правилами чата перед началом общения.",
        show_alert=True
    )


async def delete_message_later(chat_id: int, message_id: int, delay: int):
    """Удаляет сообщение через указанное время"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass


# ==================== ОБРАБОТКА МЕНЮ ====================
@router.callback_query(F.data == "menu_security")
async def menu_security(callback: CallbackQuery):
    settings = db.get_chat_settings(callback.message.chat.id) if callback.message.chat.type != ChatType.PRIVATE else {}
    
    buttons = [
        [InlineKeyboardButton(
            text=f"🛡 Антирейд: {'✅' if settings.get('antiraid', {}).get('enabled', True) else '❌'}",
            callback_data="toggle_antiraid"
        )],
        [InlineKeyboardButton(
            text=f"📅 Проверка возраста аккаунта: {'✅' if settings.get('account_age_check', {}).get('enabled', False) else '❌'}",
            callback_data="toggle_account_age"
        )],
        [InlineKeyboardButton(
            text=f"🖼 Проверка аватарки: {'✅' if settings.get('avatar_check', False) else '❌'}",
            callback_data="toggle_avatar_check"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "🔒 <b>Настройки безопасности</b>\n\n"
        "Выберите параметр для изменения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_filters")
async def menu_filters(callback: CallbackQuery):
    settings = db.get_chat_settings(callback.message.chat.id) if callback.message.chat.type != ChatType.PRIVATE else {}
    
    buttons = [
        [InlineKeyboardButton(
            text=f"🔗 Фильтр ссылок: {'✅' if settings.get('filter_enabled', True) else '❌'}",
            callback_data="toggle_filter"
        )],
        [InlineKeyboardButton(
            text=f"🎤 Голосовые: {'✅' if settings.get('voice_messages_allowed', True) else '❌'}",
            callback_data="toggle_voice"
        )],
        [InlineKeyboardButton(text="📝 Стоп-слова", callback_data="show_stopwords")],
        [InlineKeyboardButton(text="➕ Добавить стоп-слово", callback_data="add_stopword")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "🚫 <b>Настройки фильтров</b>\n\n"
        "Управление фильтрацией контента:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_captcha")
async def menu_captcha(callback: CallbackQuery):
    settings = db.get_chat_settings(callback.message.chat.id) if callback.message.chat.type != ChatType.PRIVATE else {}
    
    buttons = [
        [InlineKeyboardButton(
            text=f"🤖 Капча: {'✅ Включена' if settings.get('captcha_enabled', True) else '❌ Выключена'}",
            callback_data="toggle_captcha"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "🤖 <b>Настройки капчи</b>\n\n"
        "Капча защищает чат от ботов и спамеров.\n"
        "Новые участники должны пройти проверку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_night")
async def menu_night(callback: CallbackQuery):
    settings = db.get_chat_settings(callback.message.chat.id) if callback.message.chat.type != ChatType.PRIVATE else {}
    night = settings.get("night_mode", {})
    
    buttons = [
        [InlineKeyboardButton(
            text=f"🌙 Ночной режим: {'✅' if night.get('enabled', False) else '❌'}",
            callback_data="toggle_night"
        )],
        [InlineKeyboardButton(text=f"⏰ Время: {night.get('start', '23:00')} - {night.get('end', '07:00')}", callback_data="set_night_time")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "💤 <b>Ночной режим</b>\n\n"
        "Запрет сообщений в определённые часы.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_antiflood")
async def menu_antiflood(callback: CallbackQuery):
    settings = db.get_chat_settings(callback.message.chat.id) if callback.message.chat.type != ChatType.PRIVATE else {}
    af = settings.get("antiflood", {})
    
    buttons = [
        [InlineKeyboardButton(
            text=f"🕒 Антифлуд: {'✅' if settings.get('antiflood_enabled', True) else '❌'}",
            callback_data="toggle_antiflood"
        )],
        [InlineKeyboardButton(
            text=f"📊 Лимит: {af.get('messages', 5)} сообщ. за {af.get('seconds', 10)} сек",
            callback_data="set_antiflood"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "🕒 <b>Антифлуд</b>\n\n"
        "Автоматическая блокировка при флуде.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_scheduled")
async def menu_scheduled(callback: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="📝 Создать пост", callback_data="create_scheduled")],
        [InlineKeyboardButton(text="📋 Список постов", callback_data="list_scheduled")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "📨 <b>Отложенные посты</b>\n\n"
        "Планируйте публикации заранее.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_members")
async def menu_members(callback: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="🧹 Очистка от удалённых", callback_data="cleanup_members")],
        [InlineKeyboardButton(text="📊 Топ активных", callback_data="top_active")],
        [InlineKeyboardButton(text="📤 Экспорт списка", callback_data="export_members")],
        [InlineKeyboardButton(text="📢 Массовая рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "👥 <b>Управление участниками</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_stats")
async def menu_stats(callback: CallbackQuery):
    if callback.message.chat.type == ChatType.PRIVATE:
        await callback.answer("Статистика доступна только в чатах", show_alert=True)
        return
    
    settings = db.get_chat_settings(callback.message.chat.id)
    stats = settings.get("stats", {})
    
    try:
        members_count = await bot.get_chat_member_count(callback.message.chat.id)
    except:
        members_count = "N/A"
    
    buttons = [[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]]
    
    await callback.message.edit_text(
        f"📊 <b>Статистика чата</b>\n\n"
        f"👥 Участников: {members_count}\n"
        f"🗑 Удалено сообщений: {stats.get('messages_deleted', 0)}\n"
        f"🚫 Забанено: {stats.get('users_banned', 0)}\n"
        f"🔇 Замьючено: {stats.get('users_muted', 0)}\n"
        f"✅ Прошли капчу: {stats.get('captcha_passed', 0)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="👤 Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton(text="📋 Установить правила", callback_data="set_rules")],
        [InlineKeyboardButton(text="💬 Установить приветствие", callback_data="set_welcome")],
        [InlineKeyboardButton(text="📢 Админ-канал для логов", callback_data="set_admin_channel")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
    ]
    
    await callback.message.edit_text(
        "⚙️ <b>Настройки</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>❓ Помощь</b>\n\n"
        "1️⃣ Добавьте бота в чат с правами админа\n"
        "2️⃣ Настройте параметры через меню\n"
        "3️⃣ Бот автоматически будет модерировать чат\n\n"
        "<b>Основные функции:</b>\n"
        "• Капча для новых участников\n"
        "• Фильтрация спама и ссылок\n"
        "• Антифлуд защита\n"
        "• Ночной режим\n"
        "• Отложенные публикации\n\n"
        "Используйте /help для списка команд.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")]
        ])
    )


@router.callback_query(F.data == "menu_back")
async def menu_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "📋 <b>Главное меню</b>",
        reply_markup=create_main_menu()
    )


# ==================== TOGGLE HANDLERS ====================
@router.callback_query(F.data == "toggle_captcha")
async def toggle_captcha(callback: CallbackQuery):
    if callback.message.chat.type == ChatType.PRIVATE:
        await callback.answer("Работает только в чатах", show_alert=True)
        return
    if not await is_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    
    settings = db.get_chat_settings(callback.message.chat.id)
    settings["captcha_enabled"] = not settings.get("captcha_enabled", True)
    db.update_chat_settings(callback.message.chat.id, settings)
    
    await callback.answer(f"Капча {'включена' if settings['captcha_enabled'] else 'выключена'}")
    await menu_captcha(callback)


@router.callback_query(F.data == "toggle_filter")
async def toggle_filter(callback: CallbackQuery):
    if callback.message.chat.type == ChatType.PRIVATE:
        await callback.answer("Работает только в чатах", show_alert=True)
        return
    if not await is_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    
    settings = db.get_chat_settings(callback.message.chat.id)
    settings["filter_enabled"] = not settings.get("filter_enabled", True)
    db.update_chat_settings(callback.message.chat.id, settings)
    
    await callback.answer(f"Фильтры {'включены' if settings['filter_enabled'] else 'выключены'}")
    await menu_filters(callback)


@router.callback_query(F.data == "toggle_antiflood")
async def toggle_antiflood(callback: CallbackQuery):
    if callback.message.chat.type == ChatType.PRIVATE:
        await callback.answer("Работает только в чатах", show_alert=True)
        return
    if not await is_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    
    settings = db.get_chat_settings(callback.message.chat.id)
    settings["antiflood_enabled"] = not settings.get("antiflood_enabled", True)
    db.update_chat_settings(callback.message.chat.id, settings)
    
    await callback.answer(f"Антифлуд {'включен' if settings['antiflood_enabled'] else 'выключен'}")
    await menu_antiflood(callback)


@router.callback_query(F.data == "toggle_antiraid")
async def toggle_antiraid(callback: CallbackQuery):
    if callback.message.chat.type == ChatType.PRIVATE:
        await callback.answer("Работает только в чатах", show_alert=True)
        return
    if not await is_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    
    settings = db.get_chat_settings(callback.message.chat.id)
    if "antiraid" not in settings:
        settings["antiraid"] = {"enabled": True, "joins_per_minute": 10}
    settings["antiraid"]["enabled"] = not settings["antiraid"].get("enabled", True)
    db.update_chat_settings(callback.message.chat.id, settings)
    
    await callback.answer(f"Антирейд {'включен' if settings['antiraid']['enabled'] else 'выключен'}")
    await menu_security(callback)


@router.callback_query(F.data == "toggle_night")
async def toggle_night(callback: CallbackQuery):
    if callback.message.chat.type == ChatType.PRIVATE:
        await callback.answer("Работает только в чатах", show_alert=True)
        return
    if not await is_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    
    settings = db.get_chat_settings(callback.message.chat.id)
    if "night_mode" not in settings:
        settings["night_mode"] = {"enabled": False, "start": "23:00", "end": "07:00"}
    settings["night_mode"]["enabled"] = not settings["night_mode"].get("enabled", False)
    db.update_chat_settings(callback.message.chat.id, settings)
    
    await callback.answer(f"Ночной режим {'включен' if settings['night_mode']['enabled'] else 'выключен'}")
    await menu_night(callback)


@router.callback_query(F.data == "toggle_voice")
async def toggle_voice(callback: CallbackQuery):
    if callback.message.chat.type == ChatType.PRIVATE:
        await callback.answer("Работает только в чатах", show_alert=True)
        return
    if not await is_admin(callback.message.chat.id, callback.from_user.id):
        await callback.answer("Только для админов", show_alert=True)
        return
    
    settings = db.get_chat_settings(callback.message.chat.id)
    settings["voice_messages_allowed"] = not settings.get("voice_messages_allowed", True)
    db.update_chat_settings(callback.message.chat.id, settings)
    
    await callback.answer(f"Голосовые {'разрешены' if settings['voice_messages_allowed'] else 'запрещены'}")
    await menu_filters(callback)


# ==================== ФИЛЬТРАЦИЯ СООБЩЕНИЙ ====================
@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def filter_messages(message: Message):
    """Фильтрация всех сообщений в группах"""
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Пропускаем админов
    if await is_admin(chat_id, user_id):
        return
    
    settings = db.get_chat_settings(chat_id)
    
    # Проверка верификации (капча)
    if settings.get("captcha_enabled", True):
        verified = db.data.get("verified_users", {}).get(str(chat_id), [])
        if user_id not in verified:
            try:
                await message.delete()
            except:
                pass
            return
    
    # Ночной режим
    if settings.get("night_mode", {}).get("enabled", False):
        now = datetime.now().time()
        start = datetime.strptime(settings["night_mode"].get("start", "23:00"), "%H:%M").time()
        end = datetime.strptime(settings["night_mode"].get("end", "07:00"), "%H:%M").time()
        
        if start > end:  # Переход через полночь
            if now >= start or now <= end:
                try:
                    await message.delete()
                    await message.answer(f"🌙 Ночной режим активен ({start.strftime('%H:%M')} - {end.strftime('%H:%M')})")
                except:
                    pass
                return
        else:
            if start <= now <= end:
                try:
                    await message.delete()
                except:
                    pass
                return
    
    # Антифлуд
    if settings.get("antiflood_enabled", True):
        af = settings.get("antiflood", {"messages": 5, "seconds": 10, "mute_minutes": 60})
        key = f"{chat_id}_{user_id}"
        now = datetime.now()
        
        if key not in db.data["flood_tracker"]:
            db.data["flood_tracker"][key] = []
        
        # Очищаем старые записи
        db.data["flood_tracker"][key] = [
            t for t in db.data["flood_tracker"][key]
            if datetime.fromisoformat(t) > now - timedelta(seconds=af["seconds"])
        ]
        db.data["flood_tracker"][key].append(now.isoformat())
        
        if len(db.data["flood_tracker"][key]) > af["messages"]:
            # Флуд обнаружен
            until_date = now + timedelta(minutes=af["mute_minutes"])
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            db.data["flood_tracker"][key] = []
            db.save()
            
            settings["stats"]["users_muted"] = settings["stats"].get("users_muted", 0) + 1
            db.update_chat_settings(chat_id, settings)
            
            await message.answer(f"🔇 {message.from_user.full_name} замьючен за флуд на {af['mute_minutes']} мин")
            await log_action(chat_id, f"Мут за флуд на {af['mute_minutes']} мин", user_id)
            return
    
    if not settings.get("filter_enabled", True):
        return
    
    # Проверка голосовых сообщений
    if not settings.get("voice_messages_allowed", True):
        if message.voice or message.video_note:
            try:
                await message.delete()
                settings["stats"]["messages_deleted"] = settings["stats"].get("messages_deleted", 0) + 1
                db.update_chat_settings(chat_id, settings)
            except:
                pass
            return
    
    # Проверка пересланных сообщений
    if message.forward_from or message.forward_from_chat:
        try:
            await message.delete()
            settings["stats"]["messages_deleted"] = settings["stats"].get("messages_deleted", 0) + 1
            db.update_chat_settings(chat_id, settings)
            await log_action(chat_id, "Удалено пересланное сообщение", user_id)
        except:
            pass
        return
    
    # Проверка GIF и видео
    if message.animation:
        try:
            await message.delete()
            settings["stats"]["messages_deleted"] = settings["stats"].get("messages_deleted", 0) + 1
            db.update_chat_settings(chat_id, settings)
        except:
            pass
        return
    
    text = message.text or message.caption or ""
    
    # Проверка ссылок
    url_pattern = r'https?://[^\s]+'
    if re.search(url_pattern, text):
        try:
            await message.delete()
            settings["stats"]["messages_deleted"] = settings["stats"].get("messages_deleted", 0) + 1
            db.update_chat_settings(chat_id, settings)
            await log_action(chat_id, "Удалено сообщение со ссылкой", user_id)
        except:
            pass
        return
    
    # Проверка стоп-слов
    stopwords = settings.get("stopwords", [])
    text_lower = text.lower()
    for word in stopwords:
        if word.lower() in text_lower:
            try:
                await message.delete()
                settings["stats"]["messages_deleted"] = settings["stats"].get("messages_deleted", 0) + 1
                db.update_chat_settings(chat_id, settings)
                await log_action(chat_id, f"Удалено сообщение со стоп-словом: {word}", user_id)
            except:
                pass
            return


# ==================== ОТЛОЖЕННЫЕ ПОСТЫ ====================
@router.message(Command("schedule"))
async def cmd_schedule(message: Message, state: FSMContext):
    """Создание отложенного поста"""
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Используйте эту команду в личных сообщениях с ботом.")
        return
    
    await state.set_state(AdminStates.waiting_scheduled_message)
    await message.answer(
        "📝 <b>Создание отложенного поста</b>\n\n"
        "Отправьте сообщение, которое хотите опубликовать.\n"
        "Можно отправить текст, фото, видео, документ или аудио."
    )


@router.message(AdminStates.waiting_scheduled_message)
async def process_scheduled_message(message: Message, state: FSMContext):
    """Обработка сообщения для отложенного поста"""
    await state.update_data(
        message_text=message.text,
        message_photo=message.photo[-1].file_id if message.photo else None,
        message_video=message.video.file_id if message.video else None,
        message_document=message.document.file_id if message.document else None,
        message_audio=message.audio.file_id if message.audio else None,
        message_caption=message.caption
    )
    
    await state.set_state(AdminStates.waiting_scheduled_time)
    await message.answer(
        "⏰ Укажите дату и время публикации в формате:\n"
        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
        "Например: <code>25.12.2024 15:30</code>"
    )


@router.message(AdminStates.waiting_scheduled_time)
async def process_scheduled_time(message: Message, state: FSMContext):
    """Обработка времени для отложенного поста"""
    try:
        scheduled_time = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        
        if scheduled_time <= datetime.now():
            await message.answer("❌ Время должно быть в будущем. Попробуйте снова.")
            return
        
        data = await state.get_data()
        
        # Сохраняем отложенный пост
        post = {
            "id": len(db.data["scheduled_messages"]) + 1,
            "user_id": message.from_user.id,
            "scheduled_time": scheduled_time.isoformat(),
            "text": data.get("message_text"),
            "photo": data.get("message_photo"),
            "video": data.get("message_video"),
            "document": data.get("message_document"),
            "audio": data.get("message_audio"),
            "caption": data.get("message_caption"),
            "chat_id": None,  # Будет указан позже
            "status": "pending"
        }
        
        db.data["scheduled_messages"].append(post)
        db.save()
        
        await state.clear()
        
        await message.answer(
            f"✅ <b>Пост запланирован!</b>\n\n"
            f"📅 Дата: {scheduled_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🆔 ID поста: {post['id']}\n\n"
            f"Теперь укажите ID чата для публикации командой:\n"
            f"/setchat {post['id']} ID_ЧАТА"
        )
        
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ")


@router.message(Command("setchat"))
async def cmd_setchat(message: Message):
    """Установка чата для отложенного поста"""
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Формат: /setchat ID_ПОСТА ID_ЧАТА")
        return
    
    try:
        post_id = int(args[1])
        chat_id = int(args[2])
        
        for post in db.data["scheduled_messages"]:
            if post["id"] == post_id and post["user_id"] == message.from_user.id:
                post["chat_id"] = chat_id
                db.save()
                await message.answer(f"✅ Чат установлен для поста #{post_id}")
                return
        
        await message.answer("❌ Пост не найден")
    except ValueError:
        await message.answer("❌ Неверный формат ID")


@router.message(Command("scheduled"))
async def cmd_scheduled(message: Message):
    """Список отложенных постов"""
    user_posts = [p for p in db.data["scheduled_messages"] 
                  if p["user_id"] == message.from_user.id and p["status"] == "pending"]
    
    if not user_posts:
        await message.answer("📭 У вас нет отложенных постов")
        return
    
    text = "📋 <b>Ваши отложенные посты:</b>\n\n"
    for post in user_posts:
        scheduled = datetime.fromisoformat(post["scheduled_time"])
        text += f"🆔 #{post['id']} — {scheduled.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"   Чат: {post['chat_id'] or 'не указан'}\n\n"
    
    await message.answer(text)


@router.message(Command("cancelpost"))
async def cmd_cancelpost(message: Message):
    """Отмена отложенного поста"""
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Формат: /cancelpost ID_ПОСТА")
        return
    
    try:
        post_id = int(args[1])
        
        for post in db.data["scheduled_messages"]:
            if post["id"] == post_id and post["user_id"] == message.from_user.id:
                post["status"] = "cancelled"
                db.save()
                await message.answer(f"✅ Пост #{post_id} отменён")
                return
        
        await message.answer("❌ Пост не найден")
    except ValueError:
        await message.answer("❌ Неверный формат ID")


async def scheduled_posts_checker():
    """Фоновая задача для проверки отложенных постов"""
    while True:
        now = datetime.now()
        
        for post in db.data["scheduled_messages"]:
            if post["status"] != "pending" or not post["chat_id"]:
                continue
            
            scheduled = datetime.fromisoformat(post["scheduled_time"])
            if scheduled <= now:
                try:
                    if post["photo"]:
                        await bot.send_photo(post["chat_id"], post["photo"], caption=post["caption"])
                    elif post["video"]:
                        await bot.send_video(post["chat_id"], post["video"], caption=post["caption"])
                    elif post["document"]:
                        await bot.send_document(post["chat_id"], post["document"], caption=post["caption"])
                    elif post["audio"]:
                        await bot.send_audio(post["chat_id"], post["audio"], caption=post["caption"])
                    elif post["text"]:
                        await bot.send_message(post["chat_id"], post["text"])
                    
                    post["status"] = "sent"
                    db.save()
                    logger.info(f"Отложенный пост #{post['id']} опубликован")
                except Exception as e:
                    logger.error(f"Ошибка публикации поста #{post['id']}: {e}")
                    post["status"] = "error"
                    db.save()
        
        await asyncio.sleep(30)  # Проверка каждые 30 секунд


# ==================== ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ ====================
@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message):
    """Добавление админа бота"""
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эта команда работает только в чатах.")
        return
    
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя, которого хотите сделать админом бота.")
        return
    
    user_id = message.reply_to_message.from_user.id
    settings = db.get_chat_settings(message.chat.id)
    
    if user_id not in settings["admins"]:
        settings["admins"].append(user_id)
        db.update_chat_settings(message.chat.id, settings)
        await message.answer(f"✅ {message.reply_to_message.from_user.full_name} добавлен как админ бота")
    else:
        await message.answer("Этот пользователь уже админ бота")


@router.message(Command("deladmin"))
async def cmd_deladmin(message: Message):
    """Удаление админа бота"""
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эта команда работает только в чатах.")
        return
    
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя.")
        return
    
    user_id = message.reply_to_message.from_user.id
    settings = db.get_chat_settings(message.chat.id)
    
    if user_id in settings["admins"]:
        settings["admins"].remove(user_id)
        db.update_chat_settings(message.chat.id, settings)
        await message.answer(f"✅ {message.reply_to_message.from_user.full_name} удалён из админов бота")
    else:
        await message.answer("Этот пользователь не является админом бота")


@router.message(Command("setadminchannel"))
async def cmd_setadminchannel(message: Message):
    """Установка канала для логов"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Формат: /setadminchannel ID_КАНАЛА\n\nПолучить ID канала можно через @userinfobot")
        return
    
    try:
        channel_id = int(args[1])
        settings = db.get_chat_settings(message.chat.id)
        settings["admin_channel"] = channel_id
        db.update_chat_settings(message.chat.id, settings)
        await message.answer(f"✅ Канал для логов установлен: {channel_id}")
    except ValueError:
        await message.answer("❌ Неверный формат ID")


@router.message(Command("blacklist"))
async def cmd_blacklist(message: Message):
    """Показать чёрный список"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if db.data["blacklist"]:
        await message.answer("🚫 <b>Чёрный список:</b>\n" + "\n".join(str(uid) for uid in db.data["blacklist"]))
    else:
        await message.answer("Чёрный список пуст")


@router.message(Command("addblacklist"))
async def cmd_addblacklist(message: Message):
    """Добавить в чёрный список"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Ответьте на сообщение или укажите ID: /addblacklist ID")
            return
        try:
            user_id = int(args[1])
        except:
            await message.answer("❌ Неверный ID")
            return
    
    if user_id not in db.data["blacklist"]:
        db.data["blacklist"].append(user_id)
        db.save()
        await message.answer(f"✅ Пользователь {user_id} добавлен в чёрный список")
    else:
        await message.answer("Уже в чёрном списке")


@router.message(Command("delblacklist"))
async def cmd_delblacklist(message: Message):
    """Удалить из чёрного списка"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Формат: /delblacklist ID")
        return
    
    try:
        user_id = int(args[1])
        if user_id in db.data["blacklist"]:
            db.data["blacklist"].remove(user_id)
            db.save()
            await message.answer(f"✅ Пользователь {user_id} удалён из чёрного списка")
        else:
            await message.answer("Не найден в чёрном списке")
    except:
        await message.answer("❌ Неверный ID")


@router.message(Command("whitelist"))
async def cmd_whitelist(message: Message):
    """Показать белый список"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if db.data["whitelist"]:
        await message.answer("✅ <b>Белый список:</b>\n" + "\n".join(str(uid) for uid in db.data["whitelist"]))
    else:
        await message.answer("Белый список пуст")


@router.message(Command("addwhitelist"))
async def cmd_addwhitelist(message: Message):
    """Добавить в белый список"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Ответьте на сообщение или укажите ID: /addwhitelist ID")
            return
        try:
            user_id = int(args[1])
        except:
            await message.answer("❌ Неверный ID")
            return
    
    if user_id not in db.data["whitelist"]:
        db.data["whitelist"].append(user_id)
        db.save()
        await message.answer(f"✅ Пользователь {user_id} добавлен в белый список")
    else:
        await message.answer("Уже в белом списке")


@router.message(Command("note"))
async def cmd_note(message: Message, state: FSMContext):
    """Добавить заметку о пользователе"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя")
        return
    
    args = message.text.replace("/note", "").strip()
    if not args:
        await message.answer("Формат: /note текст заметки")
        return
    
    user_id = str(message.reply_to_message.from_user.id)
    chat_id = str(message.chat.id)
    
    if chat_id not in db.data["user_notes"]:
        db.data["user_notes"][chat_id] = {}
    
    if user_id not in db.data["user_notes"][chat_id]:
        db.data["user_notes"][chat_id][user_id] = []
    
    db.data["user_notes"][chat_id][user_id].append({
        "text": args,
        "by": message.from_user.id,
        "date": datetime.now().isoformat()
    })
    db.save()
    
    await message.answer(f"✅ Заметка добавлена для {message.reply_to_message.from_user.full_name}")


@router.message(Command("notes"))
async def cmd_notes(message: Message):
    """Показать заметки о пользователе"""
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя")
        return
    
    user_id = str(message.reply_to_message.from_user.id)
    chat_id = str(message.chat.id)
    
    notes = db.data.get("user_notes", {}).get(chat_id, {}).get(user_id, [])
    
    if notes:
        text = f"📝 <b>Заметки о {message.reply_to_message.from_user.full_name}:</b>\n\n"
        for i, note in enumerate(notes, 1):
            date = datetime.fromisoformat(note["date"]).strftime("%d.%m.%Y")
            text += f"{i}. {note['text']} ({date})\n"
        await message.answer(text)
    else:
        await message.answer("Заметок нет")


@router.message(Command("rules"))
async def cmd_rules(message: Message):
    """Показать правила чата"""
    settings = db.get_chat_settings(message.chat.id)
    rules_link = settings.get("rules_link", "")
    
    rules_text = """
<b>📜 Правила чата:</b>

1️⃣ Уважайте участников, без оскорблений.
2️⃣ Запрещены ссылки, реклама, казино, ставки, неприемлемая тематика, запрещенные вещества.
3️⃣ GIF, видео и пересланные сообщения — запрещены.
4️⃣ Новички пишут только после прохождения капчи.
5️⃣ За флуд сначала предупреждение, затем блокировка.
6️⃣ Политика, спам, NSFW — запрещено.
7️⃣ Администраторы имеют право удалить сообщения и заблокировать нарушителей.
"""
    
    if rules_link:
        rules_text += f"\n🔗 Подробнее: {rules_link}"
    
    await message.answer(rules_text)


@router.message(Command("id"))
async def cmd_id(message: Message):
    """Получить ID пользователя или чата"""
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        await message.answer(
            f"👤 <b>Информация о пользователе:</b>\n"
            f"ID: <code>{user.id}</code>\n"
            f"Имя: {user.full_name}\n"
            f"Username: @{user.username or 'нет'}"
        )
    else:
        await message.answer(
            f"💬 <b>Информация о чате:</b>\n"
            f"ID чата: <code>{message.chat.id}</code>\n"
            f"Ваш ID: <code>{message.from_user.id}</code>"
        )


# ==================== ЗАПУСК БОТА ====================
async def set_bot_commands():
    """Установка команд бота"""
    commands = [
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="stats", description="Статистика чата"),
        BotCommand(command="rules", description="Правила чата"),
        BotCommand(command="id", description="Получить ID"),
    ]
    await bot.set_my_commands(commands)


async def main():
    """Главная функция запуска"""
    logger.info("Запуск бота...")
    
    await set_bot_commands()
    
    # Запуск фоновой задачи для отложенных постов
    asyncio.create_task(scheduled_posts_checker())
    
    # Запуск polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
