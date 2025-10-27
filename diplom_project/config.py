# config.py
import base64
import os
import sys
import tempfile

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASS: str
    DB_NAME: str

    @classmethod
    def from_encrypted_file(cls, encrypted_file_path, password):
        """Загрузка настроек из зашифрованного файла"""
        try:
            # Генерация ключа из пароля
            password_bytes = password.encode()
            salt = b'salt_'  # Фиксированная соль для простоты
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password_bytes))

            # Чтение и расшифровка
            with open(encrypted_file_path, 'rb') as f:
                encrypted_data = f.read()

            fernet = Fernet(key)
            decrypted_data = fernet.decrypt(encrypted_data)

            # Создание временного файла с настройками
            with tempfile.NamedTemporaryFile(
                mode='w', delete=False, suffix='.env'
            ) as f:
                f.write(decrypted_data.decode())
                temp_env_file = f.name

            # Загрузка настроек
            settings = cls(_env_file=temp_env_file)

            # Удаление временного файла
            os.unlink(temp_env_file)

            return settings
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
            # Возвращаем настройки по умолчанию или пустые
            return cls()

    @property
    def DATABASE_URL_asyncpg(self):
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def DATABASE_URL_psycopg(self):
        return f"postgresql+psycopg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = SettingsConfigDict(env_file=".env")


def init_settings():
    """Инициализация настроек при запуске"""
    global settings

    # Определяем путь к зашифрованному конфигу
    if getattr(sys, 'frozen', False):
        # Если запущено как .exe
        base_dir = os.path.dirname(sys.executable)
    else:
        # Если запущено как скрипт
        base_dir = os.path.dirname(__file__)

    encrypted_config_path = os.path.join(base_dir, "config_encrypted.dat")

    # Пароль для расшифровки (должен совпадать с паролем при шифровании)
    password = "your_strong_password_12345"

    if os.path.exists(encrypted_config_path):
        # Загружаем из зашифрованного файла
        settings = Settings.from_encrypted_file(
            encrypted_config_path, password
        )
    else:
        # Загружаем из обычного .env (для разработки)
        settings = Settings()

    return settings
