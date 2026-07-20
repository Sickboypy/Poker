from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    emoji = Column(String, default="🂡", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    participations = relationship(
        "GameParticipant", back_populates="user", foreign_keys="GameParticipant.user_id"
    )


class Session(Base):
    __tablename__ = "sessions"

    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)

    # Tipo de juego: hoy solo "knockout". Extensible a "cash", etc.
    game_type = Column(String, default="knockout", nullable=False, index=True)

    # "open" (esperando jugadores) | "in_progress" | "finished" | "cancelled"
    status = Column(String, default="open", nullable=False, index=True)

    # Valor de una caja (opcional). Si esta cargado, la app calcula totales.
    buy_in_amount = Column(Float, nullable=True)

    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    admin = relationship("User", foreign_keys=[admin_id])

    created_at = Column(DateTime, default=utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner = relationship("User", foreign_keys=[winner_id])

    participants = relationship(
        "GameParticipant", back_populates="game", cascade="all, delete-orphan"
    )
    buyins = relationship(
        "BuyIn", back_populates="game", cascade="all, delete-orphan"
    )


class GameParticipant(Base):
    __tablename__ = "game_participants"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Posicion final: 1 = campeon, N = primero en salir. NULL = sigue en juego.
    position = Column(Integer, nullable=True)
    eliminated_at = Column(DateTime, nullable=True)

    # True si el jugador pidio retirarse y espera confirmacion del admin
    exit_requested = Column(Boolean, default=False, nullable=False)

    joined_at = Column(DateTime, default=utcnow, nullable=False)

    game = relationship("Game", back_populates="participants")
    user = relationship("User", back_populates="participations", foreign_keys=[user_id])


class BuyIn(Base):
    __tablename__ = "buyins"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # "pending" | "approved" | "rejected"
    status = Column(String, default="pending", nullable=False, index=True)

    requested_at = Column(DateTime, default=utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    game = relationship("Game", back_populates="buyins")
    user = relationship("User")
