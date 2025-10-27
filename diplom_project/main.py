import asyncio
import os
import sys

sys.path.append(os.path.dirname(__file__))


async def init_database():
    """Инициализация базы данных"""
    try:
        print("🔄 Инициализация базы данных...")

        # Импортируем и инициализируем БД через database.py
        from database import get_async_engine, init_databases
        from models import Base
        from sqlalchemy import text

        # Инициализируем движки БД
        init_databases()

        # Получаем асинхронный движок
        async_engine = get_async_engine()

        # Создаем таблицы
        async with async_engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
            await conn.run_sync(Base.metadata.create_all)

        print("✅ База данных инициализирована")

    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")
        raise


async def setup_initial_data():
    """Настройка начальных данных"""
    try:
        from login_window import insert_data_database, setup_database

        print("🔄 Настройка начальных данных...")
        await setup_database()
        await insert_data_database()
        print("✅ Начальные данные добавлены")

    except Exception as e:
        print(f"❌ Ошибка настройки данных: {e}")
        raise


async def main():
    try:
        # 1. Сначала инициализируем базу данных
        await init_database()

        # 2. Затем настраиваем начальные данные
        await setup_initial_data()

        # 3. Только ПОСЛЕ этого импортируем Qt и создаем приложение
        from login_window import LoginWindow
        from PyQt5 import QtWidgets
        from qasync import QEventLoop

        app = QtWidgets.QApplication(sys.argv)
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)

        # Создаем окно логина
        window = LoginWindow()
        window.show()

        # Создаем учителя по умолчанию
        window.create_default_teacher()

        print("🚀 Приложение запущено")
        await loop.run_forever()

    except Exception as e:
        print(f"❌ Критическая ошибка при запуске: {e}")


if __name__ == "__main__":
    # Простой запуск без сложных проверок
    asyncio.run(main())
