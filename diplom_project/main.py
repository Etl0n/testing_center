import asyncio
import base64
import os
import re
import sys

from database import async_engine, sync_engine
from models import (
    AnswersCheckBoxOrm,
    AnswersReplacementOrm,
    Base,
    QuestionsCheckBoxOrm,
    QuestionsInputStringOrm,
    QuestionsReplacementOrm,
    TestsOrm,
)
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QFont, QImage, QTextCharFormat
from PyQt5.QtWidgets import QFileDialog
from qasync import QEventLoop
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import sessionmaker

# Установка пути к плагинам PyQt5 (если нужно)
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(
    os.path.dirname(__file__)[:-14],
    "venv/Lib/site-packages/PyQt5/Qt5/plugins/platforms",
)

session_async_factory = async_sessionmaker(async_engine)
session_sync_factory = sessionmaker(sync_engine)

fmt = QtGui.QTextTableFormat()
fmt.setBorder(1)  # Толщина внешней рамки
fmt.setCellPadding(7)  # Отступ внутри ячеек
fmt.setCellSpacing(0)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        if item.layout():
            clear_layout(item)


class QuestionReplacementMixin:
    def handle_replacement_click(self, button):
        if button in self.replacement_order:
            self.replacement_order.remove(button)
        else:
            self.replacement_order.append(button)
        self.update_replacement_labels()

    def update_replacement_labels(self):
        for i, button in enumerate(self.replacement_order):
            button.setText(f"{i+1}")
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


