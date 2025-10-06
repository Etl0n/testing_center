import asyncio
import base64
import hashlib
import os
import re
import secrets
import string
import sys
from random import sample

import pandas as pd
from database import async_engine, sync_engine
from models import (
    AnswersCheckBoxOrm,
    AnswersReplacementOrm,
    Base,
    GroupsOrm,
    QuestionsCheckBoxOrm,
    QuestionsInputStringOrm,
    QuestionsReplacementOrm,
    StudentsOrm,
    TagsOrm,
    TeachersOrm,
    TestsOrm,
)
from openpyxl import Workbook
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont, QImage, QTextCharFormat
from PyQt5.QtWidgets import QFileDialog
from qasync import QEventLoop
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload, sessionmaker

# Установка пути к плагинам PyQt5 (если нужно)
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(
    os.path.dirname(__file__)[:-14],
    "venv/Lib/site-packages/PyQt5/Qt5/plugins/platforms",
)

session_async_factory = async_sessionmaker(async_engine)
session_sync_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

fmt = QtGui.QTextTableFormat()
fmt.setBorder(1)  # Толщина внешней рамки
fmt.setCellPadding(7)  # Отступ внутри ячеек
fmt.setCellSpacing(0)


# Чистит полносью layout
def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        if item.layout():
            clear_layout(item)


# Миксин для реализации вопросов с очередностью
class QuestionReplacementMixin:
    def handle_replacement_click(self, button):
        # если вопрос уже отвечен — клики игнорируем
        if not self.not_look_question[self.current_index]:
            return

        if button in self.replacement_order:
            self.replacement_order.remove(button)
        else:
            self.replacement_order.append(button)

        self.update_replacement_labels()

        all_selected = len(self.replacement_order) == len(
            self.current_question.get("replacement_buttons", [])
        )

        # включаем "ответить" только если вопрос ещё не отвечен
        self.navigation_on_questions.btn_reply_question.setEnabled(
            all_selected and self.not_look_question[self.current_index]
        )

    def update_replacement_labels(self):
        # Нумерация выбранных кнопок
        for i, button in enumerate(self.replacement_order):
            button.setText(f"{i+1}")
        # Остальные кнопки остаются пустыми
        for button in self.current_question.get("replacement_buttons", []):
            if button not in self.replacement_order:
                button.setText("")


class CustomTextEdit(QtWidgets.QTextEdit):
    def insertFromMimeData(self, source):
        cursor = self.textCursor()

        if source.hasHtml():
            html = source.html()
            html = self._replace_image_sources_with_base64(html)
            cursor.insertHtml(html)
        elif source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage):
                html_img = self._image_to_base64_html(image)
                cursor.insertHtml(html_img)
        elif source.hasText():
            cursor.insertText(source.text())
        else:
            super().insertFromMimeData(source)

    def _replace_image_sources_with_base64(self, html):
        def repl(match):
            src = match.group(1)
            if src.startswith("file:///"):
                try:
                    path = src.replace("file:///", "")
                    with open(path, "rb") as f:
                        data = f.read()
                    base64_data = base64.b64encode(data).decode()
                    return f'src="data:image/png;base64,{base64_data}"'
                except Exception as e:
                    print("Ошибка при обработке изображения:", e)
            return f'src="{src}"'  # оставить как есть, если не удалось

        return re.sub(r'src="([^"]+)"', repl, html)

    def _image_to_base64_html(self, image):
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QBuffer.WriteOnly)
        image.save(buffer, "PNG")
        base64_data = base64.b64encode(buffer.data()).decode()
        return f'<img src="data:image/png;base64,{base64_data}" style="max-width:100%; width:300px; height:auto;" />'


# Реализация боковой панели со списков вопросов при прохождении теста
class QuestionGrid(QtWidgets.QFrame):
    def __init__(self, total_questions=12, cols=3):
        super().__init__()

        self.STATUS_COLORS = {
            "Выбран": "lightblue",  # временная подсветка, не сохраняем в status
            "Отвечен": "lightgreen",
            "Пропущен": "orange",
            "Не просмотрен": "white",
        }

        self.buttons = []
        self.status = []  # реальный статус каждой кнопки (без "Выбран")
        self.selected_index = None  # кто сейчас открыт

        # --- Оформление рамки ---
        self.setFrameShape(QtWidgets.QFrame.Box)
        self.setFrameShadow(QtWidgets.QFrame.Plain)
        self.setLineWidth(1)

        main_layout = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("Вопросы")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-weight: bold;")
        main_layout.addWidget(title)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        self.grid = QtWidgets.QGridLayout()
        self.grid.setSpacing(5)

        for i in range(total_questions):
            btn = QtWidgets.QPushButton(str(i + 1))
            btn.setFixedSize(40, 40)  # кнопки оставляем ВКЛЮЧЁННЫМИ
            self.buttons.append(btn)
            self.status.append("Не просмотрен")
            self.grid.addWidget(btn, i // cols, i % cols)
            self._apply_status_color(i)

        self.grid.setRowStretch((total_questions // cols) + 1, 1)
        main_layout.addLayout(self.grid)
        self.setLayout(main_layout)

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding
        )

    def _apply_status_color(self, index: int):
        """Красим кнопку: если выбран — синий, иначе по реальному статусу."""
        if index == self.selected_index:
            color = self.STATUS_COLORS["Выбран"]
        else:
            color = self.STATUS_COLORS.get(self.status[index], "white")
        self.buttons[index].setStyleSheet(
            f"background-color: {color}; border-radius: 5px;"
        )

    def set_button_status(self, index: int, status: str):
        """
        Универсальный метод для совместимости со старым кодом.
        - Если просят 'Выбран' — просто подсвечиваем (не меняем self.status).
        - Иначе меняем реальный статус и перекрашиваем.
        """
        if not (0 <= index < len(self.buttons)):
            return

        if status == "Выбран":
            # сначала снимем прошлый выбор (и, если надо, отметим как 'Пропущен')
            self.reset_selected()
            self.selected_index = index
            self._apply_status_color(index)
        else:
            self.status[index] = status
            self._apply_status_color(index)

    def reset_selected(self):
        """
        Снять синюю подсветку с текущего выбранного.
        Если уход с вопроса, который не 'Отвечен' — помечаем его как 'Пропущен'.
        """
        prev = self.selected_index
        if prev is not None:
            if self.status[prev] != "Отвечен":
                self.status[prev] = "Пропущен"
        self.selected_index = None

        # Перекрашиваем всё, чтобы цвета точно соответствовали статусам
        for i in range(len(self.buttons)):
            self._apply_status_color(i)


# Нижняя рамка с перемещением между вопросами
class NavigationOnQuestion(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        main_layout = QtWidgets.QHBoxLayout()

        # Кнопка ответить
        self.btn_reply_question = QtWidgets.QPushButton("Ответить на вопрос")
        main_layout.addWidget(self.btn_reply_question)

        # Кнопка предыдущий
        self.btn_next_question = QtWidgets.QPushButton("Следующий вопрос")
        main_layout.addWidget(self.btn_next_question)

        # Кнопка закончить тестирование
        self.btn_end_test = QtWidgets.QPushButton("Завершить тестирование")
        self.btn_end_test.setEnabled(False)
        main_layout.addWidget(self.btn_end_test)

        self.setLayout(main_layout)


class TestInfoDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, test_name=None, teacher_name=None):
        super().__init__(parent)
        self.setWindowTitle("Информация о тесте")
        self.resize(400, 200)

        layout = QtWidgets.QFormLayout(self)

        self.name_edit = QtWidgets.QLineEdit(test_name or "")
        self.teacher_edit = QtWidgets.QLineEdit(teacher_name or "")

        layout.addRow("Название теста:", self.name_edit)
        layout.addRow("Преподаватель:", self.teacher_edit)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addRow(buttons)

    def get_data(self):
        return self.name_edit.text().strip(), self.teacher_edit.text().strip()


class TagInfoDialog(QtWidgets.QDialog):
    def __init__(self, unique_tag, parent=None, existing_tags=None):
        super().__init__(parent)
        self.setWindowTitle("Количество вопросов по тегам")
        self.resize(400, 300)

        self.unique_tag = unique_tag
        self.existing_tags = existing_tags or {}  # Существующие теги из БД

        layout = QtWidgets.QVBoxLayout(self)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_widget)

        self.tag_widgets = {}

        # Объединяем теги из текущей сессии и существующие из БД
        all_tags = set(unique_tag.keys()) | set(
            existing_tags.keys() if existing_tags else []
        )

        for tag_name in sorted(all_tags):
            tag_layout = QtWidgets.QHBoxLayout()

            tag_label = QtWidgets.QLabel(tag_name)
            tag_label.setFixedWidth(150)

            count_spin = QtWidgets.QSpinBox()
            count_spin.setMinimum(1)
            count_spin.setMaximum(100)

            # Устанавливаем значение: сначала из текущей сессии, потом из существующих
            if tag_name in unique_tag:
                count_spin.setValue(unique_tag[tag_name])
            elif existing_tags and tag_name in existing_tags:
                count_spin.setValue(existing_tags[tag_name])
            else:
                count_spin.setValue(1)

            tag_layout.addWidget(tag_label)
            tag_layout.addWidget(count_spin)
            tag_layout.addStretch()

            self.scroll_layout.addLayout(tag_layout)
            self.tag_widgets[tag_name] = count_spin

        self.scroll_area.setWidget(self.scroll_widget)
        layout.addWidget(
            QtWidgets.QLabel("Укажите количество вопросов для каждого тега:")
        )
        layout.addWidget(self.scroll_area)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def get_data(self):
        return {tag: spin.value() for tag, spin in self.tag_widgets.items()}


class LoginWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Авторизация")
        self.resize(250, 100)

        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # Заголовок
        title = QtWidgets.QLabel("Центр тестирования")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 18pt; font-weight: bold;")
        layout.addWidget(title)

        # Статус
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: red;")
        layout.addWidget(self.status_label)

        # Поля ввода
        form_layout = QtWidgets.QFormLayout()

        self.login_edit = QtWidgets.QLineEdit()
        self.login_edit.setPlaceholderText("Введите логин")

        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setPlaceholderText("Введите пароль")
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)

        form_layout.addRow("Логин:", self.login_edit)
        form_layout.addRow("Пароль:", self.password_edit)

        layout.addLayout(form_layout)

        # Кнопка входа
        self.login_btn = QtWidgets.QPushButton("Войти")
        self.login_btn.clicked.connect(self.authenticate)
        layout.addWidget(self.login_btn)

        self.setLayout(layout)

    def create_default_teacher(self):
        """Создает учителя по умолчанию если его нет"""
        with session_sync_factory() as session:
            existing_teacher = session.scalar(
                select(TeachersOrm).where(TeachersOrm.login == "teacher_admin")
            )
            if not existing_teacher:
                teacher = TeachersOrm(
                    login="teacher_admin",
                    password="123",  # В реальном приложении нужно хэшировать!
                )
                session.add(teacher)
                session.commit()

    def authenticate(self):
        login = self.login_edit.text().strip()
        password = self.password_edit.text().strip()

        if not login or not password:
            self.show_status("Введите логин и пароль")
            return

        with session_sync_factory() as session:
            # Проверяем учителя
            teacher = session.scalar(
                select(TeachersOrm).where(TeachersOrm.login == login)
            )
            if teacher and teacher.password == password:
                self.open_start_window(is_teacher=True)
                return

            # Проверяем студента
            student = session.scalar(
                select(StudentsOrm).where(StudentsOrm.login == login)
            )
            if student and student.password == password:
                self.open_start_window(is_teacher=False, student_id=student.id)
                return

        self.show_status("Неверный логин или пароль")

    def show_status(self, message):
        self.status_label.setText(message)
        QTimer.singleShot(3000, lambda: self.status_label.setText(""))

    def open_start_window(self, is_teacher=False, student_id=None):
        self.start_window = StartWindow(
            is_teacher=is_teacher, student_id=student_id
        )
        self.start_window.show()
        self.close()


