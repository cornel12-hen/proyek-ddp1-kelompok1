import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base

class AnonymityMode(str, enum.Enum):
    OPEN_ONLY   = "OPEN_ONLY"    # Semua peserta selalu tampil dengan nama asli
    ANON_ONLY   = "ANON_ONLY"    # Semua peserta selalu tampil dengan nama samaran
    USER_CHOICE = "USER_CHOICE"  # Setiap postingan bisa memilih sendiri

class QuizType(str, enum.Enum):
    NATIVE   = "NATIVE"    # Quiz dibuat langsung di sini (dengan JSON soal)
    EXTERNAL = "EXTERNAL"  # Quiz hanya berupa link ke Google Form, Quizizz, dll.

class TargetType(str, enum.Enum):
    QUESTION = "QUESTION"  # Upvote untuk PublicQuestion
    REPLY    = "REPLY"     # Upvote untuk PublicReply

class User(Base):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(50), unique=True, nullable=False, index=True)
    email           = Column(String(255), unique=True, nullable=False)
    password_hash   = Column(String(255), nullable=False)
    full_name       = Column(String(150), nullable=False)
    batch_year      = Column(Integer, nullable=False)
    anonymous_alias = Column(String(100), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)

    memberships      = relationship("SpaceMember", back_populates="user")
    public_questions = relationship("PublicQuestion", back_populates="author")
    public_replies   = relationship("PublicReply", back_populates="author")
    upvotes          = relationship("Upvote", back_populates="user")
    quiz_submissions = relationship("QuizSubmission", back_populates="user")

class Space(Base):
    __tablename__ = "spaces"
    id             = Column(Integer, primary_key=True, index=True)
    title          = Column(String(200), nullable=False)
    description    = Column(Text, nullable=True)
    invite_code    = Column(String(20), unique=True, nullable=False, index=True)
    admin_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    anonymity_mode = Column(Enum(AnonymityMode), default=AnonymityMode.USER_CHOICE, nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)

    admin     = relationship("User", foreign_keys=[admin_id])
    members   = relationship("SpaceMember", back_populates="space")
    resources = relationship("SpaceResource", back_populates="space")
    threads   = relationship("SpaceThread", back_populates="space")
    quizzes   = relationship("Quiz", back_populates="space")

class SpaceMember(Base):
    __tablename__ = "space_members"
    id        = Column(Integer, primary_key=True, index=True)
    space_id  = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    space = relationship("Space", back_populates="members")
    user  = relationship("User", back_populates="memberships")


class SpaceResource(Base):
    __tablename__ = "space_resources"
    id               = Column(Integer, primary_key=True, index=True)
    space_id         = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    title            = Column(String(200), nullable=False)
    content_md       = Column(Text, nullable=True)
    file_or_link_url = Column(String(500), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)

    space = relationship("Space", back_populates="resources")

class SpaceThread(Base):
    __tablename__ = "space_threads"
    id           = Column(Integer, primary_key=True, index=True)
    space_id     = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    author_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    title        = Column(String(300), nullable=False)
    body         = Column(Text, nullable=False)
    is_anonymous = Column(Boolean, default=False, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    space   = relationship("Space", back_populates="threads")
    author  = relationship("User")
    replies = relationship("SpaceReply", back_populates="thread")


class SpaceReply(Base):
    __tablename__ = "space_replies"
    id           = Column(Integer, primary_key=True, index=True)
    thread_id    = Column(Integer, ForeignKey("space_threads.id"), nullable=False)
    author_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    body         = Column(Text, nullable=False)
    is_anonymous = Column(Boolean, default=False, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    thread = relationship("SpaceThread", back_populates="replies")
    author = relationship("User")

class Quiz(Base):
    __tablename__ = "quizzes"
    id             = Column(Integer, primary_key=True, index=True)
    space_id       = Column(Integer, ForeignKey("spaces.id"), nullable=False)
    title          = Column(String(200), nullable=False)
    description    = Column(Text, nullable=True)
    quiz_type      = Column(Enum(QuizType), default=QuizType.NATIVE, nullable=False)
    external_url   = Column(String(500), nullable=True)
    questions_json = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)

    space       = relationship("Space", back_populates="quizzes")
    submissions = relationship("QuizSubmission", back_populates="quiz")


class QuizSubmission(Base):
    __tablename__ = "quiz_submissions"
    id           = Column(Integer, primary_key=True, index=True)
    quiz_id      = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    answers_json = Column(Text, nullable=False)
    total_score  = Column(Float, default=0.0, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    quiz = relationship("Quiz", back_populates="submissions")
    user = relationship("User", back_populates="quiz_submissions")

class PublicQuestion(Base):
    __tablename__ = "public_questions"
    id           = Column(Integer, primary_key=True, index=True)
    author_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    title        = Column(String(300), nullable=False)
    body         = Column(Text, nullable=False)
    topic_tag    = Column(String(100), nullable=True)
    is_anonymous = Column(Boolean, default=False, nullable=False)
    upvote_count = Column(Integer, default=0, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    author  = relationship("User", back_populates="public_questions")
    replies = relationship("PublicReply", back_populates="question")


class PublicReply(Base):
    __tablename__ = "public_replies"
    id           = Column(Integer, primary_key=True, index=True)
    question_id  = Column(Integer, ForeignKey("public_questions.id"), nullable=False)
    author_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    body         = Column(Text, nullable=False)
    is_anonymous = Column(Boolean, default=False, nullable=False)
    upvote_count = Column(Integer, default=0, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    question = relationship("PublicQuestion", back_populates="replies")
    author   = relationship("User", back_populates="public_replies")

class Upvote(Base):
    __tablename__ = "upvotes"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_type = Column(Enum(TargetType), nullable=False)
    target_id   = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_id", name="uq_upvote"),
    )

    user = relationship("User", back_populates="upvotes")