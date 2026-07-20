from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- Auth ----------

class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=24)
    password: str = Field(min_length=4, max_length=100)
    emoji: str = Field(default="🂡", max_length=8)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    emoji: str


# ---------- Partidas ----------

class GameCreate(BaseModel):
    game_type: str = Field(default="knockout")
    buy_in_amount: Optional[float] = Field(default=None, ge=0)


class BuyInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserOut
    status: str
    requested_at: datetime


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserOut
    position: Optional[int]
    eliminated_at: Optional[datetime]
    exit_requested: bool


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_type: str
    status: str
    buy_in_amount: Optional[float]
    admin: UserOut
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    winner: Optional[UserOut]
    participants: list[ParticipantOut]
    buyins: list[BuyInOut]


class EliminateIn(BaseModel):
    user_id: int


# ---------- Estadisticas ----------

class PlayerStats(BaseModel):
    user: UserOut
    games_played: int
    wins: int
    podiums: int
    win_rate: float
    avg_position: Optional[float]
    current_streak: int
    total_buyins: int


class StatsOut(BaseModel):
    leaderboard: list[PlayerStats]
    total_games: int
