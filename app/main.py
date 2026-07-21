from datetime import datetime, timezone
import os

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import schemas
from .auth import (
    get_current_user,
    get_store,
    hash_password,
    new_token,
    verify_password,
)
from .store import Store

app = FastAPI(title="Poker Pobre")


SUPERADMIN_USERNAME = "superadmin"
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "Holanda123")


@app.on_event("startup")
def seed_superadmin():
    """Crea el usuario superadmin al arrancar si todavía no existe."""
    store = get_store()
    existing = store.get_user_by_username(SUPERADMIN_USERNAME)
    if existing is None:
        store.create_user(
            username=SUPERADMIN_USERNAME,
            password_hash=hash_password(SUPERADMIN_PASSWORD),
            emoji="👑",
            is_super=True,
        )


def _require_super(user):
    if not getattr(user, "is_super", False):
        raise HTTPException(403, "Solo el superadmin puede hacer esto")


GAME_TYPES = {
    "knockout": {
        "label": "Eliminación directa",
        "description": "Se juega hasta que queda un solo jugador en pie.",
        "min_players": 2,
        "available": True,
    },
    "cash": {
        "label": "Cash game",
        "description": "Póquer tradicional con balance por sesión.",
        "min_players": 2,
        "available": False,
    },
}


def utcnow():
    return datetime.now(timezone.utc)


def _sorted_game(game):
    game.participants.sort(
        key=lambda p: (p.position is not None, p.position or 0, p.user.username.lower())
    )
    game.buyins.sort(key=lambda b: b.requested_at, reverse=True)
    return game


# ============================================================
# Auth
# ============================================================

def _set_session(response: Response, store: Store, user) -> None:
    token = new_token()
    store.create_session(token, user.id)
    response.set_cookie(
        "mf_token", token, httponly=True, samesite="lax",
        secure=True, max_age=60 * 60 * 24 * 90,
    )


@app.post("/api/auth/register", response_model=schemas.UserOut)
def register(payload: schemas.RegisterIn, response: Response, store: Store = Depends(get_store)):
    username = payload.username.strip()
    if not username:
        raise HTTPException(400, "El nombre de usuario no puede estar vacío")

    user = store.create_user(
        username=username,
        password_hash=hash_password(payload.password),
        emoji=payload.emoji or "🂡",
    )
    if user is None:
        raise HTTPException(400, f"El usuario «{username}» ya existe")

    _set_session(response, store, user)
    return user


@app.post("/api/auth/login", response_model=schemas.UserOut)
def login(payload: schemas.LoginIn, response: Response, store: Store = Depends(get_store)):
    user = store.get_user_by_username(payload.username.strip())
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    _set_session(response, store, user)
    return user


@app.post("/api/auth/logout", status_code=204)
def logout(response: Response, store: Store = Depends(get_store), user=Depends(get_current_user)):
    store.delete_user_sessions(user.id)
    response.delete_cookie("mf_token")


@app.get("/api/auth/me", response_model=schemas.UserOut)
def me(user=Depends(get_current_user)):
    return user


@app.post("/api/auth/change-password", status_code=204)
def change_password(payload: schemas.ChangePasswordIn, store: Store = Depends(get_store), user=Depends(get_current_user)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "La contraseña actual no es correcta")
    store.update_password(user.username, hash_password(payload.new_password))


# ============================================================
# Usuarios (lista, administración del superadmin)
# ============================================================

@app.get("/api/users", response_model=list[schemas.UserOut])
def list_users(store: Store = Depends(get_store), user=Depends(get_current_user)):
    users = [u for u in store.list_users() if not getattr(u, "is_super", False)]
    users.sort(key=lambda u: u.username.lower())
    return users


@app.post("/api/users/reset-password", status_code=204)
def reset_password(payload: schemas.ResetPasswordIn, store: Store = Depends(get_store), user=Depends(get_current_user)):
    _require_super(user)
    target = store.get_user(payload.user_id)
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    store.update_password(target.username, hash_password(payload.new_password))


