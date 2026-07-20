from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload

from . import schemas
from .auth import (
    get_current_user,
    get_db,
    hash_password,
    new_token,
    verify_password,
)
from .database import Base, engine
from .models import BuyIn, Game, GameParticipant, Session as SessionModel, User

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Poker pobre 98!")


GAME_TYPES = {
    "knockout": {
        "label": "Poker Highlander",
        "description": "Se juega hasta que queda un solo jugador en pie.",
        "min_players": 2,
        "available": True,
    },
    "cash": {
        "label": "Poker tradicional",
        "description": "Póquer tradicional, cada uno se retira cuando quiere.",
        "min_players": 2,
        "available": False,
    },
}


def utcnow():
    return datetime.now(timezone.utc)


# ============================================================
# Auth
# ============================================================

def _set_session(response: Response, db: Session, user: User) -> None:
    token = new_token()
    db.add(SessionModel(token=token, user_id=user.id))
    db.commit()
    response.set_cookie(
        "mf_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 90,  # 90 dias
    )


@app.post("/api/auth/register", response_model=schemas.UserOut)
def register(payload: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
    username = payload.username.strip()
    if not username:
        raise HTTPException(400, "El nombre de usuario no puede estar vacío")

    exists = db.query(User).filter(User.username.ilike(username)).first()
    if exists:
        raise HTTPException(400, f"El usuario «{username}» ya existe")

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        emoji=payload.emoji or "🂡",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session(response, db, user)
    return user


@app.post("/api/auth/login", response_model=schemas.UserOut)
def login(payload: schemas.LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username.ilike(payload.username.strip())).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    _set_session(response, db, user)
    return user


@app.post("/api/auth/logout", status_code=204)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    db.query(SessionModel).filter(SessionModel.user_id == user.id).delete()
    db.commit()
    response.delete_cookie("mf_token")


@app.get("/api/auth/me", response_model=schemas.UserOut)
def me(user: User = Depends(get_current_user)):
    return user


# ============================================================
# Tipos de juego
# ============================================================

@app.get("/api/game-types")
def list_game_types(user: User = Depends(get_current_user)):
    return [{"id": k, **v} for k, v in GAME_TYPES.items()]


# ============================================================
# Partidas
# ============================================================

def _load_game(db: Session, game_id: int) -> Game:
    game = (
        db.query(Game)
        .options(
            joinedload(Game.participants).joinedload(GameParticipant.user),
            joinedload(Game.buyins).joinedload(BuyIn.user),
            joinedload(Game.admin),
            joinedload(Game.winner),
        )
        .filter(Game.id == game_id)
        .first()
    )
    if not game:
        raise HTTPException(404, "Partida no encontrada")
    return game


def _sorted_game(game: Game) -> Game:
    game.participants.sort(
        key=lambda p: (
            p.position is not None,
            p.position or 0,
            p.user.username.lower(),
        )
    )
    game.buyins.sort(key=lambda b: b.requested_at, reverse=True)
    return game


def _require_admin(game: Game, user: User):
    if game.admin_id != user.id:
        raise HTTPException(403, "Solo el administrador de la partida puede hacer esto")


def _participant_of(game: Game, user_id: int) -> GameParticipant | None:
    return next((p for p in game.participants if p.user_id == user_id), None)


@app.get("/api/games", response_model=list[schemas.GameOut])
def list_games(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        db.query(Game)
        .options(
            joinedload(Game.participants).joinedload(GameParticipant.user),
            joinedload(Game.buyins).joinedload(BuyIn.user),
            joinedload(Game.admin),
            joinedload(Game.winner),
        )
        .order_by(Game.created_at.desc())
    )
    if status:
        q = q.filter(Game.status.in_(status.split(",")))
    return [_sorted_game(g) for g in q.all()]


@app.get("/api/games/{game_id}", response_model=schemas.GameOut)
def get_game(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games", response_model=schemas.GameOut, status_code=201)
def create_game(
    payload: schemas.GameCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    gtype = GAME_TYPES.get(payload.game_type)
    if not gtype:
        raise HTTPException(400, f"Tipo de juego desconocido: {payload.game_type}")
    if not gtype["available"]:
        raise HTTPException(400, f"El modo «{gtype['label']}» todavía no está disponible")

    active = db.query(Game).filter(Game.status.in_(["open", "in_progress"])).first()
    if active:
        raise HTTPException(
            400,
            f"Ya hay una partida activa (#{active.id}). Terminala o cancelala primero.",
        )

    game = Game(
        game_type=payload.game_type,
        status="open",
        admin_id=user.id,
        buy_in_amount=payload.buy_in_amount,
    )
    db.add(game)
    db.flush()

    # El creador queda anotado automaticamente
    db.add(GameParticipant(game_id=game.id, user_id=user.id))
    db.commit()
    return _sorted_game(_load_game(db, game.id))


@app.post("/api/games/{game_id}/join", response_model=schemas.GameOut)
def join_game(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    if game.status != "open":
        raise HTTPException(400, "La partida ya arrancó, no se puede entrar")
    if _participant_of(game, user.id):
        raise HTTPException(400, "Ya estás anotado en esta partida")

    db.add(GameParticipant(game_id=game.id, user_id=user.id))
    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games/{game_id}/unjoin", response_model=schemas.GameOut)
def unjoin_game(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    if game.status != "open":
        raise HTTPException(400, "La partida ya arrancó")
    if game.admin_id == user.id:
        raise HTTPException(400, "El administrador no puede bajarse: cancelá la partida")

    part = _participant_of(game, user.id)
    if not part:
        raise HTTPException(400, "No estás anotado en esta partida")

    db.delete(part)
    db.query(BuyIn).filter(
        BuyIn.game_id == game_id, BuyIn.user_id == user.id
    ).delete()
    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games/{game_id}/start", response_model=schemas.GameOut)
def start_game(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    _require_admin(game, user)
    if game.status != "open":
        raise HTTPException(400, "La partida ya arrancó")

    min_players = GAME_TYPES[game.game_type]["min_players"]
    if len(game.participants) < min_players:
        raise HTTPException(400, f"Se necesitan al menos {min_players} jugadores")

    game.status = "in_progress"
    game.started_at = utcnow()
    db.commit()
    return _sorted_game(_load_game(db, game_id))


# ---------------- Cajas (buy-ins) ----------------

@app.post("/api/games/{game_id}/buyins", response_model=schemas.GameOut, status_code=201)
def request_buyin(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    if game.status not in ("open", "in_progress"):
        raise HTTPException(400, "La partida ya terminó")

    part = _participant_of(game, user.id)
    if not part:
        raise HTTPException(400, "No estás en esta partida")
    if part.position is not None:
        raise HTTPException(400, "Ya saliste de la partida, no podés pedir caja")

    pending = any(
        b.user_id == user.id and b.status == "pending" for b in game.buyins
    )
    if pending:
        raise HTTPException(400, "Ya tenés una caja pendiente de aprobación")

    db.add(BuyIn(game_id=game.id, user_id=user.id))
    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games/{game_id}/buyins/{buyin_id}/approve", response_model=schemas.GameOut)
def approve_buyin(
    game_id: int,
    buyin_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    _require_admin(game, user)

    buyin = next((b for b in game.buyins if b.id == buyin_id), None)
    if not buyin:
        raise HTTPException(404, "Caja no encontrada")
    if buyin.status != "pending":
        raise HTTPException(400, "Esa caja ya fue resuelta")

    buyin.status = "approved"
    buyin.resolved_at = utcnow()
    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games/{game_id}/buyins/{buyin_id}/reject", response_model=schemas.GameOut)
def reject_buyin(
    game_id: int,
    buyin_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    _require_admin(game, user)

    buyin = next((b for b in game.buyins if b.id == buyin_id), None)
    if not buyin:
        raise HTTPException(404, "Caja no encontrada")
    if buyin.status != "pending":
        raise HTTPException(400, "Esa caja ya fue resuelta")

    buyin.status = "rejected"
    buyin.resolved_at = utcnow()
    db.commit()
    return _sorted_game(_load_game(db, game_id))


# ---------------- Retiros y eliminaciones ----------------

@app.post("/api/games/{game_id}/exit-request", response_model=schemas.GameOut)
def request_exit(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    if game.status != "in_progress":
        raise HTTPException(400, "La partida no está en curso")

    part = _participant_of(game, user.id)
    if not part:
        raise HTTPException(400, "No estás en esta partida")
    if part.position is not None:
        raise HTTPException(400, "Ya saliste de la partida")
    if part.exit_requested:
        raise HTTPException(400, "Ya pediste retirarte; esperá al administrador")

    part.exit_requested = True
    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games/{game_id}/exit-request/cancel", response_model=schemas.GameOut)
def cancel_exit(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    part = _participant_of(game, user.id)
    if not part or not part.exit_requested:
        raise HTTPException(400, "No tenés un retiro pendiente")

    part.exit_requested = False
    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games/{game_id}/eliminate", response_model=schemas.GameOut)
def eliminate(
    game_id: int,
    payload: schemas.EliminateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    _require_admin(game, user)
    if game.status != "in_progress":
        raise HTTPException(400, "La partida no está en curso")

    part = _participant_of(game, payload.user_id)
    if not part:
        raise HTTPException(400, "Ese jugador no está en la partida")
    if part.position is not None:
        raise HTTPException(400, "Ese jugador ya salió de la partida")

    alive = [p for p in game.participants if p.position is None]

    part.position = len(alive)
    part.eliminated_at = utcnow()
    part.exit_requested = False

    remaining = [p for p in alive if p.id != part.id]
    if len(remaining) == 1:
        champion = remaining[0]
        champion.position = 1
        champion.exit_requested = False
        game.status = "finished"
        game.finished_at = utcnow()
        game.winner_id = champion.user_id

    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.post("/api/games/{game_id}/undo", response_model=schemas.GameOut)
def undo_last(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = _load_game(db, game_id)
    _require_admin(game, user)
    if game.status == "cancelled":
        raise HTTPException(400, "La partida fue cancelada")

    eliminated = [p for p in game.participants if p.eliminated_at is not None]
    if not eliminated:
        raise HTTPException(400, "No hay salidas para deshacer")

    last = max(eliminated, key=lambda p: p.eliminated_at)

    if game.status == "finished":
        for p in game.participants:
            if p.position == 1:
                p.position = None
        game.status = "in_progress"
        game.finished_at = None
        game.winner_id = None

    last.position = None
    last.eliminated_at = None

    db.commit()
    return _sorted_game(_load_game(db, game_id))


@app.delete("/api/games/{game_id}", status_code=204)
def cancel_or_delete_game(
    game_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(404, "Partida no encontrada")
    if game.admin_id != user.id:
        raise HTTPException(403, "Solo el administrador de la partida puede hacer esto")

    if game.status in ("open", "in_progress"):
        game.status = "cancelled"
        game.finished_at = utcnow()
        db.commit()
    else:
        db.delete(game)
        db.commit()


# ============================================================
# Estadisticas
# ============================================================

@app.get("/api/stats", response_model=schemas.StatsOut)
def get_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    finished = (
        db.query(Game)
        .options(
            joinedload(Game.participants).joinedload(GameParticipant.user),
            joinedload(Game.buyins),
        )
        .filter(Game.status == "finished")
        .order_by(Game.finished_at.desc())
        .all()
    )

    users = db.query(User).all()
    by_user = {
        u.id: {
            "user": u,
            "games_played": 0,
            "wins": 0,
            "podiums": 0,
            "positions": [],
            "results": [],
            "total_buyins": 0,
        }
        for u in users
    }

    for game in finished:
        approved = {}
        for b in game.buyins:
            if b.status == "approved":
                approved[b.user_id] = approved.get(b.user_id, 0) + 1
        for part in game.participants:
            row = by_user.get(part.user_id)
            if row is None:
                continue
            row["games_played"] += 1
            row["total_buyins"] += approved.get(part.user_id, 0)
            if part.position:
                row["positions"].append(part.position)
                if part.position == 1:
                    row["wins"] += 1
                if part.position <= 3:
                    row["podiums"] += 1
                row["results"].append(part.position == 1)

    leaderboard = []
    for row in by_user.values():
        streak = 0
        for won in row["results"]:
            if won:
                streak += 1
            else:
                break
        gp = row["games_played"]
        leaderboard.append(
            schemas.PlayerStats(
                user=schemas.UserOut.model_validate(row["user"]),
                games_played=gp,
                wins=row["wins"],
                podiums=row["podiums"],
                win_rate=round(row["wins"] / gp, 3) if gp else 0.0,
                avg_position=(
                    round(sum(row["positions"]) / len(row["positions"]), 2)
                    if row["positions"]
                    else None
                ),
                current_streak=streak,
                total_buyins=row["total_buyins"],
            )
        )

    leaderboard.sort(
        key=lambda s: (-s.wins, -s.win_rate, s.avg_position or 99, s.user.username.lower())
    )

    return schemas.StatsOut(leaderboard=leaderboard, total_games=len(finished))


# ============================================================
# Frontend
# ============================================================

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("static/index.html")
