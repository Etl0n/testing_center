from typing import Annotated, Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)

# сокращение для id-шников
idpk = Annotated[int, mapped_column(primary_key=True)]


class Base(DeclarativeBase):
    pass


class GroupsOrm(Base):
    __tablename__ = "groups"

    id: Mapped[idpk]
    name: Mapped[str] = mapped_column(unique=True, nullable=False)

    students: Mapped[list["StudentsOrm"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


# ---- Студенты ----
class StudentsOrm(Base):
    __tablename__ = "students"

    id: Mapped[idpk]
    login: Mapped[str] = mapped_column(unique=True, nullable=False)
    password: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str]
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))

    group: Mapped["GroupsOrm"] = relationship(back_populates="students")


# ---- Преподаватели ----
class TeachersOrm(Base):
    __tablename__ = "teachers"

    id: Mapped[idpk]
    login: Mapped[str] = mapped_column(unique=True, nullable=False)
    password: Mapped[str] = mapped_column(nullable=False)


# ---- Базовый класс для всех вопросов ----
class QuestionBase(Base):
    __abstract__ = True  # таблица для него не создаётся

    id: Mapped[idpk]
    question: Mapped[str] = mapped_column(Text)

    @declared_attr
    def tag_id(cls) -> Mapped[Optional[int]]:
        return mapped_column(
            ForeignKey("tags.id", ondelete="SET NULL"), nullable=True
        )

    @declared_attr
    def test_id(cls) -> Mapped[int]:
        return mapped_column(
            ForeignKey("tests.id", ondelete="CASCADE"), nullable=False
        )


# ---- Тэги ----
class TagsOrm(Base):
    __tablename__ = "tags"

    id: Mapped[idpk]
    name: Mapped[str]  # название тэга (например "Алгебра")
    count: Mapped[int] = mapped_column(default=0)  # сколько вопросов выбрать

    test_id: Mapped[int] = mapped_column(
        ForeignKey("tests.id", ondelete="CASCADE"), nullable=False
    )
    test = relationship("TestsOrm", back_populates="tags")

    # связи с разными типами вопросов
    questions_check_box: Mapped[list["QuestionsCheckBoxOrm"]] = relationship(
        back_populates="tag_obj"
    )
    questions_replacement: Mapped[list["QuestionsReplacementOrm"]] = (
        relationship(back_populates="tag_obj")
    )
    questions_input_string: Mapped[list["QuestionsInputStringOrm"]] = (
        relationship(back_populates="tag_obj")
    )


# ---- Тесты ----
class TestsOrm(Base):
    __tablename__ = "tests"

    id: Mapped[idpk]
    name_test: Mapped[str] = mapped_column(unique=True)
    teacher: Mapped[str]

    tags: Mapped[list["TagsOrm"]] = relationship(
        back_populates="test", cascade="all, delete-orphan"
    )

    questions_check_box: Mapped[list["QuestionsCheckBoxOrm"]] = relationship(
        back_populates="test"
    )
    questions_replacement: Mapped[list["QuestionsReplacementOrm"]] = (
        relationship(back_populates="test")
    )
    questions_input_string: Mapped[list["QuestionsInputStringOrm"]] = (
        relationship(back_populates="test")
    )


# ---- Вопросы с выбором ----
class QuestionsCheckBoxOrm(QuestionBase):
    __tablename__ = "questionscheckbox"

    answers = relationship("AnswersCheckBoxOrm", back_populates="question")
    test = relationship("TestsOrm", back_populates="questions_check_box")
    tag_obj = relationship("TagsOrm", back_populates="questions_check_box")


class AnswersCheckBoxOrm(Base):
    __tablename__ = "answerscheckbox"

    id: Mapped[idpk]
    text: Mapped[str]
    is_correct: Mapped[bool] = mapped_column(default=False)

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questionscheckbox.id", ondelete="CASCADE"), nullable=False
    )
    question = relationship("QuestionsCheckBoxOrm", back_populates="answers")


# ---- Вопросы на упорядочивание ----
class QuestionsReplacementOrm(QuestionBase):
    __tablename__ = "questionsreplacement"

    answers = relationship("AnswersReplacementOrm", back_populates="question")
    test = relationship("TestsOrm", back_populates="questions_replacement")
    tag_obj = relationship("TagsOrm", back_populates="questions_replacement")


class AnswersReplacementOrm(Base):
    __tablename__ = "answersreplacement"

    id: Mapped[idpk]
    text: Mapped[str]
    number_in_answer: Mapped[int]

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questionsreplacement.id", ondelete="CASCADE"),
        nullable=False,
    )
    question = relationship(
        "QuestionsReplacementOrm", back_populates="answers"
    )


# ---- Вопросы с вводом строки ----
class QuestionsInputStringOrm(QuestionBase):
    __tablename__ = "questionsinputstring"

    answers: Mapped[str]
    test = relationship("TestsOrm", back_populates="questions_input_string")
    tag_obj = relationship("TagsOrm", back_populates="questions_input_string")