@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    _require_super(user)
    target = store.get_user(user_id)
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    if getattr(target, "is_super", False):
        raise HTTPException(400, "No se puede borrar al superadmin")
    if target.id == user.id:
        raise HTTPException(400, "No podés borrarte a vos mismo")
    store.delete_user(user_id)


# ============================================================
# Tipos de juego
# ============================================================

@app.get("/api/game-types")
def list_game_types(user=Depends(get_current_user)):
    return [{"id": k, **v} for k, v in GAME_TYPES.items()]


# ============================================================
# Partidas
# ============================================================

def _load_game(store: Store, game_id: int):
    game = store.get_game(game_id)
    if not game:
        raise HTTPException(404, "Partida no encontrada")
    return game


def _require_admin(game, user):
    if game.admin_id != user.id:
        raise HTTPException(403, "Solo el administrador de la partida puede hacer esto")


def _run(store: Store, game_id: int, mutator):
    """Ejecuta una mutación transaccional y traduce errores a HTTPException."""
    try:
        return _sorted_game(store.update_game(game_id, mutator))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        if str(e) == "__forbidden__":
            raise HTTPException(403, "Solo el administrador de la partida puede hacer esto")
        raise HTTPException(400, str(e))


@app.get("/api/games", response_model=list[schemas.GameOut])
def list_games(status: str | None = None, store: Store = Depends(get_store), user=Depends(get_current_user)):
    statuses = status.split(",") if status else None
    return [_sorted_game(g) for g in store.list_games(statuses)]


