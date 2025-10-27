import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def encrypt_config(env_file_path, output_file, password):
    """Шифрует .env файл"""
    try:
        # Генерация ключа из пароля
        password_bytes = password.encode()
        salt = b'salt_'  # Такая же соль как в config.py
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password_bytes))

        # Чтение конфигурации
        with open(env_file_path, 'rb') as f:
            config_data = f.read()

        # Шифрование
        fernet = Fernet(key)
        encrypted_data = fernet.encrypt(config_data)

        # Сохранение зашифрованного файла
        with open(output_file, 'wb') as f:
            f.write(encrypted_data)

        print(f"✅ Конфигурация зашифрована и сохранена в {output_file}")
        return True
    except Exception as e:
        print(f"❌ Ошибка шифрования: {e}")
        return False


if __name__ == "__main__":
    # Шифруем .env файл
    encrypt_config(
        ".env", "config_encrypted.dat", "your_strong_password_12345"
    )
