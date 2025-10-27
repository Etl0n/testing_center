import importlib
import sys


def check_module(module_name):
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def main():
    modules = [
        'pandas',
        'pandas._libs.tslibs.base',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.np_datetime',
        'pandas._libs.tslibs.period',
        'pandas._libs.tslibs.timedeltas',
        'openpyxl',
        'sqlalchemy',
        'psycopg2',
        'cryptography',
        'pydantic',
        'pydantic_settings',
        'qasync',
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
    ]

    print("🔍 Проверка зависимостей для PyInstaller...")

    missing = []
    for module in modules:
        if check_module(module):
            print(f"✅ {module}")
        else:
            print(f"❌ {module}")
            missing.append(module)

    if missing:
        print(f"\n⚠️  Отсутствуют модули: {missing}")
        print(
            "Установите их командой: pip install "
            + " ".join(set([m.split('.')[0] for m in missing]))
        )
    else:
        print("\n🎉 Все зависимости доступны!")


if __name__ == "__main__":
    main()