@app.get("/api/games/{game_id}", response_model=schemas.GameOut)
def get_game(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    return _sorted_game(_load_game(store, game_id))


@app.post("/api/games", response_model=schemas.GameOut, status_code=201)
def create_game(payload: schemas.GameCreate, store: Store = Depends(get_store), user=Depends(get_current_user)):
    gtype = GAME_TYPES.get(payload.game_type)
    if not gtype:
        raise HTTPException(400, f"Tipo de juego desconocido: {payload.game_type}")
    if not gtype["available"]:
        raise HTTPException(400, f"El modo «{gtype['label']}» todavía no está disponible")

    if store.find_active_game():
        raise HTTPException(400, "Ya hay una partida activa. Terminala o cancelala primero.")

    game = store.create_game(payload.game_type, user, payload.buy_in_amount)
    return _sorted_game(game)


@app.post("/api/games/{game_id}/join", response_model=schemas.GameOut)
def join_game(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    def mut(g):
        if g["status"] not in ("open", "in_progress"):
            return "La partida ya terminó"
        if any(p["user_id"] == user.id for p in g["participants"]):
            return "Ya estás en esta partida"
        # En lobby entra como jugador; con la partida en curso entra como espectador
        role = "player" if g["status"] == "open" else "spectator"
        g["participants"].append({
            "user": {"id": user.id, "username": user.username, "emoji": user.emoji},
            "user_id": user.id, "position": None, "eliminated_at": None,
            "exit_requested": False, "role": role, "joined_at": utcnow(),
        })
    return _run(store, game_id, mut)


@app.post("/api/games/{game_id}/unjoin", response_model=schemas.GameOut)
def unjoin_game(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    def mut(g):
        if g["status"] != "open":
            return "La partida ya arrancó"
        if g["admin_id"] == user.id:
            return "El administrador no puede bajarse: cancelá la partida"
        if not any(p["user_id"] == user.id for p in g["participants"]):
            return "No estás anotado en esta partida"
        g["participants"] = [p for p in g["participants"] if p["user_id"] != user.id]
        g["buyins"] = [b for b in g["buyins"] if b["user_id"] != user.id]
    return _run(store, game_id, mut)


@app.post("/api/games/{game_id}/start", response_model=schemas.GameOut)
def start_game(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    def mut(g):
        if g["admin_id"] != user.id:
            return "__forbidden__"
        if g["status"] != "open":
            return "La partida ya arrancó"
        if len(g["participants"]) < GAME_TYPES[g["game_type"]]["min_players"]:
            return "Se necesitan al menos 2 jugadores"
        g["status"] = "in_progress"
        g["started_at"] = utcnow()
    return _run(store, game_id, mut)


# ---------------- Cajas (buy-ins) ----------------

@app.post("/api/games/{game_id}/buyins", response_model=schemas.GameOut, status_code=201)
def request_buyin(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    def mut(g):
        if g["status"] not in ("open", "in_progress"):
            return "La partida ya terminó"
        part = next((p for p in g["participants"] if p["user_id"] == user.id), None)
        if not part:
            return "No estás en esta partida"
        if part["position"] is not None:
            return "Ya saliste de la partida, no podés pedir caja"
        if any(b["user_id"] == user.id and b["status"] == "pending" for b in g["buyins"]):
            return "Ya tenés una caja pendiente de aprobación"
        next_id = max([b["id"] for b in g["buyins"]], default=0) + 1
        g["buyins"].append({
            "id": next_id,
            "user": {"id": user.id, "username": user.username, "emoji": user.emoji},
            "user_id": user.id, "status": "pending",
            "requested_at": utcnow(), "resolved_at": None,
        })
    return _run(store, game_id, mut)


def _resolve_buyin(store, game_id, buyin_id, user, new_status):
    def mut(g):
        if g["admin_id"] != user.id:
            return "__forbidden__"
        b = next((x for x in g["buyins"] if x["id"] == buyin_id), None)
        if not b:
            return "__notfound__"
        if b["status"] != "pending":
            return "Esa caja ya fue resuelta"
        b["status"] = new_status
        b["resolved_at"] = utcnow()
        # Al aprobar la caja de un espectador, pasa a jugar la mesa
        if new_status == "approved":
            part = next((p for p in g["participants"] if p["user_id"] == b["user_id"]), None)
            if part and part.get("role") == "spectator" and part["position"] is None:
                part["role"] = "player"
    try:
        return _sorted_game(store.update_game(game_id, mut))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        if str(e) == "__notfound__":
            raise HTTPException(404, "Caja no encontrada")
        if str(e) == "__forbidden__":
            raise HTTPException(403, "Solo el administrador de la partida puede hacer esto")
        raise HTTPException(400, str(e))


@app.post("/api/games/{game_id}/buyins/{buyin_id}/approve", response_model=schemas.GameOut)
def approve_buyin(game_id: int, buyin_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    return _resolve_buyin(store, game_id, buyin_id, user, "approved")


@app.post("/api/games/{game_id}/buyins/{buyin_id}/reject", response_model=schemas.GameOut)
def reject_buyin(game_id: int, buyin_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    return _resolve_buyin(store, game_id, buyin_id, user, "rejected")


# ---------------- Retiros y eliminaciones ----------------

@app.post("/api/games/{game_id}/exit", response_model=schemas.GameOut)
def exit_game(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    """El propio jugador se retira: sale al instante, sin aprobación del admin."""
    def mut(g):
        if g["status"] != "in_progress":
            return "La partida no está en curso"
        part = next((p for p in g["participants"] if p["user_id"] == user.id), None)
        if not part:
            return "No estás en esta partida"
        if part.get("role") == "spectator":
            return "Sos espectador; no estás jugando"
        if part["position"] is not None:
            return "Ya saliste de la partida"

        alive = [p for p in g["participants"]
                 if p["position"] is None and p.get("role", "player") == "player"]
        part["position"] = len(alive)
        part["eliminated_at"] = utcnow()
        part["exit_requested"] = False

        remaining = [p for p in alive if p["user_id"] != part["user_id"]]
        if len(remaining) == 1:
            champ = remaining[0]
            champ["position"] = 1
            champ["exit_requested"] = False
            g["status"] = "finished"
            g["finished_at"] = utcnow()
            g["winner"] = dict(champ["user"])
            g["winner_id"] = champ["user_id"]
    return _run(store, game_id, mut)


@app.post("/api/games/{game_id}/eliminate", response_model=schemas.GameOut)
def eliminate(game_id: int, payload: schemas.EliminateIn, store: Store = Depends(get_store), user=Depends(get_current_user)):
    def mut(g):
        if g["admin_id"] != user.id:
            return "__forbidden__"
        if g["status"] != "in_progress":
            return "La partida no está en curso"
        part = next((p for p in g["participants"] if p["user_id"] == payload.user_id), None)
        if not part:
            return "Ese jugador no está en la partida"
        if part.get("role") == "spectator":
            return "Ese usuario es espectador; todavía no está jugando"
        if part["position"] is not None:
            return "Ese jugador ya salió de la partida"

        # Solo cuentan los jugadores (no los espectadores) que siguen vivos
        alive = [p for p in g["participants"]
                 if p["position"] is None and p.get("role", "player") == "player"]
        part["position"] = len(alive)
        part["eliminated_at"] = utcnow()
        part["exit_requested"] = False

        remaining = [p for p in alive if p["user_id"] != part["user_id"]]
        if len(remaining) == 1:
            champ = remaining[0]
            champ["position"] = 1
            champ["exit_requested"] = False
            g["status"] = "finished"
            g["finished_at"] = utcnow()
            g["winner"] = dict(champ["user"])
            g["winner_id"] = champ["user_id"]
    return _run(store, game_id, mut)


@app.post("/api/games/{game_id}/undo", response_model=schemas.GameOut)
def undo_last(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    def mut(g):
        if g["admin_id"] != user.id:
            return "__forbidden__"
        if g["status"] == "cancelled":
            return "La partida fue cancelada"
        eliminated = [p for p in g["participants"] if p["eliminated_at"] is not None]
        if not eliminated:
            return "No hay salidas para deshacer"
        last = max(eliminated, key=lambda p: p["eliminated_at"])
        if g["status"] == "finished":
            for p in g["participants"]:
                if p["position"] == 1:
                    p["position"] = None
            g["status"] = "in_progress"
            g["finished_at"] = None
            g["winner"] = None
            g["winner_id"] = None
        last["position"] = None
        last["eliminated_at"] = None
    return _run(store, game_id, mut)


@app.delete("/api/games/{game_id}", status_code=204)
def delete_game(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    """Borrar el REGISTRO de una partida: exclusivo del superadmin."""
    game = _load_game(store, game_id)
    _require_super(user)
    store.delete_game(game_id)


@app.post("/api/games/{game_id}/cancel", response_model=schemas.GameOut)
def cancel_game(game_id: int, store: Store = Depends(get_store), user=Depends(get_current_user)):
    """Cancelar una partida en curso: la puede hacer el admin de esa partida."""
    def mut(g):
        if g["admin_id"] != user.id and not getattr(user, "is_super", False):
            return "__forbidden__"
        if g["status"] not in ("open", "in_progress"):
            return "La partida ya terminó"
        g["status"] = "cancelled"
        g["finished_at"] = utcnow()
    return _run(store, game_id, mut)


# ============================================================
# Estadisticas
# ============================================================

@app.get("/api/stats", response_model=schemas.StatsOut)
def get_stats(store: Store = Depends(get_store), user=Depends(get_current_user)):
    finished = [g for g in store.list_games(["finished"])]
    finished.sort(key=lambda g: g.finished_at or g.created_at, reverse=True)

    users = [u for u in store.list_users() if not getattr(u, "is_super", False)]
    by_user = {
        u.id: {
            "user": u, "games_played": 0, "wins": 0, "podiums": 0,
            "positions": [], "results": [], "total_buyins": 0,
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
        leaderboard.append(schemas.PlayerStats(
            user=schemas.UserOut(id=row["user"].id, username=row["user"].username, emoji=row["user"].emoji),
            games_played=gp,
            wins=row["wins"],
            podiums=row["podiums"],
            win_rate=round(row["wins"] / gp, 3) if gp else 0.0,
            avg_position=round(sum(row["positions"]) / len(row["positions"]), 2) if row["positions"] else None,
            current_streak=streak,
            total_buyins=row["total_buyins"],
        ))

    leaderboard.sort(key=lambda s: (-s.wins, -s.win_rate, s.avg_position or 99, s.user.username.lower()))
    return schemas.StatsOut(leaderboard=leaderboard, total_games=len(finished))


# ============================================================
# Frontend
# ============================================================

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("static/index.html")
