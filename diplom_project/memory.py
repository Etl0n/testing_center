# Загрузка следующего вопроса при прохождении теста
@QtCore.pyqtSlot()
def next_question(self):
    if self.check_answer():
        self.true_answer += 1

    if self.current_index + 1 >= len(self.questions):
        self.label_question.setText(
            "Вопросы закончились, ваш результат "
            f"{round(self.true_answer / len(self.questions) * 100)} %"
        )
        clear_layout(self.answer)
        self.btnNext.clicked.disconnect(self.next_question)
        self.btnNext.setText("Вернуться в главное меню")
        self.btnNext.clicked.connect(self.comeback_startmenu)
    else:
        self.load_question(self.current_index + 1)
