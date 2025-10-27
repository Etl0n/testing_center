# database.py
from sqlalchemy import URL, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    sessionmaker,
)  # Правильный импорт для синхронных сессий


def init_databases():
    """Инициализация подключений к БД"""
    global sync_engine, async_engine, session_async_factory, session_sync_factory

    from config import init_settings

    try:
        settings = init_settings()

        # Инициализируем синхронный engine с настройками пула
        sync_engine = create_engine(
            url=settings.DATABASE_URL_psycopg,
            echo=True,
            pool_size=10,  # Размер пула
            max_overflow=20,  # Максимальное количество соединений сверх pool_size
            pool_pre_ping=True,  # Проверка соединения перед использованием
            pool_recycle=3600,  # Пересоздавать соединения каждый час
        )

        # Инициализируем асинхронный engine с настройками пула
        async_engine = create_async_engine(
            url=settings.DATABASE_URL_asyncpg,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,  # Для async может потребоваться альтернативное решение
            pool_recycle=3600,
        )

        # Создаем session factories
        session_async_factory = async_sessionmaker(
            get_async_engine(), expire_on_commit=False, class_=AsyncSession
        )
        session_sync_factory = sessionmaker(
            bind=get_sync_engine(), expire_on_commit=False
        )

        print("✅ Базы данных инициализированы успешно")

    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

        # Создаем заглушки чтобы избежать ошибок импорта
        class DummyEngine:
            def dispose(self):
                pass

        sync_engine = DummyEngine()
        async_engine = DummyEngine()
        session_async_factory = None
        session_sync_factory = None


# Функции для безопасного доступа к engines
def get_sync_engine():
    if sync_engine is None:
        raise RuntimeError(
            "Sync engine не инициализирован. Вызовите init_databases() сначала."
        )
    return sync_engine


def get_async_engine():
    if async_engine is None:
        raise RuntimeError(
            "Async engine не инициализирован. Вызовите init_databases() сначала."
        )
    return async_engine


def get_async_session():
    if session_async_factory is None:
        raise RuntimeError(
            "Async session factory не инициализирована. Вызовите init_databases() сначала."
        )
    return session_async_factory()


def get_sync_session():
    if session_sync_factory is None:
        raise RuntimeError(
            "Sync session factory не инициализирована. Вызовите init_databases() сначала."
        )
    return session_sync_factory()
