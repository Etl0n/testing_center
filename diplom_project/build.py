import os
import shutil

import PyInstaller.__main__


def build_installer():
    print("🚀 Начинаем сборку проекта...")

    # 1. Шифруем конфигурацию
    print("🔐 Шифруем конфигурацию...")
    from encrypt_config import encrypt_config

    success = encrypt_config(
        ".env", "config_encrypted.dat", "your_strong_password_12345"
    )
    if not success:
        print("❌ Ошибка при шифровании конфигурации")
        return

    # 2. Сначала соберем отладочную версию
    print("🐛 Собираем отладочную версию...")
    PyInstaller.__main__.run(
        [
            'debug_build.py',  # Используем отладочный файл
            '--onefile',
            '--console',  # Важно: оставляем консоль для отладки
            '--name=TestingCenter_Debug',
            '--add-data=config_encrypted.dat;.',
            '--add-data=config.py;.',
            '--add-data=database.py;.',
            '--add-data=models.py;.',
            '--add-data=login_window.py;.',
            '--hidden-import=sqlalchemy',
            '--hidden-import=sqlalchemy.ext.asyncio',
            '--hidden-import=sqlalchemy.orm',
            '--hidden-import=psycopg2',
            '--hidden-import=cryptography',
            '--hidden-import=pydantic',
            '--hidden-import=qasync',
            '--hidden-import=PyQt5',
            '--hidden-import=PyQt5.QtCore',
            '--hidden-import=PyQt5.QtWidgets',
            '--hidden-import=PyQt5.QtGui',
            '--hidden-import=openpyxl',
            '--hidden-import=pandas',
            '--hidden-import=asyncpg',
            '--collect-all=qasync',
            '--collect-all=asyncpg',
            '--noconfirm',
            '--clean',
        ]
    )

    # 3. Теперь собираем финальную версию
    print("📦 Собираем финальную версию...")
    PyInstaller.__main__.run(
        [
            'main.py',
            '--onefile',
            '--windowed',
            '--name=TestingCenter',
            '--add-data=config_encrypted.dat;.',
            '--add-data=config.py;.',
            '--add-data=database.py;.',
            '--add-data=models.py;.',
            '--add-data=login_window.py;.',
            '--hidden-import=sqlalchemy',
            '--hidden-import=sqlalchemy.ext.asyncio',
            '--hidden-import=sqlalchemy.orm',
            '--hidden-import=psycopg2',
            '--hidden-import=cryptography',
            '--hidden-import=pydantic',
            '--hidden-import=qasync',
            '--hidden-import=PyQt5',
            '--hidden-import=PyQt5.QtCore',
            '--hidden-import=PyQt5.QtWidgets',
            '--hidden-import=PyQt5.QtGui',
            '--hidden-import=openpyxl',
            '--hidden-import=pandas',
            '--hidden-import=asyncpg',
            '--collect-all=qasync',
            '--collect-all=asyncpg',
            '--noconfirm',
            '--clean',
        ]
    )

    # 4. Создаем папку для установщика
    print("📁 Подготавливаем файлы для установщика...")
    installer_dir = "installer_files"
    os.makedirs(installer_dir, exist_ok=True)

    # Копируем собранное приложение и зашифрованный конфиг
    if os.path.exists("dist/TestingCenter.exe"):
        shutil.copy2("dist/TestingCenter.exe", installer_dir + "/")
        shutil.copy2("config_encrypted.dat", installer_dir + "/")

        # Также копируем отладочную версию
        if os.path.exists("dist/TestingCenter_Debug.exe"):
            shutil.copy2("dist/TestingCenter_Debug.exe", installer_dir + "/")

    print(
        f"✅ Сборка завершена! Файлы для установщика в папке {installer_dir}/"
    )

    # 5. Создаем Inno Setup скрипт
    create_innosetup_script(installer_dir)


def create_innosetup_script(installer_dir):
    """Создает скрипт для Inno Setup"""
    iss_content = f"""; Inno Setup Script для Центра Тестирования
[Setup]
AppName=Центр Тестирования
AppVersion=1.0
AppPublisher=TestingCenter
DefaultDirName={{autopf}}\\Центр Тестирования
DefaultGroupName=Центр Тестирования
OutputDir={installer_dir}
OutputBaseFilename=TestingCenterSetup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "{installer_dir}\\TestingCenter.exe"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{installer_dir}\\TestingCenter_Debug.exe"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{installer_dir}\\config_encrypted.dat"; DestDir: "{{app}}"; Flags: ignoreversion

[Icons]
Name: "{{group}}\\Центр Тестирования"; Filename: "{{app}}\\TestingCenter.exe"
Name: "{{group}}\\Центр Тестирования (Отладка)"; Filename: "{{app}}\\TestingCenter_Debug.exe"
Name: "{{autodesktop}}\\Центр Тестирования"; Filename: "{{app}}\\TestingCenter.exe"

[Run]
Filename: "{{app}}\\TestingCenter.exe"; Description: "Запустить Центр Тестирования"; Flags: nowait postinstall skipifsilent
"""

    with open("installer.iss", "w", encoding="utf-8") as f:
        f.write(iss_content)

    print("✅ Создан скрипт installer.iss для Inno Setup")


if __name__ == "__main__":
    build_installer()
