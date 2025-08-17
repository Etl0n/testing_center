from typing import Annotated, Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)

idpk = Annotated[int, mapped_column(primary_key=True)]


class Base(DeclarativeBase):
    pass


class QuestionBase(Base):
    __abstract__ = True

    id: Mapped[idpk]
    question: Mapped[str] = mapped_column(Text)
    tag: Mapped[Optional[str]]

    @declared_attr
    def test_id(cls) -> Mapped[int]:
        return mapped_column(
            ForeignKey("Tests.id", ondelete="CASCADE"), nullable=False
        )


class TestsOrm(Base):
    __tablename__ = "Tests"

    id: Mapped[idpk]
    name_test: Mapped[str] = mapped_column(unique=True)
    teacher: Mapped[str]
    col_view_questions: Mapped[int]

    questions_check_box: Mapped[Optional[list["QuestionsCheckBoxOrm"]]] = (
        relationship(back_populates="test")
    )

    questions_replacement: Mapped[
        Optional[list["QuestionsReplacementOrm"]]
    ] = relationship(back_populates="test")

    questions_input_string: Mapped[
        Optional[list["QuestionsInputStringOrm"]]
    ] = relationship(back_populates="test")


class QuestionsCheckBoxOrm(QuestionBase):
    __tablename__ = "QuestionsCheckBox"

    answers = relationship("AnswersCheckBoxOrm", back_populates="question")
    test = relationship("TestsOrm", back_populates="questions_check_box")


class AnswersCheckBoxOrm(Base):
    __tablename__ = "AnswersCheckBox"

    id: Mapped[idpk]
    text: Mapped[str]
    is_correct: Mapped[bool] = mapped_column(default=False)
    question_id: Mapped[int] = mapped_column(
        ForeignKey('QuestionsCheckBox.id', ondelete="CASCADE"), nullable=False
    )

    question = relationship("QuestionsCheckBoxOrm", back_populates="answers")


class QuestionsReplacementOrm(QuestionBase):
    __tablename__ = "QuestionsReplacement"

    answers = relationship("AnswersReplacementOrm", back_populates="question")
    test = relationship("TestsOrm", back_populates="questions_replacement")


class AnswersReplacementOrm(Base):
    __tablename__ = "AnswersReplacement"

    id: Mapped[idpk]
    text: Mapped[str]
    number_in_answer: Mapped[int]
    question_id: Mapped[int] = mapped_column(
        ForeignKey('QuestionsReplacement.id', ondelete="CASCADE"),
        nullable=False,
    )

    question = relationship(
        "QuestionsReplacementOrm", back_populates="answers"
    )


class QuestionsInputStringOrm(QuestionBase):
    __tablename__ = "QuestionsInputString"

    answers: Mapped[str]
    test = relationship("TestsOrm", back_populates="questions_input_string")