class QuestionEditor(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Создание теста")

        self.questions = []  # Список временных вопросов
        self.current_edit_index = None

        self.question_text = CustomTextEdit()
        self.answer_on_question = QtWidgets.QLineEdit()
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
        left_layout.addWidget(self.question_text)
        left_layout.addWidget(QtWidgets.QLabel("Введите ответ:"))
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

        cursor = self.question_text.textCursor()
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
        cursor = self.question_text.textCursor()
        html_img = self.question_text._image_to_base64_html(image)
        cursor.insertHtml(html_img)

    @QtCore.pyqtSlot()
    def save_question_temp(self):
        html = self.question_text.toHtml()
        answer = self.answer_on_question.text()
        tag = self.tag_for_question.text()

        item_text = f"{tag or 'Без тега'} — {html[:-18][435:500]}..."

        if self.current_edit_index is not None:
            self.questions[self.current_edit_index] = (
                html,
                answer,
                tag or None,
            )
            self.question_list.item(self.current_edit_index).setText(item_text)
            self.current_edit_index = None
        else:
            self.questions.append((html, answer, tag or None))
            self.question_list.addItem(item_text)

        self.clear_question_fields()

    def load_selected_question(self, item):
        index = self.question_list.row(item)
        html, answer, tag = self.questions[index]

        self.question_text.setHtml(html)
        self.answer_on_question.setText(answer)
        self.tag_for_question.setText(tag)
        self.current_edit_index = index

    @QtCore.pyqtSlot()
    def save_all_questions(self):
        with session_sync_factory() as session:
            for i in range(len(self.question_list)):
                input_question = QuestionsInputStringOrm(
                    test_id=1,
                    question=self.questions[i][0],
                    answers=self.questions[i][1],
                    tag=self.questions[i][2],
                )
                session.add(input_question)
            session.commit()
        self.comeback_startmenu()

    # Возвращение в главное меню
    @QtCore.pyqtSlot()
    def comeback_startmenu(self):
        self.start_window = StartWindow()
        self.start_window.show()
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
        cursor = self.question_text.textCursor()
        cursor.mergeCharFormat(fmt)  # Применить формат к выделенному тексту
        self.question_text.setTextCursor(cursor)

    def clear_question_fields(self):
        self.question_text.clear()
        self.answer_on_question.clear()


class QuestionWindow(QtWidgets.QFrame, QuestionReplacementMixin):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.true_answer: int = 0
        self.count_question: int = 0

        self.setWindowTitle("Вопрос")
        self.resize(2000, 1000)

        layout = QtWidgets.QVBoxLayout()

        self.questions = self.get_question()

        self.current_question = next(self.questions)

        self.label_question = QtWidgets.QLabel(
            self.current_question["question"]
        )
        self.label_question.setAlignment(
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop
        )
        self.label_question.setWordWrap(True)
        layout.addWidget(self.label_question)

        self.answer = QtWidgets.QVBoxLayout()
        self.add_widgets_answer()
        layout.addLayout(self.answer)

        self.btnNext = QtWidgets.QPushButton("&Следуюищйй вопрос")
        self.btnNext.clicked.connect(self.next_question)
        layout.addWidget(self.btnNext)

        self.setLayout(layout)

    # Загрузка следующего вопроса при прохождении теста
    @QtCore.pyqtSlot()
    def next_question(self):
        # Проверка на правильность ответа
        if self.check_answer():
            self.true_answer += 1
        try:
            # Получение следующего вопроса
            self.current_question = next(self.questions)
        except StopIteration:
            self.label_question.setText(
                "Вопросы закончились, ваш результат "
                f"{round(self.true_answer / self.count_question * 100)} %"
            )
            clear_layout(self.answer)
            self.btnNext.clicked.disconnect(self.next_question)
            self.btnNext.setText("Вернуться в главное меню")
            self.btnNext.clicked.connect(self.comeback_startmenu)
            return

        # Обновление текста вопроса
        self.label_question.setText(self.current_question["question"])

        # Очистка старых чекбоксов
        clear_layout(self.answer)

        # Добавление новых ответов
        self.add_widgets_answer()

    # Генератор с запросом к БД с получением данных о вопросе
    def get_question(self):
        with session_sync_factory() as session:
            # Должен браться взависимости от выбранного теста
            id_test = 1
            query = select(TestsOrm).where(TestsOrm.id == id_test)
            result = session.execute(query)
            choose_test = result.scalars().one_or_none()
            questions = set(
                choose_test.questions_check_box
                + choose_test.questions_replacement
                + choose_test.questions_input_string
            )
            self.count_question = len(questions)
            for i in questions:
                yield {
                    "question": i.question,
                    "answer": i.answers,
                    "type": i.__tablename__,
                }

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

    # Возвращение в главное меню
    @QtCore.pyqtSlot()
    def comeback_startmenu(self):
        self.start_window = StartWindow()
        self.start_window.show()
        self.close()


class StartWindow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Стартовое окно")

        self.label = QtWidgets.QLabel("Стартовое окно")
        self.label.setAlignment(QtCore.Qt.AlignHCenter)

        self.btnStartTest = QtWidgets.QPushButton("&Начать тест")
        self.btnStartTest.clicked.connect(self.open_test_window)

        self.btnCreateTest = QtWidgets.QPushButton("&Создать тест")
        self.btnCreateTest.clicked.connect(self.open_create_test_window)

        self.vbox = QtWidgets.QVBoxLayout()
        self.vbox.addWidget(self.label)
        self.vbox.addWidget(self.btnStartTest)
        self.vbox.addWidget(self.btnCreateTest)
        self.setLayout(self.vbox)

    def open_test_window(self):
        self.qeustion_window = QuestionWindow()
        # self.qeustion_window.showFullScreen()
        self.qeustion_window.show()
        self.close()

    def open_create_test_window(self):
        self.qeustion_window = QuestionEditor()
        self.qeustion_window.show()
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
    window.btnStartTest.setEnabled(False)
    print("Загрузка данных")
    await setup_database()
    print("Добавление данных в таблицы")
    await insert_data_database()
    print("Работа с БД закончилась")
    window.btnStartTest.setEnabled(True)


async def main():
    app = QtWidgets.QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = StartWindow()
    window.show()

    # Запускаем асинхронную задачу по работе с БД
    loop.create_task(first_work_database(window))

    loop.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print("Asyncio RuntimeError (можно игнорировать):", e)
