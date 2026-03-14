"""
Telegram Bot with Advanced Registration System
Author: Advanced Bot Development
Version: 1.0.0
"""

import asyncio
import logging
import sqlite3
import json
import re
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from enum import Enum
from dataclasses import dataclass
from contextlib import contextmanager
import random
import string
import os
from functools import wraps
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    ReplyKeyboardRemove, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    PicklePersistence
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError

# ==================== CONFIGURATION ====================

TOKEN = "7774268866:AAGDXUEvMO_qftav3xgEVNxomWMg0uCwNpM"
ADMIN_IDS = [8275951845]
BOT_USERNAME = None  # Will be set on startup

# Database configuration
DATABASE_FILE = "bot_database.db"

# Registration states
(
    REG_NAME,
    REG_PHONE,
    REG_EMAIL,
    REG_CONFIRM,
    REG_PASSWORD,
    REG_BIRTHDAY,
    REG_CITY,
    REG_BIO,
    REG_INTERESTS,
    REG_AVATAR
) = range(10)

# Other conversation states
(
    FEEDBACK_TEXT,
    ADMIN_BROADCAST,
    ADMIN_EDIT_USER,
    PROFILE_EDIT_NAME,
    PROFILE_EDIT_PHONE,
    PROFILE_EDIT_EMAIL,
    PROFILE_EDIT_BIRTHDAY,
    PROFILE_EDIT_CITY,
    PROFILE_EDIT_BIO,
    PROFILE_EDIT_INTERESTS,
    SETTINGS_CHANGE_LANGUAGE,
    SETTINGS_CHANGE_NOTIFICATIONS,
    SETTINGS_CHANGE_PRIVACY,
    SUPPORT_MESSAGE,
    VERIFICATION_CODE
) = range(20, 35)


# ==================== ENUMS & DATA CLASSES ====================

class UserRole(Enum):
    USER = "user"
    PREMIUM = "premium"
    MODERATOR = "moderator"
    ADMIN = "admin"


class UserStatus(Enum):
    ACTIVE = "active"
    BANNED = "banned"
    PENDING = "pending"
    DELETED = "deleted"


class NotificationType(Enum):
    ALL = "all"
    IMPORTANT = "important"
    NONE = "none"


class PrivacyLevel(Enum):
    PUBLIC = "public"
    CONTACTS = "contacts"
    PRIVATE = "private"


class Language(Enum):
    RU = "ru"
    EN = "en"
    UZ = "uz"


@dataclass
class UserData:
    user_id: int
    username: str = None
    first_name: str = None
    last_name: str = None
    phone: str = None
    email: str = None
    password_hash: str = None
    birthday: str = None
    city: str = None
    bio: str = None
    interests: str = None
    avatar: str = None
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.PENDING
    language: Language = Language.RU
    notification_pref: NotificationType = NotificationType.ALL
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    registration_date: datetime = None
    last_login: datetime = None
    is_verified: bool = False
    is_2fa_enabled: bool = False
    referral_code: str = None
    referred_by: int = None
    rating: float = 0.0
    total_interactions: int = 0
    warnings: int = 0
    premium_until: datetime = None


@dataclass
class Session:
    session_id: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    ip_address: str = None
    user_agent: str = None


# ==================== DATABASE MANAGER ====================

