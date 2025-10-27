import asyncio
import os
import sys
import traceback


def setup_environment():
    """Настройка окружения"""
    # Добавляем текущую директорию в путь
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    # Устанавливаем путь к плагинам PyQt5
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(
        current_dir, "PyQt5", "Qt5", "plugins", "platforms"
    )


async def main_async():
    """Асинхронная main функция"""
    try:
        print("🔄 Инициализация базы данных...")

        # Импорты внутри функции для изоляции ошибок
        from database import get_async_engine, init_databases
        from models import Base
        from sqlalchemy import text

        # Инициализируем БД
        init_databases()
        async_engine = get_async_engine()

        async with async_engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
            await conn.run_sync(Base.metadata.create_all)

        print("✅ База данных инициализирована")

        # Импортируем и запускаем основное приложение
        from login_window import (
            LoginWindow,
            insert_data_database,
            setup_database,
        )
        from PyQt5 import QtWidgets
        from qasync import QEventLoop

        # Настраиваем начальные данные
        await setup_database()
        await insert_data_database()

        # Создаем Qt приложение
        app = QtWidgets.QApplication(sys.argv)
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)

        # Создаем окно логина
        window = LoginWindow()
        window.show()

        # Создаем учителя по умолчанию
        window.create_default_teacher()

        print("🚀 Приложение запущено успешно!")

        # Запускаем event loop
        await loop.run_forever()

    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()
        input("Нажмите Enter для выхода...")


def main():
    """Основная функция"""
    try:
        setup_environment()

        # Запускаем асинхронную main
        asyncio.run(main_async())

    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")
        traceback.print_exc()
        input("Нажмите Enter для выхода...")


if __name__ == "__main__":
    main()