# Стартовое окно
class StartWindow(QtWidgets.QWidget):
    def __init__(self, is_teacher=False, student_id=None, parent=None):
        super().__init__(parent)
        self.is_teacher = is_teacher
        self.student_id = student_id

        self.setWindowTitle("Центр тестирования")
        self.resize(800, 600)
        self.setMinimumSize(600, 400)

        self.init_ui()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(30)

        # Заголовок с информацией о пользователе
        user_type = "Преподаватель" if self.is_teacher else "Студент"
        self.label = QtWidgets.QLabel(f"Добро пожаловать, {user_type}!")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        main_layout.addWidget(self.label)

        # Список тестов
        self.test_list = QtWidgets.QListWidget()
        self.test_list.itemDoubleClicked.connect(self.confirm_test_selection)
        main_layout.addWidget(QtWidgets.QLabel("Доступные тесты:"))
        main_layout.addWidget(self.test_list)

        # Кнопки для преподавателя
        if self.is_teacher:
            teacher_layout = QtWidgets.QHBoxLayout()

            self.btn_create_test = QtWidgets.QPushButton("Создать новый тест")
            self.btn_create_test.clicked.connect(self.open_create_test_window)

            self.btn_edit_test = QtWidgets.QPushButton("Редактировать тест")
            self.btn_edit_test.clicked.connect(self.open_edit_test_window)

            self.btn_manage_students = QtWidgets.QPushButton(
                "Управление студентами"
            )
            self.btn_manage_students.clicked.connect(
                self.open_student_management
            )

            teacher_layout.addWidget(self.btn_create_test)
            teacher_layout.addWidget(self.btn_edit_test)
            teacher_layout.addWidget(self.btn_manage_students)

            main_layout.addLayout(teacher_layout)

        # Кнопка выхода
        self.btn_logout = QtWidgets.QPushButton("Выйти")
        self.btn_logout.clicked.connect(self.logout)
        main_layout.addWidget(self.btn_logout)

        self.load_tests()

    def open_student_management(self):
        """Открывает окно управления студентами"""
        self.student_window = StudentManagementWindow()
        self.student_window.show()
        self.close()

    def logout(self):
        """Возврат к окну авторизации"""
        self.login_window = LoginWindow()
        self.login_window.show()
        self.close()

    def load_tests(self):
        self.test_list.clear()
        self.test_items = {}

        with session_sync_factory() as session:
            tests = session.scalars(select(TestsOrm)).all()
            for test in tests:
                item = QtWidgets.QListWidgetItem(
                    f"{test.name_test} — {test.teacher}"
                )
                item.setData(QtCore.Qt.UserRole, test.id)
                self.test_list.addItem(item)

    def confirm_test_selection(self, item):
        test_id = item.data(QtCore.Qt.UserRole)
        test_name = item.text()

        reply = QtWidgets.QMessageBox.question(
            self,
            "Подтверждение",
            f"Вы действительно хотите начать тест:\n«{test_name}»?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.open_test_window(test_id, test_name)

    def open_test_window(self, test_id, test_name):
        self.qeustion_window = QuestionWindow(
            id_test=test_id, test_name=test_name, start_window=self
        )
        self.qeustion_window.show()
        self.close()

    def open_create_test_window(self):
        self.qeustion_window = QuestionEditor()
        self.qeustion_window.show()
        self.close()

    def open_edit_test_window(self):
        # Диалог выбора теста для редактирования
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Выбор теста для редактирования")
        dialog.setModal(True)
        dialog.resize(500, 400)

        layout = QtWidgets.QVBoxLayout(dialog)

        # Список тестов
        test_list = QtWidgets.QListWidget()
        layout.addWidget(QtWidgets.QLabel("Выберите тест для редактирования:"))
        layout.addWidget(test_list)

        # Кнопки
        button_layout = QtWidgets.QHBoxLayout()
        select_btn = QtWidgets.QPushButton("Выбрать")
        cancel_btn = QtWidgets.QPushButton("Отмена")
        button_layout.addWidget(select_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        # Загрузка тестов
        with session_sync_factory() as session:
            tests = session.scalars(select(TestsOrm)).all()
            for test in tests:
                item = QtWidgets.QListWidgetItem(
                    f"{test.name_test} — {test.teacher}"
                )
                item.setData(QtCore.Qt.UserRole, test.id)
                test_list.addItem(item)

        def on_select():
            selected_item = test_list.currentItem()
            if selected_item:
                test_id = selected_item.data(QtCore.Qt.UserRole)
                test_name = selected_item.text()
                dialog.accept()

                # Открываем редактор с загруженным тестом
                self.open_question_editor_with_test(test_id, test_name)

        def on_cancel():
            dialog.reject()

        select_btn.clicked.connect(on_select)
        cancel_btn.clicked.connect(on_cancel)
        test_list.itemDoubleClicked.connect(on_select)

        dialog.exec_()

    def open_question_editor_with_test(self, test_id, test_name):
        self.question_window = QuestionEditor(
            test_id=test_id, test_name=test_name
        )
        self.question_window.show()
        self.close()


class StudentManagementWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Управление студентами")
        self.resize(800, 600)

        self.init_ui()
        self.load_groups()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # Заголовок
        title = QtWidgets.QLabel("Управление студентами")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        # Импорт из Excel
        import_layout = QtWidgets.QHBoxLayout()
        self.import_btn = QtWidgets.QPushButton("Импорт из Excel")
        self.import_btn.clicked.connect(self.import_from_excel)
        import_layout.addWidget(self.import_btn)
        import_layout.addStretch()
        layout.addLayout(import_layout)

        # Экспорт логинов/паролей
        export_layout = QtWidgets.QHBoxLayout()
        self.export_btn = QtWidgets.QPushButton("Экспорт логинов/паролей")
        self.export_btn.clicked.connect(self.export_credentials)
        export_layout.addWidget(self.export_btn)

        self.export_group_selector = QtWidgets.QComboBox()
        self.export_group_selector.currentIndexChanged.connect(
            self.preview_group_students
        )
        export_layout.addWidget(QtWidgets.QLabel("Группа:"))
        export_layout.addWidget(self.export_group_selector)

        export_layout.addStretch()
        layout.addLayout(export_layout)

        # Таблица студентов (универсальная)
        self.students_table = QtWidgets.QTableWidget()
        self.students_table.setColumnCount(4)
        self.students_table.setHorizontalHeaderLabels(
            ["Логин", "Пароль", "ФИО", "Группа"]
        )
        layout.addWidget(self.students_table)

        # Кнопка возврата
        self.back_btn = QtWidgets.QPushButton("Назад")
        self.back_btn.clicked.connect(self.go_back)
        layout.addWidget(self.back_btn)

        self.setLayout(layout)

    def load_groups(self):
        """Загрузка списка групп"""
        self.export_group_selector.clear()

        with session_sync_factory() as session:
            groups = session.scalars(select(GroupsOrm)).all()
            for group in groups:
                self.export_group_selector.addItem(group.name, group.id)

    def generate_credentials(self):
        """Генерация логина и пароля из 8 случайных символов"""
        chars = string.ascii_letters + string.digits
        login = ''.join(secrets.choice(chars) for _ in range(8))
        password = ''.join(secrets.choice(chars) for _ in range(8))
        return login, password

    def import_from_excel(self):
        """Импорт студентов из Excel файла (с определением группы из файла)"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл Excel", "", "Excel Files (*.xlsx *.xls)"
        )

        if not file_path:
            return

        try:
            df = pd.read_excel(file_path)
            required_columns = ['ФИО', 'Группа']

            if not all(col in df.columns for col in required_columns):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Файл должен содержать колонки: {', '.join(required_columns)}",
                )
                return

            added_students = []  # для предпросмотра
            last_group_name = None

            with session_sync_factory() as session:
                for _, row in df.iterrows():
                    full_name = str(row['ФИО']).strip()
                    group_name = str(row['Группа']).strip()

                    if not full_name or not group_name:
                        continue

                    last_group_name = group_name  # запомним последнюю группу

                    # Находим или создаем группу
                    group = session.scalar(
                        select(GroupsOrm).where(GroupsOrm.name == group_name)
                    )
                    if not group:
                        group = GroupsOrm(name=group_name)
                        session.add(group)
                        session.flush()

                    # Генерируем уникальный логин
                    while True:
                        login, password = self.generate_credentials()
                        existing = session.scalar(
                            select(StudentsOrm).where(
                                StudentsOrm.login == login
                            )
                        )
                        if not existing:
                            break

                    student = StudentsOrm(
                        login=login,
                        password=password,
                        full_name=full_name,
                        group_id=group.id,
                    )
                    session.add(student)
                    added_students.append(
                        {
                            "login": login,
                            "password": password,
                            "full_name": full_name,
                            "group_name": group.name,
                        }
                    )

                session.commit()

            # Обновляем список групп
            self.load_groups()

            # Если мы знаем последнюю группу из импорта → выбираем её в ComboBox
            if last_group_name:
                index = self.export_group_selector.findText(last_group_name)
                if index != -1:
                    self.export_group_selector.setCurrentIndex(index)
                    # Сразу вызываем предпросмотр
                    self.preview_group_students()

            # Предпросмотр только добавленных
            self.show_students_in_table(added_students, from_preview=True)

            QtWidgets.QMessageBox.information(
                self, "Успех", f"Добавлено {len(added_students)} студентов"
            )

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Ошибка", f"Ошибка импорта: {str(e)}"
            )

    def export_credentials(self):
        """Экспорт логинов и паролей в Excel"""
        group_id = self.export_group_selector.currentData()
        if not group_id:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Выберите группу")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить как",
            f"логины_пароли_{self.export_group_selector.currentText()}.xlsx",
            "Excel Files (*.xlsx)",
        )

        if not file_path:
            return

        try:
            with session_sync_factory() as session:
                # ИСПРАВЛЕНИЕ: добавляем фильтр по группе
                students = session.scalars(
                    select(StudentsOrm)
                    .where(
                        StudentsOrm.group_id == group_id
                    )  # Фильтруем по выбранной группе
                    .options(selectinload(StudentsOrm.group))
                ).all()

                if not students:
                    QtWidgets.QMessageBox.warning(
                        self, "Ошибка", "В выбранной группе нет студентов"
                    )
                    return

                # Создаем Excel файл
                wb = Workbook()
                ws = wb.active
                ws.title = "Логины и пароли"

                # Заголовки
                ws.append(['Логин', 'Пароль', 'ФИО', 'Группа'])

                # Данные
                for student in students:
                    ws.append(
                        [
                            student.login,
                            student.password,
                            student.full_name,
                            student.group.name,
                        ]
                    )

                wb.save(file_path)
                QtWidgets.QMessageBox.information(
                    self, "Успех", f"Данные экспортированы в {file_path}"
                )

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Ошибка", f"Ошибка экспорта: {str(e)}"
            )

    def preview_group_students(self):
        """Предпросмотр студентов выбранной группы в таблице"""
        group_id = self.export_group_selector.currentData()
        if not group_id:
            return

        try:
            with session_sync_factory() as session:
                students = session.scalars(
                    select(StudentsOrm)
                    .where(StudentsOrm.group_id == group_id)
                    .options(selectinload(StudentsOrm.group))
                ).all()

                students_data = []
                for student in students:
                    students_data.append(
                        {
                            "login": student.login,
                            "password": student.password,
                            "full_name": student.full_name,
                            "group_name": student.group.name,
                        }
                    )

                self.show_students_in_table(students_data, from_preview=True)

        except Exception as e:
            print(f"Ошибка загрузки студентов: {e}")

    def show_students_in_table(self, students_data, from_preview=False):
        """Отображение студентов в таблице"""
        self.students_table.setRowCount(len(students_data))

        for row, student in enumerate(students_data):
            self.students_table.setItem(
                row, 0, QtWidgets.QTableWidgetItem(student["login"])
            )
            self.students_table.setItem(
                row, 1, QtWidgets.QTableWidgetItem(student["password"])
            )
            self.students_table.setItem(
                row, 2, QtWidgets.QTableWidgetItem(student["full_name"])
            )
            self.students_table.setItem(
                row, 3, QtWidgets.QTableWidgetItem(student["group_name"])
            )

        # Автоподбор ширины колонок
        self.students_table.resizeColumnsToContents()

    def go_back(self):
        """Возврат в главное меню"""
        self.start_window = StartWindow(is_teacher=True)
        self.start_window.show()
        self.close()


class QuestionEditorWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.font_for_answer = QFont()
        self.font_for_answer.setPointSize(14)

        self.layout = QtWidgets.QVBoxLayout(self)

        # Ввод текста вопроса
        self.question_text = CustomTextEdit()
        self.question_text.setPlaceholderText("Введите текст вопроса...")
        self.question_text.setFixedHeight(500)
        self.layout.addWidget(self.question_text)

        # Выбор типа вопроса
        self.type_selector = QtWidgets.QComboBox()
        self.type_selector.addItems(
            [
                "Ввод строки",
                "Выбор правильн(ого/ых) ответов",
                "Упорядочивание",
            ]
        )
        self.type_selector.currentIndexChanged.connect(
            self.change_answer_widget
        )

        create_answer_for_question = QtWidgets.QHBoxLayout()
        create_answer_for_question.addWidget(
            QtWidgets.QLabel("Введите ответ:")
        )
        create_answer_for_question.addStretch()
        create_answer_for_question.addWidget(QtWidgets.QLabel("Тип вопроса: "))
        create_answer_for_question.addWidget(self.type_selector)
        self.layout.addLayout(create_answer_for_question)

        # Контейнер для ответа
        self.answer_widget_container = QtWidgets.QStackedWidget()
        self.layout.addWidget(self.answer_widget_container)

        self.init_answer_widgets()

    def init_answer_widgets(self):
        # Ввод строки
        self.input_string_widget = QtWidgets.QLineEdit()
        self.input_string_widget.setFixedHeight(30)
        self.input_string_widget.setFont(self.font_for_answer)
        self.answer_widget_container.addWidget(self.input_string_widget)

        # Несколько правильных ответов (Checkboxes)
        self.multiple_choice_widget = self._create_choices_widget()
        self.answer_widget_container.addWidget(self.multiple_choice_widget)

        # Упорядочивание
        self.ordering_widget = self._create_ordering_widget()
        self.answer_widget_container.addWidget(self.ordering_widget)
        self.answer_widget_container.setCurrentIndex(0)

    # Виджет для создания ответа с выбор(ом/ами)
    def _create_choices_widget(self):
        widget = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(widget)

        self.right_answer_layout = QtWidgets.QVBoxLayout()
        self.right_answer_layout.addWidget(
            QtWidgets.QLabel("Правильные ответы: ")
        )

        first_right = QtWidgets.QLineEdit()
        first_right.setFont(self.font_for_answer)
        self.right_answer_layout.addWidget(first_right)

        self.btn_add_right = QtWidgets.QPushButton(
            "Добавить правильный вариант ответа"
        )
        self.btn_delete_right = QtWidgets.QPushButton(
            "Удалить правильный вариант ответа"
        )
        self.right_answer_layout.addWidget(self.btn_add_right)
        self.right_answer_layout.addWidget(self.btn_delete_right)
        self.right_answer_layout.addStretch()

        self.btn_add_right.clicked.connect(
            lambda: self._add_line_edit_with_font(self.right_answer_layout)
        )
        self.btn_delete_right.clicked.connect(
            lambda: self._delete_line_edit(self.right_answer_layout)
        )

        self.wrong_answer_layout = QtWidgets.QVBoxLayout()
        self.wrong_answer_layout.addWidget(
            QtWidgets.QLabel("Неправильные ответы: ")
        )

        self.btn_add_wrong = QtWidgets.QPushButton(
            "Добавить неправильный вариант ответа"
        )
        self.btn_delete_wrong = QtWidgets.QPushButton(
            "Удалить неправильный вариант ответа"
        )
        self.wrong_answer_layout.addWidget(self.btn_add_wrong)
        self.wrong_answer_layout.addWidget(self.btn_delete_wrong)
        self.wrong_answer_layout.addStretch()

        self.btn_add_wrong.clicked.connect(
            lambda: self._add_line_edit_with_font(self.wrong_answer_layout)
        )
        self.btn_delete_wrong.clicked.connect(
            lambda: self._delete_line_edit(self.wrong_answer_layout)
        )

        main_layout.addLayout(self.right_answer_layout)
        main_layout.addLayout(self.wrong_answer_layout)

        return widget

    # Реализация добавления полей для ввода в layout
    def _add_line_edit_with_font(self, layout, text=None):
        line_edit = QtWidgets.QLineEdit(text)
        line_edit.setFont(self.font_for_answer)
        layout.insertWidget(layout.count() - 3, line_edit)
        self._update_delete_buttons()

    # Реализация удаления полей для ввода в layout
    def _delete_line_edit(self, layout):
        count = layout.count()
        for i in range(count - 4, 0, -1):  # Пропускаем label и кнопки
            item = layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, QtWidgets.QLineEdit):
                layout.takeAt(i)
                widget.deleteLater()
                break
        self._update_delete_buttons()

    def _update_delete_buttons(self):

        # Проверка для активности кнопки удаления в выборе ответов(index==1)
        if self.type_selector.currentIndex() == 1:
            # Проверяем количество QLineEdit в неправильных ответах layout
            wrong_count = sum(
                isinstance(
                    self.wrong_answer_layout.itemAt(i).widget(),
                    QtWidgets.QLineEdit,
                )
                for i in range(self.wrong_answer_layout.count())
            )
            self.btn_delete_wrong.setEnabled(wrong_count > 0)

            # Проверяем количество QLineEdit в правильных ответах layout
            right_count = sum(
                isinstance(
                    self.right_answer_layout.itemAt(i).widget(),
                    QtWidgets.QLineEdit,
                )
                for i in range(self.right_answer_layout.count())
            )
            self.btn_delete_right.setEnabled(right_count > 1)

        # Проверка для активности кнопки удаления в упорядочивание(index==2)
        if self.type_selector.currentIndex() == 2:
            # Проверяем количество QLineEdit в правильных ответах layout
            main_count = sum(
                isinstance(
                    self.main_layout.itemAt(i).widget(),
                    QtWidgets.QLineEdit,
                )
                for i in range(self.main_layout.count())
            )
            self.btn_delete_line_answer.setEnabled(main_count > 2)

    # Виджет для создания ответа с упорядочиванием
    def _create_ordering_widget(self):
        widget = QtWidgets.QWidget()
        self.main_layout = QtWidgets.QVBoxLayout(widget)

        self.main_layout.addWidget(
            QtWidgets.QLabel("Введите ответ в правильном порядке: ")
        )

        first_line_answer = QtWidgets.QLineEdit()
        first_line_answer.setFont(self.font_for_answer)
        self.main_layout.addWidget(first_line_answer)
        second_line_answer = QtWidgets.QLineEdit()
        second_line_answer.setFont(self.font_for_answer)
        self.main_layout.addWidget(second_line_answer)

        self.btn_add_line_answer = QtWidgets.QPushButton(
            "Добавить правильный вариант ответа"
        )
        self.btn_delete_line_answer = QtWidgets.QPushButton(
            "Удалить правильный вариант ответа"
        )
        self.main_layout.addWidget(self.btn_add_line_answer)
        self.main_layout.addWidget(self.btn_delete_line_answer)
        self.main_layout.addStretch()

        self.btn_add_line_answer.clicked.connect(
            lambda: self._add_line_edit_with_font(self.main_layout)
        )
        self.btn_delete_line_answer.clicked.connect(
            lambda: self._delete_line_edit(self.main_layout)
        )

        return widget

    def change_answer_widget(self, index):
        self.answer_widget_container.setCurrentIndex(index)
        # Деактивация кнопок удаления при создания первоначального шаблона вопроса
        self._update_delete_buttons()


class QuestionEditor(QtWidgets.QWidget):
    def __init__(self, test_id=None, test_name=None):
        super().__init__()

        self.test_id = test_id  # ID редактируемого теста
        self.test_name = test_name  # Название редактируемого теста

        if test_id:
            self.setWindowTitle(f"Редактирование теста: {test_name}")
        else:
            self.setWindowTitle("Создание теста")

        self.questions = []  # Список временных вопросов
        self.current_edit_index = None
        self.flag_change_question = False
        self.current_load_tag = None
        self.unique_tag = {"Без тэга": 0}

        self.answer_on_question = QuestionEditorWidget()
        self.tag_for_question = QtWidgets.QLineEdit()
        self.tag_for_question.setMaxLength(20)
        self.tag_for_question.setFixedWidth(150)
        self.size_box = QtWidgets.QComboBox()
        self.size_box.addItems([str(size) for size in range(8, 30, 2)])
        self.size_box.currentIndexChanged.connect(self.set_font_size)

        self.bold_btn = QtWidgets.QPushButton("Жирный")
        self.bold_btn.setCheckable(True)
        self.bold_btn.clicked.connect(self.set_bold)

        self.italic_btn = QtWidgets.QPushButton("Курсив")
        self.italic_btn.setCheckable(True)
        self.italic_btn.clicked.connect(self.set_italic)

        self.underline_btn = QtWidgets.QPushButton("Подчеркнуть")
        self.underline_btn.setCheckable(True)
        self.underline_btn.clicked.connect(self.set_underline)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(self.size_box)
        toolbar.addWidget(self.bold_btn)
        toolbar.addWidget(self.italic_btn)
        toolbar.addWidget(self.underline_btn)

        tag_layout = QtWidgets.QHBoxLayout()
        tag_layout.addStretch()
        tag_layout.addWidget(QtWidgets.QLabel("Тег:"))
        tag_layout.addWidget(self.tag_for_question)

        title_label = QtWidgets.QLabel("Введите текст вопроса:")
        title_question = QtWidgets.QHBoxLayout()
        title_question.addWidget(title_label)
        title_question.addLayout(tag_layout)

        layout_render_text = QtWidgets.QHBoxLayout()
        self.load_image_btn = QtWidgets.QPushButton("Загрузить изображение")
        self.insert_table_btn = QtWidgets.QPushButton("Вставить таблицу")
        layout_render_text.addWidget(self.load_image_btn)
        layout_render_text.addWidget(self.insert_table_btn)

        self.add_question_btn = QtWidgets.QPushButton(
            "Добавить/Обновить вопрос"
        )

        # Список вопросов
        self.question_list = QtWidgets.QListWidget()
        self.question_list.setFixedWidth(240)
        self.save_test_btn = QtWidgets.QPushButton("Сохранить тест")
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(QtWidgets.QLabel("Список вопросов: "))
        right_layout.addWidget(self.question_list)
        right_layout.addWidget(self.save_test_btn)
        self.question_list.itemClicked.connect(self.load_selected_question)

        left_layout = QtWidgets.QVBoxLayout()
        left_layout.addLayout(toolbar)
        left_layout.addLayout(title_question)
        left_layout.addWidget(self.answer_on_question)
        left_layout.addLayout(layout_render_text)
        left_layout.addWidget(self.add_question_btn)

        main_layout = QtWidgets.QHBoxLayout()
        main_layout.addLayout(left_layout)
        main_layout.addLayout(right_layout)

        self.setLayout(main_layout)

        self.load_image_btn.clicked.connect(self.insert_image)
        self.insert_table_btn.clicked.connect(self.insert_table)
        self.add_question_btn.clicked.connect(self.save_question_temp)
        self.save_test_btn.clicked.connect(self.save_all_questions)

        if test_id:
            self.load_existing_test()

    @QtCore.pyqtSlot()
    def insert_table(self):
        rows, ok1 = QtWidgets.QInputDialog.getInt(
            self, 'Строки таблицы', 'Введите количество строк:', 2, 1, 10
        )
        if not ok1:
            return
        cols, ok2 = QtWidgets.QInputDialog.getInt(
            self, 'Столбцы таблицы', 'Введите количество столбцов:', 2, 1, 10
        )
        if not ok2:
            return

        cursor = self.answer_on_question.question_text.textCursor()
        cursor.insertTable(rows, cols, fmt)

    @QtCore.pyqtSlot()
    def insert_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать изображение",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if path:
            image = QImage(path)
            if image.isNull():
                return
        cursor = self.answer_on_question.question_text.textCursor()
        html_img = self.answer_on_question.question_text._image_to_base64_html(
            image
        )
        cursor.insertHtml(html_img)

    # Сохранение шаблона вопроса в память
    @QtCore.pyqtSlot()
    def save_question_temp(self):
        html = self.answer_on_question.question_text.toHtml()
        type_answer = self.answer_on_question.type_selector.currentText()
        answer = None

        if type_answer == "Ввод строки":
            answer = self.answer_on_question.input_string_widget.text()

        elif type_answer == "Выбор правильн(ого/ых) ответов":
            answer = [[], []]
            for i in range(
                1, self.answer_on_question.right_answer_layout.count() - 3
            ):
                widget = self.answer_on_question.right_answer_layout.itemAt(
                    i
                ).widget()
                if isinstance(widget, QtWidgets.QLineEdit):
                    answer[0].append(widget.text())

            for i in range(
                1, self.answer_on_question.wrong_answer_layout.count() - 3
            ):
                widget = self.answer_on_question.wrong_answer_layout.itemAt(
                    i
                ).widget()
                if isinstance(widget, QtWidgets.QLineEdit):
                    answer[1].append(widget.text())

        elif type_answer == "Упорядочивание":
            answer = []
            for i in range(1, self.answer_on_question.main_layout.count() - 3):
                widget = self.answer_on_question.main_layout.itemAt(i).widget()
                if isinstance(widget, QtWidgets.QLineEdit):
                    answer.append(widget.text())

        # --- работа с тэгами ---
        new_tag = self.tag_for_question.text().strip()
        if not new_tag:  # Если поле тега пустое
            new_tag = None  # Сохраняем как None, а не "Без тэга"

        tag_display = new_tag or "Без тэга"  # Для отображения

        # если редактируем существующий вопрос
        if self.current_edit_index is not None:
            _, _, _, old_tag = self.questions[self.current_edit_index]
            old_tag_display = old_tag or "Без тэга"  # Для отображения

            # Если тег изменился, обновляем счетчики
            if old_tag_display != tag_display:
                # Уменьшаем счетчик старого тега
                if old_tag_display in self.unique_tag:
                    self.unique_tag[old_tag_display] -= 1
                    if self.unique_tag[old_tag_display] <= 0:
                        del self.unique_tag[old_tag_display]

                # Увеличиваем счетчик нового тега
                self.unique_tag[tag_display] = (
                    self.unique_tag.get(tag_display, 0) + 1
                )
        else:
            # Увеличиваем счетчик нового тега для нового вопроса
            self.unique_tag[tag_display] = (
                self.unique_tag.get(tag_display, 0) + 1
            )

        item_text = (
            f"{tag_display} — {html[:50]}..."  # Обрезаем HTML для отображения
        )

        if self.current_edit_index is not None:
            self.questions[self.current_edit_index] = (
                html,
                type_answer,
                answer,
                new_tag,  # Сохраняем как None если пусто
            )
            self.question_list.item(self.current_edit_index).setText(item_text)
            self.current_edit_index = None
        else:
            self.questions.append((html, type_answer, answer, new_tag))
            self.question_list.addItem(item_text)

        self.current_load_tag = None
        self.clear_question_fields()

    # Загрузка из памяти сохраненного вопроса
    def load_selected_question(self, item):
        self.clear_question_fields()

        index = self.question_list.row(item)
        html, type_answer, answer, tag = self.questions[index]

        self.answer_on_question.question_text.setHtml(html)

        if type_answer == "Ввод строки":
            self.answer_on_question.type_selector.setCurrentIndex(0)
            self.answer_on_question.input_string_widget.setText(answer)

        elif type_answer == "Выбор правильн(ого/ых) ответов":
            self.answer_on_question.type_selector.setCurrentIndex(1)
            for i in range(len(answer[0])):
                if i == 0:
                    self.answer_on_question.right_answer_layout.itemAt(
                        1
                    ).widget().setText(answer[0][0])
                    continue
                self.answer_on_question._add_line_edit_with_font(
                    self.answer_on_question.right_answer_layout, answer[0][i]
                )
            for i in range(len(answer[1])):
                self.answer_on_question._add_line_edit_with_font(
                    self.answer_on_question.wrong_answer_layout, answer[1][i]
                )

        elif type_answer == "Упорядочивание":
            self.answer_on_question.type_selector.setCurrentIndex(2)
            for i in range(len(answer)):
                if i in (0, 1):
                    self.answer_on_question.main_layout.itemAt(
                        i + 1
                    ).widget().setText(answer[i])
                    continue
                self.answer_on_question._add_line_edit_with_font(
                    self.answer_on_question.main_layout, answer[i]
                )

        self.flag_change_question = True
        # Устанавливаем текст тега (пустую строку если None)
        self.tag_for_question.setText(tag if tag else "")
        self.current_edit_index = index

    # Сохранение всех вопросов
    @QtCore.pyqtSlot()
    def save_all_questions(self):
        # --- Ввод информации о тесте ---
        if self.test_id:  # Если редактируем существующий тест
            with session_sync_factory() as session:
                test = session.get(TestsOrm, self.test_id)
                test_dialog = TestInfoDialog(
                    self, test.name_test, test.teacher
                )
        else:  # Если создаем новый тест
            test_dialog = TestInfoDialog(self)

        if test_dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        name_test, teacher_name = test_dialog.get_data()
        if not name_test or not teacher_name:
            QtWidgets.QMessageBox.warning(
                self,
                "Ошибка",
                "Название теста, имя преподавателя обязательны.",
            )
            return

        # --- Сначала ввод количества тегов ---
        # Используем актуальные счетчики из unique_tag
        tag_dialog = TagInfoDialog(self.unique_tag, self)
        if tag_dialog.exec_() == QtWidgets.QDialog.Accepted:
            tag_counts = tag_dialog.get_data()  # {tag_name: count}
        else:
            return

        with session_sync_factory() as session:
            # Проверяем, существует ли уже тест с таким названием (только для нового теста)
            if not self.test_id:
                existing_test = session.scalar(
                    select(TestsOrm).where(TestsOrm.name_test == name_test)
                )
                if existing_test:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Ошибка",
                        f"Тест с названием '{name_test}' уже существует. Пожалуйста, выберите другое название.",
                    )
                    return

            # Если редактируем существующий тест, сначала удаляем старые данные
            if self.test_id:
                # Удаляем старые вопросы и связанные данные
                session.execute(
                    delete(QuestionsInputStringOrm).where(
                        QuestionsInputStringOrm.test_id == self.test_id
                    )
                )
                session.execute(
                    delete(QuestionsCheckBoxOrm).where(
                        QuestionsCheckBoxOrm.test_id == self.test_id
                    )
                )
                session.execute(
                    delete(QuestionsReplacementOrm).where(
                        QuestionsReplacementOrm.test_id == self.test_id
                    )
                )

                # Удаляем старые теги
                session.execute(
                    delete(TagsOrm).where(TagsOrm.test_id == self.test_id)
                )

                # Обновляем информацию о тесте
                test = session.get(TestsOrm, self.test_id)
                test.name_test = name_test
                test.teacher = teacher_name
                session.flush()
                test_id = self.test_id
            else:
                # Создаем новый тест
                new_test = TestsOrm(name_test=name_test, teacher=teacher_name)
                session.add(new_test)
                session.flush()  # Чтобы получить id теста
                test_id = new_test.id

            # --- Сохраняем теги ---
            tags_map = {}  # {tag_name: TagsOrm}
            for tag_name, count in tag_counts.items():
                tag_obj = TagsOrm(
                    name=tag_name,
                    count=count,
                    test_id=test_id,
                )
                session.add(tag_obj)
                tags_map[tag_name] = tag_obj
            session.flush()  # Получаем id тегов

            # --- Сохраняем вопросы ---
            for q_html, q_type, q_answer, q_tag in self.questions:
                tag_name = q_tag or "Без тэга"
                tag_obj = tags_map.get(tag_name)

                if q_type == "Ввод строки":
                    question = QuestionsInputStringOrm(
                        test_id=test_id,
                        question=q_html,
                        answers=q_answer,
                        tag_id=tag_obj.id if tag_obj else None,
                    )
                    session.add(question)

                elif q_type == "Выбор правильн(ого/ых) ответов":
                    question = QuestionsCheckBoxOrm(
                        test_id=test_id,
                        question=q_html,
                        tag_id=tag_obj.id if tag_obj else None,
                    )
                    session.add(question)
                    session.flush()  # Получаем id вопроса

                    # создаем ответы
                    answers = [
                        AnswersCheckBoxOrm(
                            text=text, is_correct=True, question_id=question.id
                        )
                        for text in q_answer[0]
                    ] + [
                        AnswersCheckBoxOrm(
                            text=text,
                            is_correct=False,
                            question_id=question.id,
                        )
                        for text in q_answer[1]
                    ]
                    session.add_all(answers)

                elif q_type == "Упорядочивание":
                    question = QuestionsReplacementOrm(
                        test_id=test_id,
                        question=q_html,
                        tag_id=tag_obj.id if tag_obj else None,
                    )
                    session.add(question)
                    session.flush()  # Получаем id вопроса

                    answers = [
                        AnswersReplacementOrm(
                            text=q_answer[i],
                            number_in_answer=i + 1,
                            question_id=question.id,
                        )
                        for i in range(len(q_answer))
                    ]
                    session.add_all(answers)

            session.commit()

        QtWidgets.QMessageBox.information(
            self,
            "Успех",
            f"Тест '{name_test}' успешно {'сохранен' if self.test_id else 'создан'}!",
        )
        self.comeback_startmenu()

    # Загрузка существущего теста
    def load_existing_test(self):
        """Загрузка вопросов существующего теста"""
        with session_sync_factory() as session:
            # Загрузка вопросов разных типов
            input_string_questions = session.scalars(
                select(QuestionsInputStringOrm).where(
                    QuestionsInputStringOrm.test_id == self.test_id
                )
            ).all()

            checkbox_questions = session.scalars(
                select(QuestionsCheckBoxOrm).where(
                    QuestionsCheckBoxOrm.test_id == self.test_id
                )
            ).all()

            replacement_questions = session.scalars(
                select(QuestionsReplacementOrm).where(
                    QuestionsReplacementOrm.test_id == self.test_id
                )
            ).all()

            # Загрузка всех тегов для этого теста
            tags = session.scalars(
                select(TagsOrm).where(TagsOrm.test_id == self.test_id)
            ).all()
            tags_dict = {tag.id: tag for tag in tags}  # Словарь тегов по id

            # Сбрасываем счетчик тегов и начинаем подсчет заново
            self.unique_tag = {}

            # Обработка вопросов с вводом строки
            for question in input_string_questions:
                tag_name = "Без тэга"
                if question.tag_id and question.tag_id in tags_dict:
                    tag_name = tags_dict[question.tag_id].name
                self.unique_tag[tag_name] = (
                    self.unique_tag.get(tag_name, 0) + 1
                )

                self.questions.append(
                    (
                        question.question,
                        "Ввод строки",
                        question.answers,
                        tag_name if tag_name != "Без тэга" else None,
                    )
                )
                item_text = f"{tag_name} — {question.question[:50]}..."
                self.question_list.addItem(item_text)

            # Обработка вопросов с выбором ответов
            for question in checkbox_questions:
                tag_name = "Без тэга"
                if question.tag_id and question.tag_id in tags_dict:
                    tag_name = tags_dict[question.tag_id].name
                self.unique_tag[tag_name] = (
                    self.unique_tag.get(tag_name, 0) + 1
                )

                # Загрузка правильных и неправильных ответов
                correct_answers = session.scalars(
                    select(AnswersCheckBoxOrm.text).where(
                        AnswersCheckBoxOrm.question_id == question.id,
                        AnswersCheckBoxOrm.is_correct == True,
                    )
                ).all()

                wrong_answers = session.scalars(
                    select(AnswersCheckBoxOrm.text).where(
                        AnswersCheckBoxOrm.question_id == question.id,
                        AnswersCheckBoxOrm.is_correct == False,
                    )
                ).all()

                self.questions.append(
                    (
                        question.question,
                        "Выбор правильн(ого/ых) ответов",
                        [list(correct_answers), list(wrong_answers)],
                        tag_name if tag_name != "Без тэга" else None,
                    )
                )
                item_text = f"{tag_name} — {question.question[:50]}..."
                self.question_list.addItem(item_text)

            # Обработка вопросов с упорядочиванием
            for question in replacement_questions:
                tag_name = "Без тэга"
                if question.tag_id and question.tag_id in tags_dict:
                    tag_name = tags_dict[question.tag_id].name
                self.unique_tag[tag_name] = (
                    self.unique_tag.get(tag_name, 0) + 1
                )

                # Загрузка ответов в правильном порядке
                answers = session.scalars(
                    select(AnswersReplacementOrm.text)
                    .where(AnswersReplacementOrm.question_id == question.id)
                    .order_by(AnswersReplacementOrm.number_in_answer)
                ).all()

                self.questions.append(
                    (
                        question.question,
                        "Упорядочивание",
                        list(answers),
                        tag_name if tag_name != "Без тэга" else None,
                    )
                )
                item_text = f"{tag_name} — {question.question[:50]}..."
                self.question_list.addItem(item_text)

    # Возвращение в главное меню
    def comeback_startmenu(self):
        self.window = StartWindow()
        self.window.load_tests()
        self.window.show()
        self.close()

    @QtCore.pyqtSlot()
    def set_font_size(self):
        size = int(self.size_box.currentText())
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self.apply_format(fmt)

    @QtCore.pyqtSlot()
    def set_font(self, font):
        fmt = QTextCharFormat()
        fmt.setFontFamily(font.family())
        self.apply_format(fmt)

    @QtCore.pyqtSlot()
    def set_bold(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(
            QFont.Bold if self.bold_btn.isChecked() else QFont.Normal
        )
        self.apply_format(fmt)

    @QtCore.pyqtSlot()
    def set_italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(self.italic_btn.isChecked())
        self.apply_format(fmt)

    @QtCore.pyqtSlot()
    def set_underline(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(self.underline_btn.isChecked())
        self.apply_format(fmt)

    def apply_format(self, fmt):
        cursor = self.answer_on_question.question_text.textCursor()
        cursor.mergeCharFormat(fmt)  # Применить формат к выделенному тексту
        self.answer_on_question.question_text.setTextCursor(cursor)

    # Очистка полей после сохранения вопроса
    def clear_question_fields(self):
        self.answer_on_question.question_text.clear()
        self.answer_on_question.input_string_widget.clear()
        self.answer_on_question.answer_widget_container.setCurrentIndex(0)
        self.answer_on_question.type_selector.setCurrentText("Ввод строки")

        # очистка правильных ответов (оставляем только первый lineedit)
        for i in reversed(
            range(2, self.answer_on_question.right_answer_layout.count() - 3)
        ):
            widget = self.answer_on_question.right_answer_layout.itemAt(
                i
            ).widget()
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.deleteLater()
                self.answer_on_question.right_answer_layout.removeWidget(
                    widget
                )

        # очистка неправильных ответов
        for i in reversed(
            range(1, self.answer_on_question.wrong_answer_layout.count() - 3)
        ):
            widget = self.answer_on_question.wrong_answer_layout.itemAt(
                i
            ).widget()
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.deleteLater()
                self.answer_on_question.wrong_answer_layout.removeWidget(
                    widget
                )

        # очистка полей с упорядочиванием
        for i in reversed(
            range(3, self.answer_on_question.main_layout.count() - 3)
        ):
            widget = self.answer_on_question.main_layout.itemAt(i).widget()
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.deleteLater()
                self.answer_on_question.main_layout.removeWidget(widget)

        # очистка статичных полей в упорядочивании и выборе ответа
        first_right = self.answer_on_question.right_answer_layout.itemAt(
            1
        ).widget()
        first_str = self.answer_on_question.main_layout.itemAt(1).widget()
        second_str = self.answer_on_question.main_layout.itemAt(2).widget()
        if isinstance(first_right, QtWidgets.QLineEdit):
            first_right.clear()
        if isinstance(first_str, QtWidgets.QLineEdit):
            first_str.clear()
        if isinstance(second_str, QtWidgets.QLineEdit):
            second_str.clear()

        # после очистки обновляем состояние кнопок
        self.answer_on_question._update_delete_buttons()


class QuestionWindow(QtWidgets.QFrame, QuestionReplacementMixin):
    def __init__(
        self,
        id_test: int,
        test_name: str,
        start_window: StartWindow,
        parent=None,
    ):
        super().__init__(parent)

        self.id_test = id_test
        self.last_window = start_window

        self.true_answer: int = 0
        self.current_index: int = 0
        self.do_question: int = 0

        self.setWindowTitle("Прохождение теста")
        self.resize(2000, 1000)

        main_layout = QtWidgets.QVBoxLayout()
        header = QtWidgets.QLabel(f"Тест: {test_name}")
        header.setStyleSheet("font-size: 16pt;")
        main_layout.addWidget(header)

        # Загружаем список вопросов (а не генератор!)
        self.questions = self.get_questions()
        self.limit = len(self.questions)

        # Список для контроля отвеченных и не отвеченных вопросов
        self.not_look_question = [True] * self.limit

        down_main_layout = QtWidgets.QHBoxLayout()
        self.question_grid = QuestionGrid(total_questions=self.limit, cols=3)
        down_main_layout.addWidget(self.question_grid)

        # Даем grid знать про главное окно
        for i, btn in enumerate(self.question_grid.buttons):
            btn.clicked.connect(lambda _, idx=i: self.load_question(idx))

        # Правая часть
        self.right_layout = QtWidgets.QVBoxLayout()
        self.label_question = QtWidgets.QLabel()
        self.label_question.setAlignment(
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop
        )
        self.label_question.setWordWrap(True)
        self.right_layout.addWidget(self.label_question, stretch=1)

        self.answer = QtWidgets.QVBoxLayout()
        self.right_layout.addLayout(self.answer)

        self.navigation_on_questions = NavigationOnQuestion()
        self.right_layout.addWidget(self.navigation_on_questions)
        self.navigation_on_questions.btn_next_question.clicked.connect(
            self.next_question
        )
        self.navigation_on_questions.btn_reply_question.clicked.connect(
            self.reply_question
        )
        self.navigation_on_questions.btn_end_test.clicked.connect(
            self.end_test
        )

        down_main_layout.addLayout(self.right_layout, stretch=1)
        main_layout.addLayout(down_main_layout)
        self.setLayout(main_layout)
        self.load_question(0)

    def prev_question(self):
        pass

    @QtCore.pyqtSlot()
    def reply_question(self):
        if not self.not_look_question[self.current_index]:
            # уже отвечен → ничего не делаем
            return

        if self.check_answer():
            self.true_answer += 1

        self.not_look_question[self.current_index] = False
        self.question_grid.set_button_status(self.current_index, "Отвечен")

        # блокируем кнопку "ответить" сразу после ответа
        self.navigation_on_questions.btn_reply_question.setEnabled(False)

        self.next_question()

    @QtCore.pyqtSlot()
    def next_question(self):
        start_index = (self.current_index + 1) % self.limit

        for shift in range(self.limit):
            idx = (start_index + shift) % self.limit
            if self.not_look_question[idx]:
                self.load_question(idx)
                return

        # все вопросы отвечены
        self.navigation_on_questions.btn_next_question.setEnabled(False)
        self.navigation_on_questions.btn_end_test.setEnabled(True)

    @QtCore.pyqtSlot()
    def end_test(self):
        clear_layout(self.right_layout)
        self.right_layout.addWidget(
            QtWidgets.QLabel(
                f"Ваш результат: {round(self.true_answer/self.limit*100)}%"
            )
        )
        btn_comeback_startmenu = QtWidgets.QPushButton(
            "Вернуться в главное меню"
        )
        btn_comeback_startmenu.clicked.connect(self.comeback_startmenu)

        self.right_layout.addWidget(btn_comeback_startmenu)

    # Генератор с запросом к БД с получением данных о вопросе
    def get_questions(self):
        with session_sync_factory() as session:
            query = (
                select(TestsOrm)
                .options(
                    selectinload(TestsOrm.tags).selectinload(
                        TagsOrm.questions_check_box
                    ),
                    selectinload(TestsOrm.tags).selectinload(
                        TagsOrm.questions_replacement
                    ),
                    selectinload(TestsOrm.tags).selectinload(
                        TagsOrm.questions_input_string
                    ),
                )
                .where(TestsOrm.id == self.id_test)
            )
            result = session.execute(query)
            test = result.scalars().one_or_none()
            if not test:
                return []

            chosen_questions = []

            # для каждого тэга — выбираем count вопросов из него
            for tag in test.tags:
                tag_questions = (
                    tag.questions_check_box
                    + tag.questions_replacement
                    + tag.questions_input_string
                )

                if tag_questions:
                    selected = sample(
                        tag_questions, min(len(tag_questions), tag.count)
                    )
                    chosen_questions.extend(selected)

            # возвращаем список вопросов с нужными данными
            return [
                {
                    "question": q.question,
                    "answer": q.answers,
                    "type": q.__tablename__,
                }
                for q in chosen_questions
            ]

    def load_question(self, index: int):
        if index < 0 or index >= len(self.questions):
            return

        # сбросить предыдущий выбор
        self.question_grid.reset_selected()

        self.current_index = index
        self.current_question = self.questions[index]

        # статус текущей кнопки → выбран
        self.question_grid.set_button_status(index, "Выбран")

        # текст вопроса
        self.label_question.setText(self.current_question["question"])

        # очистка и добавление новых ответов
        clear_layout(self.answer)
        self.add_widgets_answer()

        # кнопка "ответить":
        # если вопрос уже отвечен — отключаем её
        if not self.not_look_question[index]:
            self.navigation_on_questions.btn_reply_question.setEnabled(False)
        elif self.current_question["type"] == "QuestionsReplacement":
            # для replacement активируем только когда всё выбрано
            self.navigation_on_questions.btn_reply_question.setEnabled(False)
        else:
            # для остальных типов активируем сразу
            self.navigation_on_questions.btn_reply_question.setEnabled(True)

    # Загрузка в окно с вопросом подходящий под вопрос виджет
    def add_widgets_answer(self):
        if self.current_question["type"] == "QuestionsCheckBox":
            for i in self.current_question["answer"]:
                self.answer.addWidget(QtWidgets.QCheckBox(i.text))

        elif self.current_question["type"] == "QuestionsReplacement":
            self.replacement_order = []
            self.current_question["replacement_buttons"] = []
            self.true_replacement = []

            for i in set(self.current_question["answer"]):
                hbox = QtWidgets.QHBoxLayout()

                label = QtWidgets.QLabel(i.text)
                self.true_replacement.append(i.number_in_answer)

                label.setSizePolicy(
                    QtWidgets.QSizePolicy.Expanding,
                    QtWidgets.QSizePolicy.Preferred,
                )

                btn = QtWidgets.QPushButton("")
                btn.setFixedSize(20, 20)
                btn.setProperty("original_text", i.text)
                btn.setStyleSheet("background-color: lightgray;")
                btn.clicked.connect(
                    lambda _, b=btn: self.handle_replacement_click(b)
                )

                hbox.addWidget(btn)
                hbox.addWidget(label)
                self.answer.addLayout(hbox)

                self.current_question["replacement_buttons"].append(btn)

        elif self.current_question["type"] == "QuestionsInputString":
            self.answer.addWidget(QtWidgets.QLineEdit())

    # Получение ответа пользователя в зависимости от типа вопроса
    def get_user_answers(self):
        checked_answers = []
        if self.current_question["type"] == "QuestionsCheckBox":
            for i in range(self.answer.count()):
                item = self.answer.itemAt(i)
                checkbox = item.widget()
                if (
                    isinstance(checkbox, QtWidgets.QCheckBox)
                    and checkbox.isChecked()
                ):
                    checked_answers.append(checkbox.text())
        elif self.current_question["type"] == "QuestionsReplacement":
            for i in range(self.answer.count()):
                item = self.answer.itemAt(i).itemAt(0)
                w = item.widget()
                checked_answers.append(int(w.text()))
        elif self.current_question["type"] == "QuestionsInputString":
            return self.answer.itemAt(0).widget().text()
        return checked_answers

    # Проверка выбранных оветов пользователем
    def check_answer(self):
        answer_user = self.get_user_answers()
        if self.current_question["type"] == "QuestionsCheckBox":
            for answer in self.current_question["answer"]:
                if answer.is_correct and answer.text not in answer_user:
                    return False
                if (not answer.is_correct) and answer.text in answer_user:
                    return False
            return True
        elif self.current_question["type"] == "QuestionsReplacement":
            if self.true_replacement == answer_user:
                return True
        elif self.current_question["type"] == "QuestionsInputString":
            if answer_user == self.current_question["answer"]:
                return True
        return False

    def check_replacement_ready(self):
        if self.current_question["type"] == "QuestionsReplacement":
            # Все кнопки должны быть нажаты (т.е. текст не пустой)
            for btn in self.current_question["replacement_buttons"]:
                if btn.text().strip() == "":
                    return False
            return True
        return True

    # Возвращение в главное меню
    @QtCore.pyqtSlot()
    def comeback_startmenu(self):
        self.last_window.show()
        self.close()


async def setup_database():
    async with async_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    await async_engine.dispose()


async def insert_data_database():
    async with session_async_factory() as session:
        answers1 = [
            {
                "text": "смещенной",
                "is_corrected": False,
            },
            {
                "text": "несмещенной",
                "is_corrected": True,
            },
            {
                "text": "состоятельной",
                "is_corrected": True,
            },
            {
                "text": "несостоятельной",
                "is_corrected": False,
            },
            {
                "text": "доверительной",
                "is_corrected": False,
            },
            {
                "text": "нормальной",
                "is_corrected": False,
            },
        ]
        answers2 = [
            {
                "text": "число опытов мало",
                "is_corrected": True,
            },
            {
                "text": "число опытов велика",
                "is_corrected": False,
            },
            {
                "text": "заданы большие (>50) значения случайной величины",
                "is_corrected": False,
            },
            {
                "text": "заданы маленькие (<1 значения случайной величины)",
                "is_corrected": False,
            },
        ]
        answers3 = [
            "Строят прямые, уравнения которых получаются в результате замены в ограничениях знаков неравенств на знаки точных равенств",
            "Находят полуплоскости, определяемые каждым из ограничений задачи",
            "Находят многоугольник решений",
            "Строят вектор",
            "Строят прямую, проходящую через многоугольник решений",
            "Передвигают прямую в направлении веткора, в результате чего-либо находят точку"
            " (точки), в которой целвая функция принимает максимальное значение, "
            "либо устанавливают неограниченность сверху функции нам ножестве планов",
            "Определяют координаты точки максимума функции и вычисляют значение целевой функции"
            "в этой точке",
        ]
        question1 = QuestionsCheckBoxOrm(
            question="Выбрать все правильные варинат ответа\n"
            "Оценка параметра рассположения должна быть ______",
            answers=[
                AnswersCheckBoxOrm(
                    text=ans["text"], is_correct=ans["is_corrected"]
                )
                for ans in answers1
            ],
        )
        question2 = QuestionsCheckBoxOrm(
            question="Выбрать правильный вариант ответа.\n"
            "Для оценки параметра распределения случайной величины"
            "используют доверительные интервалы, если",
            answers=[
                AnswersCheckBoxOrm(
                    text=ans["text"], is_correct=ans["is_corrected"]
                )
                for ans in answers2
            ],
        )
        question3 = QuestionsReplacementOrm(
            question="Последовательность решения задачи линейного "
            "программирования на основе ее геометрической интерпретации",
            answers=[
                AnswersReplacementOrm(
                    text=ans, number_in_answer=answers3.index(ans) + 1
                )
                for ans in answers3
            ],
        )
        test = TestsOrm(
            name_test="Первый тест",
            teacher="Поляков",
            questions_check_box=[question1, question2],
            questions_replacement=[question3],
        )
        session.add(test)
        await session.flush()
        await session.commit()


async def first_work_database(window):
    print("Загрузка данных")
    await setup_database()
    print("Добавление данных в таблицы")
    await insert_data_database()
    print("Работа с БД закончилась")

    window.create_default_teacher()


async def main():
    app = QtWidgets.QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = LoginWindow()
    window.show()

    # Запускаем асинхронную задачу по работе с БД
    loop.create_task(first_work_database(window))

    loop.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print("Asyncio RuntimeError (можно игнорировать):", e)