class DatabaseManager:
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.init_database()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_file, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def init_database(self):
        """Initialize database with all required tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    phone TEXT UNIQUE,
                    email TEXT UNIQUE,
                    password_hash TEXT,
                    birthday TEXT,
                    city TEXT,
                    bio TEXT,
                    interests TEXT,
                    avatar TEXT,
                    role TEXT DEFAULT 'user',
                    status TEXT DEFAULT 'pending',
                    language TEXT DEFAULT 'ru',
                    notification_pref TEXT DEFAULT 'all',
                    privacy_level TEXT DEFAULT 'public',
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    is_verified INTEGER DEFAULT 0,
                    is_2fa_enabled INTEGER DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    referred_by INTEGER,
                    rating REAL DEFAULT 0,
                    total_interactions INTEGER DEFAULT 0,
                    warnings INTEGER DEFAULT 0,
                    premium_until TIMESTAMP,
                    FOREIGN KEY (referred_by) REFERENCES users(user_id)
                )
            ''')

            # Sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Verification codes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS verification_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    used INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Login attempts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    ip_address TEXT,
                    attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    successful INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Activity logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    receiver_id INTEGER NOT NULL,
                    content TEXT,
                    file_path TEXT,
                    message_type TEXT,
                    is_read INTEGER DEFAULT 0,
                    is_deleted INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sender_id) REFERENCES users(user_id),
                    FOREIGN KEY (receiver_id) REFERENCES users(user_id)
                )
            ''')

            # Groups/Chats table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_name TEXT,
                    chat_type TEXT,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    avatar TEXT,
                    description TEXT,
                    FOREIGN KEY (created_by) REFERENCES users(user_id)
                )
            ''')

            # Chat members table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id INTEGER,
                    user_id INTEGER,
                    role TEXT DEFAULT 'member',
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id),
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Notifications table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT,
                    content TEXT,
                    type TEXT,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Feedback table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    feedback_text TEXT,
                    rating INTEGER,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Referrals table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER NOT NULL,
                    referral_code TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reward_given INTEGER DEFAULT 0,
                    FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                    FOREIGN KEY (referred_id) REFERENCES users(user_id)
                )
            ''')

            # User interests table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS interests (
                    interest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    interest_name TEXT UNIQUE,
                    category TEXT
                )
            ''')

            # User interests mapping
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_interests (
                    user_id INTEGER,
                    interest_id INTEGER,
                    PRIMARY KEY (user_id, interest_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (interest_id) REFERENCES interests(interest_id)
                )
            ''')

            # Achievements table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS achievements (
                    achievement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    achievement_name TEXT UNIQUE,
                    description TEXT,
                    icon TEXT,
                    points INTEGER
                )
            ''')

            # User achievements table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id INTEGER,
                    achievement_id INTEGER,
                    earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, achievement_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (achievement_id) REFERENCES achievements(achievement_id)
                )
            ''')

            # Create indexes for better performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_referral ON users(referral_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages(receiver_id, is_read)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_logs(user_id, timestamp)')

            # Insert default interests if not exists
            default_interests = [
                ('Technology', 'Tech'),
                ('Sports', 'Sports'),
                ('Music', 'Entertainment'),
                ('Movies', 'Entertainment'),
                ('Reading', 'Hobbies'),
                ('Travel', 'Lifestyle'),
                ('Cooking', 'Lifestyle'),
                ('Gaming', 'Entertainment'),
                ('Art', 'Creative'),
                ('Fashion', 'Lifestyle'),
                ('Fitness', 'Health'),
                ('Photography', 'Creative')
            ]

            for interest, category in default_interests:
                cursor.execute(
                    'INSERT OR IGNORE INTO interests (interest_name, category) VALUES (?, ?)',
                    (interest, category)
                )

    # User management methods
    def create_user(self, user_data: UserData) -> bool:
        """Create a new user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Generate referral code
                referral_code = self.generate_referral_code()

                cursor.execute('''
                    INSERT INTO users (
                        user_id, username, first_name, last_name, phone, email,
                        password_hash, birthday, city, bio, interests, avatar,
                        role, status, language, notification_pref, privacy_level,
                        registration_date, referral_code, referred_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_data.user_id, user_data.username, user_data.first_name,
                    user_data.last_name, user_data.phone, user_data.email,
                    user_data.password_hash, user_data.birthday, user_data.city,
                    user_data.bio, user_data.interests, user_data.avatar,
                    user_data.role.value, user_data.status.value, user_data.language.value,
                    user_data.notification_pref.value, user_data.privacy_level.value,
                    datetime.now(), referral_code, user_data.referred_by
                ))

                return True
        except Exception as e:
            logging.error(f"Error creating user: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            return cursor.fetchone()

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            return cursor.fetchone()

    def get_user_by_phone(self, phone: str) -> Optional[Dict]:
        """Get user by phone"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE phone = ?', (phone,))
            return cursor.fetchone()

    def update_user(self, user_id: int, **kwargs) -> bool:
        """Update user information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                fields = []
                values = []

                for key, value in kwargs.items():
                    if value is not None:
                        fields.append(f"{key} = ?")
                        values.append(value)

                if fields:
                    query = f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?"
                    values.append(user_id)
                    cursor.execute(query, values)
                    return True
                return False
        except Exception as e:
            logging.error(f"Error updating user: {e}")
            return False

    def generate_referral_code(self) -> str:
        """Generate unique referral code"""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (code,))
                if not cursor.fetchone():
                    return code

    # Session management
    def create_session(self, user_id: int, ip: str = None, user_agent: str = None) -> str:
        """Create a new session"""
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=7)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sessions (session_id, user_id, expires_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, user_id, expires_at, ip, user_agent))

        return session_id

    def validate_session(self, session_id: str) -> Optional[int]:
        """Validate session and return user_id if valid"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id FROM sessions 
                WHERE session_id = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (session_id,))
            result = cursor.fetchone()
            return result['user_id'] if result else None

    def end_session(self, session_id: str) -> bool:
        """End a session"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
            return cursor.rowcount > 0

    # Verification codes
    def create_verification_code(self, user_id: int, code_type: str) -> str:
        """Create verification code"""
        code = ''.join(random.choices(string.digits, k=6))
        expires_at = datetime.now() + timedelta(minutes=15)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO verification_codes (user_id, code, type, expires_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, code, code_type, expires_at))

        return code

    def verify_code(self, user_id: int, code: str, code_type: str) -> bool:
        """Verify a code"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM verification_codes 
                WHERE user_id = ? AND code = ? AND type = ? 
                AND expires_at > CURRENT_TIMESTAMP AND used = 0
            ''', (user_id, code, code_type))

            if cursor.fetchone():
                cursor.execute('''
                    UPDATE verification_codes SET used = 1 
                    WHERE user_id = ? AND code = ? AND type = ?
                ''', (user_id, code, code_type))
                return True
            return False

    # Activity logging
    def log_activity(self, user_id: int, action: str, details: str = None, ip: str = None):
        """Log user activity"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO activity_logs (user_id, action, details, ip_address)
                VALUES (?, ?, ?, ?)
            ''', (user_id, action, details, ip))

    # Statistics methods
    def get_user_count(self) -> int:
        """Get total user count"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM users')
            return cursor.fetchone()['count']

    def get_active_users_today(self) -> int:
        """Get users active today"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(DISTINCT user_id) as count 
                FROM activity_logs 
                WHERE DATE(timestamp) = DATE('now')
            ''')
            return cursor.fetchone()['count']

    def get_new_users_today(self) -> int:
        """Get new users today"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count 
                FROM users 
                WHERE DATE(registration_date) = DATE('now')
            ''')
            return cursor.fetchone()['count']


# ==================== SECURITY MANAGER ====================

class SecurityManager:
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password with salt"""
        salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
        pwdhash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)
        pwdhash = pwdhash.hex()
        return salt.decode('ascii') + pwdhash

    @staticmethod
    def verify_password(stored_password: str, provided_password: str) -> bool:
        """Verify password"""
        salt = stored_password[:64]
        stored_pwdhash = stored_password[64:]
        pwdhash = hashlib.pbkdf2_hmac(
            'sha512',
            provided_password.encode('utf-8'),
            salt.encode('ascii'),
            100000
        )
        pwdhash = pwdhash.hex()
        return pwdhash == stored_pwdhash

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate phone number format"""
        pattern = r'^\+?[\d\s-]{10,}$'
        return re.match(pattern, phone) is not None

    @staticmethod
    def validate_password(password: str) -> Tuple[bool, str]:
        """Validate password strength"""
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r'\d', password):
            return False, "Password must contain at least one number"
        return True, "Password is valid"

    @staticmethod
    def sanitize_input(text: str) -> str:
        """Sanitize user input"""
        # Remove any potential harmful characters
        return re.sub(r'[<>{}]', '', text)


# ==================== LOCALIZATION MANAGER ====================

class LocalizationManager:
    def __init__(self):
        self.strings = {
            Language.RU: {
                # General
                'welcome': '👋 Добро пожаловать в бот!',
                'start_registration': '📝 Начать регистрацию',
                'main_menu': '🏠 Главное меню',
                'profile': '👤 Профиль',
                'settings': '⚙️ Настройки',
                'help': '❓ Помощь',
                'about': 'ℹ️ О боте',
                'back': '◀️ Назад',
                'cancel': '❌ Отмена',
                'confirm': '✅ Подтвердить',
                'yes': 'Да',
                'no': 'Нет',
                'save': '💾 Сохранить',
                'edit': '✏️ Редактировать',
                'delete': '🗑️ Удалить',
                'search': '🔍 Поиск',

                # Registration
                'reg_start': '📝 Давайте начнем регистрацию! Это займет всего несколько минут.',
                'reg_name': '👤 Введите ваше имя:',
                'reg_phone': '📱 Введите ваш номер телефона:',
                'reg_email': '📧 Введите ваш email адрес:',
                'reg_password': '🔐 Придумайте пароль (минимум 8 символов, с заглавной буквой и цифрой):',
                'reg_birthday': '🎂 Введите вашу дату рождения (ДД.ММ.ГГГГ):',
                'reg_city': '🏙️ Введите ваш город:',
                'reg_bio': '📝 Расскажите немного о себе (необязательно):',
                'reg_interests': '🎯 Выберите ваши интересы:',
                'reg_avatar': '🖼️ Отправьте фото для профиля (необязательно):',
                'reg_confirm': '✅ Подтвердите введенные данные:',
                'reg_success': '🎉 Регистрация успешно завершена! Добро пожаловать!',
                'reg_error': '❌ Ошибка при регистрации. Попробуйте позже.',
                'reg_skip': '⏭️ Пропустить',

                # Profile
                'profile_view': '👤 Ваш профиль',
                'profile_edit': '✏️ Редактировать профиль',
                'profile_edit_name': '✏️ Введите новое имя:',
                'profile_edit_phone': '✏️ Введите новый номер телефона:',
                'profile_edit_email': '✏️ Введите новый email:',
                'profile_edit_birthday': '✏️ Введите новую дату рождения:',
                'profile_edit_city': '✏️ Введите новый город:',
                'profile_edit_bio': '✏️ Введите новую информацию о себе:',
                'profile_edit_interests': '✏️ Выберите новые интересы:',
                'profile_edit_avatar': '✏️ Отправьте новое фото профиля:',
                'profile_saved': '✅ Профиль успешно обновлен!',
                'profile_not_found': '❌ Профиль не найден',

                # Interests
                'select_interests': '🎯 Выберите ваши интересы (можно выбрать несколько):',
                'interests_selected': '✅ Выбрано: {}',
                'interests_confirm': '✅ Подтвердить выбор',

                # Settings
                'settings_menu': '⚙️ Настройки',
                'settings_language': '🌐 Язык',
                'settings_notifications': '🔔 Уведомления',
                'settings_privacy': '🔒 Приватность',
                'settings_security': '🛡️ Безопасность',
                'settings_language_ru': '🇷🇺 Русский',
                'settings_language_en': '🇬🇧 English',
                'settings_language_uz': '🇺🇿 O\'zbek',
                'settings_notifications_all': '🔔 Все уведомления',
                'settings_notifications_important': '⚠️ Только важные',
                'settings_notifications_none': '🔕 Отключить',
                'settings_privacy_public': '🌍 Все видят',
                'settings_privacy_contacts': '👥 Только контакты',
                'settings_privacy_private': '🔒 Только я',
                'settings_2fa_enable': '🔐 Включить двухфакторную аутентификацию',
                'settings_2fa_disable': '🔓 Отключить двухфакторную аутентификацию',
                'settings_saved': '✅ Настройки сохранены!',

                # Actions
                'send_message': '💬 Отправить сообщение',
                'view_messages': '📬 Просмотреть сообщения',
                'find_friends': '👥 Найти друзей',
                'my_friends': '👫 Мои друзья',
                'achievements': '🏆 Достижения',
                'rating': '⭐ Рейтинг',
                'referrals': '🤝 Рефералы',
                'premium': '💎 Premium',
                'support': '🆘 Поддержка',
                'feedback': '📝 Обратная связь',

                # Admin
                'admin_panel': '👨‍💼 Панель администратора',
                'admin_stats': '📊 Статистика',
                'admin_users': '👥 Пользователи',
                'admin_broadcast': '📢 Рассылка',
                'admin_reports': '📋 Жалобы',
                'admin_settings': '⚙️ Настройки бота',
                'admin_logs': '📁 Логи',

                # Errors and messages
                'error_invalid_input': '❌ Неверный формат. Попробуйте снова.',
                'error_email_exists': '❌ Этот email уже зарегистрирован',
                'error_phone_exists': '❌ Этот номер уже зарегистрирован',
                'error_user_banned': '❌ Ваш аккаунт заблокирован',
                'error_unauthorized': '❌ У вас нет прав для этого действия',
                'error_session_expired': '❌ Сессия истекла. Войдите снова',
                'success_login': '✅ Успешный вход!',
                'success_logout': '✅ Вы вышли из аккаунта',
                'confirm_logout': '❓ Вы действительно хотите выйти?',

                # Buttons
                'btn_login': '🔑 Войти',
                'btn_register': '📝 Регистрация',
                'btn_logout': '🚪 Выйти',
                'btn_change_password': '🔐 Сменить пароль',
                'btn_delete_account': '🗑️ Удалить аккаунт',
                'btn_share_phone': '📱 Поделиться номером',
                'btn_share_location': '📍 Поделиться местоположением',
            },

            Language.EN: {
                # General
                'welcome': '👋 Welcome to the bot!',
                'start_registration': '📝 Start Registration',
                'main_menu': '🏠 Main Menu',
                'profile': '👤 Profile',
                'settings': '⚙️ Settings',
                'help': '❓ Help',
                'about': 'ℹ️ About',
                'back': '◀️ Back',
                'cancel': '❌ Cancel',
                'confirm': '✅ Confirm',
                'yes': 'Yes',
                'no': 'No',
                'save': '💾 Save',
                'edit': '✏️ Edit',
                'delete': '🗑️ Delete',
                'search': '🔍 Search',

                # Registration
                'reg_start': '📝 Let\'s start registration! It will take just a few minutes.',
                'reg_name': '👤 Enter your name:',
                'reg_phone': '📱 Enter your phone number:',
                'reg_email': '📧 Enter your email address:',
                'reg_password': '🔐 Create a password (min 8 characters, with uppercase and number):',
                'reg_birthday': '🎂 Enter your birth date (DD.MM.YYYY):',
                'reg_city': '🏙️ Enter your city:',
                'reg_bio': '📝 Tell us about yourself (optional):',
                'reg_interests': '🎯 Select your interests:',
                'reg_avatar': '🖼️ Send a profile photo (optional):',
                'reg_confirm': '✅ Confirm your information:',
                'reg_success': '🎉 Registration completed successfully! Welcome!',
                'reg_error': '❌ Error during registration. Try again later.',
                'reg_skip': '⏭️ Skip',

                # Continue with English translations...
            },

            Language.UZ: {
                # Uzbek translations
                'welcome': '👋 Botga xush kelibsiz!',
                'start_registration': '📝 Ro\'yxatdan o\'tish',
                'main_menu': '🏠 Asosiy menyu',
                'profile': '👤 Profil',
                'settings': '⚙️ Sozlamalar',
                'help': '❓ Yordam',
                'about': 'ℹ️ Bot haqida',
                'back': '◀️ Orqaga',
                'cancel': '❌ Bekor qilish',
                # ... continue with Uzbek translations
            }
        }

    def get_string(self, key: str, lang: Language, **kwargs) -> str:
        """Get localized string with formatting"""
        try:
            string = self.strings[lang].get(key, self.strings[Language.RU].get(key, key))
            if kwargs:
                string = string.format(**kwargs)
            return string
        except:
            return key


# ==================== KEYBOARD MANAGER ====================

class KeyboardManager:
    def __init__(self, localization: LocalizationManager):
        self.localization = localization

    def get_main_keyboard(self, lang: Language, is_admin: bool = False):
        """Get main menu keyboard"""
        keyboard = [
            [
                InlineKeyboardButton(self.localization.get_string('profile', lang), callback_data='profile'),
                InlineKeyboardButton(self.localization.get_string('settings', lang), callback_data='settings')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('my_friends', lang), callback_data='friends'),
                InlineKeyboardButton(self.localization.get_string('messages', lang), callback_data='messages')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('achievements', lang), callback_data='achievements'),
                InlineKeyboardButton(self.localization.get_string('rating', lang), callback_data='rating')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('find_friends', lang), callback_data='find_friends'),
                InlineKeyboardButton(self.localization.get_string('premium', lang), callback_data='premium')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('support', lang), callback_data='support'),
                InlineKeyboardButton(self.localization.get_string('feedback', lang), callback_data='feedback')
            ]
        ]

        if is_admin:
            keyboard.append([
                InlineKeyboardButton(self.localization.get_string('admin_panel', lang), callback_data='admin')
            ])

        return InlineKeyboardMarkup(keyboard)

    def get_profile_keyboard(self, lang: Language):
        """Get profile management keyboard"""
        keyboard = [
            [
                InlineKeyboardButton(self.localization.get_string('edit', lang), callback_data='profile_edit'),
                InlineKeyboardButton(self.localization.get_string('share', lang), callback_data='profile_share')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('change_password', lang),
                                     callback_data='change_password'),
                InlineKeyboardButton(self.localization.get_string('delete_account', lang),
                                     callback_data='delete_account')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('back', lang), callback_data='main_menu')
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_settings_keyboard(self, lang: Language):
        """Get settings keyboard"""
        keyboard = [
            [
                InlineKeyboardButton(self.localization.get_string('settings_language', lang),
                                     callback_data='settings_language'),
                InlineKeyboardButton(self.localization.get_string('settings_notifications', lang),
                                     callback_data='settings_notifications')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('settings_privacy', lang),
                                     callback_data='settings_privacy'),
                InlineKeyboardButton(self.localization.get_string('settings_security', lang),
                                     callback_data='settings_security')
            ],
            [
                InlineKeyboardButton(self.localization.get_string('back', lang), callback_data='main_menu')
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_interests_keyboard(self, selected_interests=None):
        """Get interests selection keyboard"""
        if selected_interests is None:
            selected_interests = []

        interests = [
            'Technology', 'Sports', 'Music', 'Movies', 'Reading',
            'Travel', 'Cooking', 'Gaming', 'Art', 'Fashion',
            'Fitness', 'Photography'
        ]

        keyboard = []
        row = []
        for i, interest in enumerate(interests):
            status = '✅ ' if interest in selected_interests else ''
            button = InlineKeyboardButton(
                f"{status}{interest}",
                callback_data=f"interest_{interest}"
            )
            row.append(button)
            if len(row) == 2:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        keyboard.append([
            InlineKeyboardButton('✅ Confirm', callback_data='interests_confirm'),
            InlineKeyboardButton('❌ Cancel', callback_data='interests_cancel')
        ])

        return InlineKeyboardMarkup(keyboard)

    def get_confirmation_keyboard(self, lang: Language):
        """Get confirmation keyboard"""
        keyboard = [
            [
                InlineKeyboardButton(self.localization.get_string('yes', lang), callback_data='confirm_yes'),
                InlineKeyboardButton(self.localization.get_string('no', lang), callback_data='confirm_no')
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_language_keyboard(self):
        """Get language selection keyboard"""
        keyboard = [
            [
                InlineKeyboardButton('🇷🇺 Русский', callback_data='lang_ru'),
                InlineKeyboardButton('🇬🇧 English', callback_data='lang_en'),
                InlineKeyboardButton('🇺🇿 O\'zbek', callback_data='lang_uz')
            ]
        ]
        return InlineKeyboardMarkup(keyboard)


# ==================== ACHIEVEMENTS MANAGER ====================

class AchievementsManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.achievements = {
            'first_login': {'name': 'First Steps', 'points': 10},
            'profile_complete': {'name': 'Social Butterfly', 'points': 20},
            'sent_10_messages': {'name': 'Chatterbox', 'points': 30},
            'received_10_messages': {'name': 'Popular', 'points': 30},
            'referred_5_friends': {'name': 'Influencer', 'points': 50},
            'premium_user': {'name': 'Premium Member', 'points': 100},
            'active_30_days': {'name': 'Loyal User', 'points': 50},
            'achievement_hunter': {'name': 'Achievement Hunter', 'points': 200}
        }

    async def check_and_award_achievement(self, user_id: int, achievement_type: str):
        """Check and award achievement if conditions met"""
        # Implementation would check user stats and award achievement
        pass


# ==================== BOT CLASS ====================

class AdvancedTelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.db = DatabaseManager(DATABASE_FILE)
        self.security = SecurityManager()
        self.localization = LocalizationManager()
        self.keyboards = KeyboardManager(self.localization)
        self.achievements = AchievementsManager(self.db)

        # Setup logging
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
        self.logger = logging.getLogger(__name__)

        # Temporary storage for registration data
        self.reg_data = {}
        self.temp_data = {}

        # Rate limiting
        self.rate_limits = {}

        # Initialize application
        self.application = None

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        self.logger.error(f"Update {update} caused error {context.error}")

        try:
            if update and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ An error occurred. Please try again later."
                )
        except:
            pass

    def rate_limit_decorator(limit: int = 5, period: int = 60):
        """Rate limiting decorator"""

        def decorator(func):
            @wraps(func)
            async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
                user_id = update.effective_user.id
                current_time = time.time()

                if user_id not in self.rate_limits:
                    self.rate_limits[user_id] = []

                # Clean old requests
                self.rate_limits[user_id] = [
                    t for t in self.rate_limits[user_id]
                    if current_time - t < period
                ]

                if len(self.rate_limits[user_id]) >= limit:
                    await update.message.reply_text(
                        f"⚠️ Too many requests. Please wait {period} seconds."
                    )
                    return

                self.rate_limits[user_id].append(current_time)
                return await func(self, update, context, *args, **kwargs)

            return wrapper

        return decorator

    async def check_user_status(self, update: Update) -> bool:
        """Check if user is allowed to use the bot"""
        user_id = update.effective_user.id

        # Check if user exists and is active
        user = self.db.get_user(user_id)
        if not user:
            return True  # New users are allowed to register

        if user['status'] == 'banned':
            await update.message.reply_text(
                self.localization.get_string('error_user_banned', Language.RU)
            )
            return False

        return True

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        user = update.effective_user
        user_id = user.id

        # Check if user exists
        db_user = self.db.get_user(user_id)

        if db_user:
            # Existing user - show main menu
            lang = Language(db_user['language'])
            await update.message.reply_text(
                f"{self.localization.get_string('welcome', lang)} {user.first_name}!",
                reply_markup=self.keyboards.get_main_keyboard(
                    lang,
                    db_user['role'] in ['admin', 'moderator']
                )
            )

            # Log activity
            self.db.log_activity(user_id, 'login', 'User logged in')
        else:
            # New user - start registration
            await self.start_registration(update, context)

    async def start_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start registration process"""
        user_id = update.effective_user.id

        # Initialize registration data
        self.reg_data[user_id] = {
            'user_id': user_id,
            'username': update.effective_user.username,
            'first_name': update.effective_user.first_name,
            'last_name': update.effective_user.last_name,
            'step': REG_NAME
        }

        await update.message.reply_text(
            self.localization.get_string('reg_start', Language.RU)
        )
        await update.message.reply_text(
            self.localization.get_string('reg_name', Language.RU)
        )

        return REG_NAME

    async def registration_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle registration steps"""
        user_id = update.effective_user.id
        text = update.message.text

        if user_id not in self.reg_data:
            await update.message.reply_text("Please use /start to begin registration")
            return ConversationHandler.END

        current_step = self.reg_data[user_id]['step']

        if text == self.localization.get_string('cancel', Language.RU):
            await update.message.reply_text(
                "Registration cancelled.",
                reply_markup=ReplyKeyboardRemove()
            )
            del self.reg_data[user_id]
            return ConversationHandler.END

        if current_step == REG_NAME:
            self.reg_data[user_id]['name'] = text
            self.reg_data[user_id]['step'] = REG_PHONE

            # Request phone with keyboard
            contact_keyboard = [[KeyboardButton(
                self.localization.get_string('btn_share_phone', Language.RU),
                request_contact=True
            )]]
            reply_markup = ReplyKeyboardMarkup(
                contact_keyboard,
                resize_keyboard=True,
                one_time_keyboard=True
            )

            await update.message.reply_text(
                self.localization.get_string('reg_phone', Language.RU),
                reply_markup=reply_markup
            )
            return REG_PHONE

        elif current_step == REG_PHONE:
            # Handle phone input
            if update.message.contact:
                phone = update.message.contact.phone_number
            else:
                phone = text

            if not self.security.validate_phone(phone):
                await update.message.reply_text(
                    self.localization.get_string('error_invalid_input', Language.RU)
                )
                return REG_PHONE

            # Check if phone already exists
            if self.db.get_user_by_phone(phone):
                await update.message.reply_text(
                    self.localization.get_string('error_phone_exists', Language.RU)
                )
                return REG_PHONE

            self.reg_data[user_id]['phone'] = phone
            self.reg_data[user_id]['step'] = REG_EMAIL
            await update.message.reply_text(
                self.localization.get_string('reg_email', Language.RU),
                reply_markup=ReplyKeyboardRemove()
            )
            return REG_EMAIL

        elif current_step == REG_EMAIL:
            if not self.security.validate_email(text):
                await update.message.reply_text(
                    self.localization.get_string('error_invalid_input', Language.RU)
                )
                return REG_EMAIL

            # Check if email already exists
            if self.db.get_user_by_email(text):
                await update.message.reply_text(
                    self.localization.get_string('error_email_exists', Language.RU)
                )
                return REG_EMAIL

            self.reg_data[user_id]['email'] = text
            self.reg_data[user_id]['step'] = REG_PASSWORD
            await update.message.reply_text(
                self.localization.get_string('reg_password', Language.RU)
            )
            return REG_PASSWORD

        elif current_step == REG_PASSWORD:
            is_valid, message = self.security.validate_password(text)
            if not is_valid:
                await update.message.reply_text(message)
                return REG_PASSWORD

            self.reg_data[user_id]['password_hash'] = self.security.hash_password(text)
            self.reg_data[user_id]['step'] = REG_BIRTHDAY
            await update.message.reply_text(
                self.localization.get_string('reg_birthday', Language.RU)
            )
            return REG_BIRTHDAY

        elif current_step == REG_BIRTHDAY:
            # Validate date format
            try:
                datetime.strptime(text, '%d.%m.%Y')
                self.reg_data[user_id]['birthday'] = text
                self.reg_data[user_id]['step'] = REG_CITY
                await update.message.reply_text(
                    self.localization.get_string('reg_city', Language.RU)
                )
                return REG_CITY
            except ValueError:
                await update.message.reply_text(
                    self.localization.get_string('error_invalid_input', Language.RU)
                )
                return REG_BIRTHDAY

        elif current_step == REG_CITY:
            self.reg_data[user_id]['city'] = text
            self.reg_data[user_id]['step'] = REG_BIO
            await update.message.reply_text(
                self.localization.get_string('reg_bio', Language.RU)
            )
            return REG_BIO

        elif current_step == REG_BIO:
            self.reg_data[user_id]['bio'] = text
            self.reg_data[user_id]['step'] = REG_INTERESTS

            # Show interests selection
            await update.message.reply_text(
                self.localization.get_string('reg_interests', Language.RU),
                reply_markup=self.keyboards.get_interests_keyboard()
            )
            return REG_INTERESTS

        return ConversationHandler.END

    async def interests_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle interests selection"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        data = query.data

        if user_id not in self.reg_data:
            return ConversationHandler.END

        if data.startswith('interest_'):
            interest = data.replace('interest_', '')

            if 'interests' not in self.reg_data[user_id]:
                self.reg_data[user_id]['interests'] = []

            if interest in self.reg_data[user_id]['interests']:
                self.reg_data[user_id]['interests'].remove(interest)
            else:
                self.reg_data[user_id]['interests'].append(interest)

            # Update keyboard
            await query.edit_message_reply_markup(
                reply_markup=self.keyboards.get_interests_keyboard(
                    self.reg_data[user_id]['interests']
                )
            )

        elif data == 'interests_confirm':
            self.reg_data[user_id]['step'] = REG_AVATAR
            await query.edit_message_text(
                self.localization.get_string('reg_avatar', Language.RU)
            )
            return REG_AVATAR

        elif data == 'interests_cancel':
            await query.edit_message_text(
                "Interest selection cancelled."
            )
            return ConversationHandler.END

    async def avatar_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle avatar upload"""
        user_id = update.effective_user.id

        if user_id not in self.reg_data:
            return ConversationHandler.END

        if update.message.photo:
            # Get the largest photo
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)

            # Save photo (in production, you'd save to cloud storage)
            self.reg_data[user_id]['avatar'] = photo.file_id

        # Show confirmation
        await self.show_registration_confirmation(update, context)
        return ConversationHandler.END

    async def show_registration_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show registration confirmation"""
        user_id = update.effective_user.id
        data = self.reg_data[user_id]

        # Create user in database
        user_data = UserData(
            user_id=data['user_id'],
            username=data.get('username'),
            first_name=data.get('first_name'),
            last_name=data.get('last_name'),
            phone=data.get('phone'),
            email=data.get('email'),
            password_hash=data.get('password_hash'),
            birthday=data.get('birthday'),
            city=data.get('city'),
            bio=data.get('bio'),
            interests=','.join(data.get('interests', [])),
            avatar=data.get('avatar')
        )

        if self.db.create_user(user_data):
            # Create session
            session_id = self.db.create_session(user_id)
            context.user_data['session_id'] = session_id

            # Log activity
            self.db.log_activity(user_id, 'registration', 'User registered')

            await update.message.reply_text(
                self.localization.get_string('reg_success', Language.RU),
                reply_markup=self.keyboards.get_main_keyboard(Language.RU)
            )

            # Send welcome notification
            await self.send_notification(
                user_id,
                "Welcome!",
                "Thank you for registering! Explore the bot features."
            )
        else:
            await update.message.reply_text(
                self.localization.get_string('reg_error', Language.RU)
            )

        del self.reg_data[user_id]

    async def profile_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle profile view"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        user = self.db.get_user(user_id)

        if not user:
            await query.edit_message_text("Profile not found. Please register first.")
            return

        # Format profile message
        profile_text = f"👤 **Your Profile**\n\n"
        profile_text += f"**Name:** {user['first_name']} {user['last_name'] or ''}\n"
        profile_text += f"**Username:** @{user['username']}\n"
        profile_text += f"**Phone:** {user['phone']}\n"
        profile_text += f"**Email:** {user['email']}\n"
        profile_text += f"**Birthday:** {user['birthday']}\n"
        profile_text += f"**City:** {user['city']}\n"
        profile_text += f"**Bio:** {user['bio'] or 'Not provided'}\n"
        profile_text += f"**Interests:** {user['interests'] or 'Not selected'}\n"
        profile_text += f"**Rating:** ⭐ {user['rating']}\n"
        profile_text += f"**Role:** {user['role']}\n"
        profile_text += f"**Registered:** {user['registration_date']}\n"

        # Send profile photo if exists
        if user['avatar']:
            await query.message.reply_photo(
                photo=user['avatar'],
                caption=profile_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self.keyboards.get_profile_keyboard(Language(user['language']))
            )
            await query.message.delete()
        else:
            await query.edit_message_text(
                profile_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self.keyboards.get_profile_keyboard(Language(user['language']))
            )

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin panel"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        user = self.db.get_user(user_id)

        if not user or user['role'] not in ['admin', 'moderator']:
            await query.edit_message_text(
                self.localization.get_string('error_unauthorized', Language.RU)
            )
            return

        # Get statistics
        total_users = self.db.get_user_count()
        active_today = self.db.get_active_users_today()
        new_today = self.db.get_new_users_today()

        admin_text = "👨‍💼 **Admin Panel**\n\n"
        admin_text += f"📊 **Statistics:**\n"
        admin_text += f"• Total Users: {total_users}\n"
        admin_text += f"• Active Today: {active_today}\n"
        admin_text += f"• New Today: {new_today}\n\n"
        admin_text += "🛠 **Admin Actions:**\n"
        admin_text += "• /broadcast - Send message to all users\n"
        admin_text += "• /stats - Detailed statistics\n"
        admin_text += "• /users - User management\n"
        admin_text += "• /logs - View activity logs\n"

        keyboard = [
            [
                InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
                InlineKeyboardButton("👥 Users", callback_data="admin_users")
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton("📋 Reports", callback_data="admin_reports")
            ],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"),
                InlineKeyboardButton("📁 Logs", callback_data="admin_logs")
            ],
            [
                InlineKeyboardButton("◀️ Back", callback_data="main_menu")
            ]
        ]

        await query.edit_message_text(
            admin_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def admin_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin broadcast"""
        user_id = update.effective_user.id
        user = self.db.get_user(user_id)

        if not user or user['role'] not in ['admin', 'moderator']:
            await update.message.reply_text("Unauthorized access")
            return

        await update.message.reply_text(
            "📢 **Send broadcast message**\n\n"
            "Enter the message you want to send to all users:",
            parse_mode=ParseMode.MARKDOWN
        )

        return ADMIN_BROADCAST

    async def broadcast_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle broadcast message input"""
        message_text = update.message.text

        await update.message.reply_text(
            f"Broadcast message:\n\n{message_text}\n\n"
            "Confirm sending to all users?",
            reply_markup=self.keyboards.get_confirmation_keyboard(Language.RU)
        )

        context.user_data['broadcast_message'] = message_text
        return ConversationHandler.END

    async def send_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send broadcast to all users"""
        query = update.callback_query
        await query.answer()

        if query.data == 'confirm_yes':
            message_text = context.user_data.get('broadcast_message')

            # Get all users (in production, use pagination)
            # This is simplified
            sent_count = 0
            failed_count = 0

            await query.edit_message_text(
                "📢 Broadcasting message to all users...\n"
                "This may take a while."
            )

            # Here you would iterate through all users and send messages
            # For now, just show confirmation
            await query.edit_message_text(
                f"✅ Broadcast completed!\n"
                f"Sent: {sent_count}\n"
                f"Failed: {failed_count}"
            )
        else:
            await query.edit_message_text("Broadcast cancelled.")

    async def settings_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle settings menu"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        user = self.db.get_user(user_id)

        if not user:
            await query.edit_message_text("Please register first.")
            return

        lang = Language(user['language'])

        await query.edit_message_text(
            self.localization.get_string('settings_menu', lang),
            reply_markup=self.keyboards.get_settings_keyboard(lang)
        )

    async def settings_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle language settings"""
        query = update.callback_query
        await query.answer()

        await query.edit_message_text(
            "Select your language:",
            reply_markup=self.keyboards.get_language_keyboard()
        )

    async def set_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set user language"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        lang_code = query.data.replace('lang_', '')

        # Map to Language enum
        lang_map = {
            'ru': Language.RU,
            'en': Language.EN,
            'uz': Language.UZ
        }

        new_lang = lang_map.get(lang_code, Language.RU)

        # Update user language
        self.db.update_user(user_id, language=new_lang.value)

        await query.edit_message_text(
            self.localization.get_string('settings_saved', new_lang),
            reply_markup=self.keyboards.get_main_keyboard(new_lang)
        )

    async def settings_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle notification settings"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        user = self.db.get_user(user_id)
        lang = Language(user['language'])

        keyboard = [
            [
                InlineKeyboardButton(
                    self.localization.get_string('settings_notifications_all', lang),
                    callback_data='notif_all'
                )
            ],
            [
                InlineKeyboardButton(
                    self.localization.get_string('settings_notifications_important', lang),
                    callback_data='notif_important'
                )
            ],
            [
                InlineKeyboardButton(
                    self.localization.get_string('settings_notifications_none', lang),
                    callback_data='notif_none'
                )
            ],
            [
                InlineKeyboardButton(
                    self.localization.get_string('back', lang),
                    callback_data='settings'
                )
            ]
        ]

        await query.edit_message_text(
            self.localization.get_string('settings_notifications', lang),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def set_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set notification preference"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        notif_type = query.data.replace('notif_', '')

        notif_map = {
            'all': NotificationType.ALL,
            'important': NotificationType.IMPORTANT,
            'none': NotificationType.NONE
        }

        new_notif = notif_map.get(notif_type, NotificationType.ALL)

        # Update user preference
        self.db.update_user(user_id, notification_pref=new_notif.value)

        user = self.db.get_user(user_id)
        lang = Language(user['language'])

        await query.edit_message_text(
            self.localization.get_string('settings_saved', lang),
            reply_markup=self.keyboards.get_settings_keyboard(lang)
        )

    async def settings_privacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle privacy settings"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        user = self.db.get_user(user_id)
        lang = Language(user['language'])

        keyboard = [
            [
                InlineKeyboardButton(
                    self.localization.get_string('settings_privacy_public', lang),
                    callback_data='privacy_public'
                )
            ],
            [
                InlineKeyboardButton(
                    self.localization.get_string('settings_privacy_contacts', lang),
                    callback_data='privacy_contacts'
                )
            ],
            [
                InlineKeyboardButton(
                    self.localization.get_string('settings_privacy_private', lang),
                    callback_data='privacy_private'
                )
            ],
            [
                InlineKeyboardButton(
                    self.localization.get_string('back', lang),
                    callback_data='settings'
                )
            ]
        ]

        await query.edit_message_text(
            self.localization.get_string('settings_privacy', lang),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def set_privacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set privacy level"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        privacy_level = query.data.replace('privacy_', '')

        privacy_map = {
            'public': PrivacyLevel.PUBLIC,
            'contacts': PrivacyLevel.CONTACTS,
            'private': PrivacyLevel.PRIVATE
        }

        new_privacy = privacy_map.get(privacy_level, PrivacyLevel.PUBLIC)

        # Update user privacy
        self.db.update_user(user_id, privacy_level=new_privacy.value)

        user = self.db.get_user(user_id)
        lang = Language(user['language'])

        await query.edit_message_text(
            self.localization.get_string('settings_saved', lang),
            reply_markup=self.keyboards.get_settings_keyboard(lang)
        )

    async def send_notification(self, user_id: int, title: str, content: str):
        """Send notification to user"""
        try:
            # Store notification in database
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO notifications (user_id, title, content, type)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, title, content, 'system'))

            # Try to send via Telegram
            await self.application.bot.send_message(
                chat_id=user_id,
                text=f"🔔 **{title}**\n\n{content}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            self.logger.error(f"Failed to send notification to {user_id}: {e}")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command"""
        help_text = """
🤖 **Bot Commands**

**Basic Commands:**
/start - Start the bot
/help - Show this help
/profile - View your profile
/settings - Bot settings
/search - Search users
/friends - Manage friends

**Registration:**
/register - Start registration
/login - Login to account
/logout - Logout

**Premium Features:**
/premium - Premium info
/stats - Your statistics

**Support:**
/feedback - Send feedback
/report - Report a problem
/support - Contact support

**Admin Commands:**
/broadcast - Send message to all
/stats - Bot statistics
/users - User management
/logs - View logs
"""
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def feedback_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle feedback command"""
        await update.message.reply_text(
            "📝 **Send Feedback**\n\n"
            "Please write your feedback, suggestions, or report any issues:",
            parse_mode=ParseMode.MARKDOWN
        )
        return FEEDBACK_TEXT

    async def feedback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle feedback input"""
        feedback_text = update.message.text
        user_id = update.effective_user.id

        # Store feedback
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO feedback (user_id, feedback_text)
                VALUES (?, ?)
            ''', (user_id, feedback_text))

        await update.message.reply_text(
            "✅ Thank you for your feedback! We'll review it soon."
        )

        # Notify admins
        for admin_id in ADMIN_IDS:
            try:
                user = update.effective_user
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📝 New feedback from @{user.username or user.first_name}:\n\n{feedback_text}"
                )
            except:
                pass

        return ConversationHandler.END

    async def search_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Search users"""
        if not context.args:
            await update.message.reply_text(
                "Usage: /search [name or username]"
            )
            return

        query = ' '.join(context.args)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, first_name, last_name, username, city, avatar
                FROM users
                WHERE (first_name LIKE ? OR last_name LIKE ? OR username LIKE ?)
                AND status = 'active'
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%', f'%{query}%'))

            users = cursor.fetchall()

        if not users:
            await update.message.reply_text("No users found.")
            return

        result_text = f"🔍 Search results for '{query}':\n\n"

        for user in users:
            result_text += f"👤 {user['first_name']} {user['last_name'] or ''}\n"
            result_text += f"   @{user['username']}\n"
            result_text += f"   City: {user['city'] or 'Not specified'}\n"
            result_text += f"   [View profile](tg://user?id={user['user_id']})\n\n"

        await update.message.reply_text(
            result_text,
            parse_mode=ParseMode.MARKDOWN
        )

    async def premium_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show premium information"""
        premium_text = """
💎 **Premium Features**

Upgrade to Premium and get access to:

✅ **Advanced Features:**
• Unlimited messages
• Priority support
• Advanced search filters
• View who visited your profile
• Custom themes
• No ads

✅ **Communication:**
• Voice messages
• Video calls
• Group chat creation
• File sharing up to 2GB

✅ **Profile Benefits:**
• Premium badge
• Profile highlighting
• Extended bio
• More interests
• Priority in search

**Price:** $9.99/month

Contact @admin to upgrade to Premium!
"""
        await update.message.reply_text(premium_text, parse_mode=ParseMode.MARKDOWN)

    async def my_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user statistics"""
        user_id = update.effective_user.id

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Get user stats
            cursor.execute('''
                SELECT 
                    (SELECT COUNT(*) FROM messages WHERE sender_id = ?) as messages_sent,
                    (SELECT COUNT(*) FROM messages WHERE receiver_id = ?) as messages_received,
                    (SELECT COUNT(*) FROM referrals WHERE referrer_id = ?) as referrals,
                    (SELECT COUNT(*) FROM user_achievements WHERE user_id = ?) as achievements,
                    rating, total_interactions
                FROM users WHERE user_id = ?
            ''', (user_id, user_id, user_id, user_id, user_id))

            stats = cursor.fetchone()

            if stats:
                stats_text = f"📊 **Your Statistics**\n\n"
                stats_text += f"📨 Messages sent: {stats['messages_sent']}\n"
                stats_text += f"📬 Messages received: {stats['messages_received']}\n"
                stats_text += f"👥 Referrals: {stats['referrals']}\n"
                stats_text += f"🏆 Achievements: {stats['achievements']}\n"
                stats_text += f"⭐ Rating: {stats['rating']}\n"
                stats_text += f"🔄 Total interactions: {stats['total_interactions']}\n"

                await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text("No statistics available.")

    async def cancel_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current conversation"""
        await update.message.reply_text(
            "Operation cancelled.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all button callbacks"""
        query = update.callback_query
        await query.answer()

        data = query.data

        # Route to appropriate handler
        handlers = {
            'profile': self.profile_handler,
            'settings': self.settings_handler,
            'admin': self.admin_panel,
            'admin_broadcast': self.admin_broadcast,
            'settings_language': self.settings_language,
            'settings_notifications': self.settings_notifications,
            'settings_privacy': self.settings_privacy,
            'main_menu': self.main_menu_handler
        }

        if data in handlers:
            await handlers[data](update, context)

    async def main_menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to main menu"""
        query = update.callback_query

        user_id = update.effective_user.id
        user = self.db.get_user(user_id)

        if user:
            lang = Language(user['language'])
            is_admin = user['role'] in ['admin', 'moderator']

            await query.edit_message_text(
                self.localization.get_string('main_menu', lang),
                reply_markup=self.keyboards.get_main_keyboard(lang, is_admin)
            )

    async def post_init(self, application: Application):
        """Setup bot after initialization"""
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help"),
            BotCommand("profile", "View your profile"),
            BotCommand("settings", "Bot settings"),
            BotCommand("search", "Search users"),
            BotCommand("feedback", "Send feedback"),
            BotCommand("premium", "Premium info"),
            BotCommand("stats", "Your statistics")
        ]

        await application.bot.set_my_commands(commands)

        # Get bot info
        bot_info = await application.bot.get_me()
        global BOT_USERNAME
        BOT_USERNAME = bot_info.username

        self.logger.info(f"Bot started: @{BOT_USERNAME}")

    def setup_handlers(self):
        """Setup all handlers"""
        # Create conversation handler for registration
        reg_conv = ConversationHandler(
            entry_points=[
                CommandHandler('register', self.start_registration),
                MessageHandler(filters.Regex('^📝 Register$'), self.start_registration)
            ],
            states={
                REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.registration_handler)],
                REG_PHONE: [
                    MessageHandler(filters.CONTACT, self.registration_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.registration_handler)
                ],
                REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.registration_handler)],
                REG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.registration_handler)],
                REG_BIRTHDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.registration_handler)],
                REG_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.registration_handler)],
                REG_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.registration_handler)],
                REG_INTERESTS: [CallbackQueryHandler(self.interests_callback)],
                REG_AVATAR: [MessageHandler(filters.PHOTO, self.avatar_handler)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_conversation)],
            name="registration",
            persistent=False
        )

        # Feedback conversation
        feedback_conv = ConversationHandler(
            entry_points=[CommandHandler('feedback', self.feedback_command)],
            states={
                FEEDBACK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.feedback_handler)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_conversation)]
        )

        # Broadcast conversation
        broadcast_conv = ConversationHandler(
            entry_points=[CommandHandler('broadcast', self.admin_broadcast)],
            states={
                ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.broadcast_handler)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_conversation)]
        )

        # Add handlers
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('search', self.search_users))
        self.application.add_handler(CommandHandler('premium', self.premium_info))
        self.application.add_handler(CommandHandler('stats', self.my_stats))

        # Add conversation handlers
        self.application.add_handler(reg_conv)
        self.application.add_handler(feedback_conv)
        self.application.add_handler(broadcast_conv)

        # Add callback query handler
        self.application.add_handler(CallbackQueryHandler(self.button_handler))

        # Add error handler
        self.application.add_error_handler(self.error_handler)

    async def run(self):
        """Run the bot"""
        # Create application
        persistence = PicklePersistence(filepath="bot_persistence")
        self.application = Application.builder() \
            .token(self.token) \
            .persistence(persistence) \
            .post_init(self.post_init) \
            .build()

        # Setup handlers
        self.setup_handlers()

        # Start bot
        self.logger.info("Starting bot...")
        await self.application.initialize()
        await self.application.start()

        # Start polling
        self.logger.info("Bot is running. Press Ctrl+C to stop.")
        await self.application.updater.start_polling()

        # Run until stopped
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Stopping bot...")
            await self.application.stop()


# ==================== MAIN FUNCTION ====================

async def main():
    """Main function"""
    bot = AdvancedTelegramBot(TOKEN)

    try:
        await bot.run()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())