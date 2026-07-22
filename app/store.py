"""
Capa de datos sobre Firestore.

Diseño:
- Colección "users":   documento por usuario (username en minúsculas como id lógico).
- Colección "sessions": token -> user_id.
- Colección "games":   documento por partida, con participantes y buy-ins EMBEBIDOS
  como listas dentro del mismo documento. Esto es clave: una noche de póquer
  entera vive en un solo documento, así las eliminaciones/cajas se resuelven con
  una sola escritura transaccional y nunca hay estados a medias.
- Colección "counters": ids autoincrementales, para mantener los mismos enteros
  cortos (1, 2, 3...) que ya usa el frontend en vez de ids largos de Firestore.

Los objetos que devuelve este módulo son SimpleNamespace anidados, que exponen
los mismos atributos que los viejos modelos SQLAlchemy (.participants, .user.username,
.position, .eliminated_at, etc.). Así main.py y el frontend no cambian.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from google.cloud import firestore


def utcnow():
    return datetime.now(timezone.utc)


def _to_dt(value):
    """Firestore devuelve datetimes con tz; normalizamos a datetime aware."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return value


class Store:
    def __init__(self, client: firestore.Client | None = None):
        self.db = client or firestore.Client()

    # ---------- ids autoincrementales ----------

    def _next_id(self, name: str) -> int:
        ref = self.db.collection("counters").document(name)

        @firestore.transactional
        def _txn(txn):
            snap = ref.get(transaction=txn)
            current = snap.get("value") if snap.exists else 0
            nxt = (current or 0) + 1
            txn.set(ref, {"value": nxt})
            return nxt

        return _txn(self.db.transaction())

    # ================= Usuarios =================

    def get_user_by_username(self, username: str):
        key = username.strip().lower()
        snap = self.db.collection("users").document(key).get()
        return _user_obj(snap.to_dict()) if snap.exists else None

    def get_user(self, user_id: int):
        docs = (
            self.db.collection("users")
            .where(filter=firestore.FieldFilter("id", "==", user_id))
            .limit(1)
            .stream()
        )
        for d in docs:
            return _user_obj(d.to_dict())
        return None

    def list_users(self):
        return [_user_obj(d.to_dict()) for d in self.db.collection("users").stream()]

    def create_user(self, username: str, password_hash: str, emoji: str, is_super: bool = False):
        key = username.strip().lower()
        ref = self.db.collection("users").document(key)

        @firestore.transactional
        def _txn(txn):
            if ref.get(transaction=txn).exists:
                return None
            uid = self._next_id("users")
            data = {
                "id": uid,
                "username": username.strip(),
                "password_hash": password_hash,
                "emoji": emoji or "🂡",
                "is_super": is_super,
                "created_at": utcnow(),
            }
            txn.set(ref, data)
            return data

        data = _txn(self.db.transaction())
        return _user_obj(data) if data else None

    def update_password(self, username: str, new_hash: str) -> bool:
        key = username.strip().lower()
        ref = self.db.collection("users").document(key)
        snap = ref.get()
        if not snap.exists:
            return False
        ref.set({"password_hash": new_hash}, merge=True)
        return True

    def delete_user(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        if not user:
            return False
        # borrar sesiones del usuario y el documento
        self.delete_user_sessions(user_id)
        self.db.collection("users").document(user.username.lower()).delete()
        return True

    # ================= Sesiones =================

    def create_session(self, token: str, user_id: int):
        self.db.collection("sessions").document(token).set(
            {"user_id": user_id, "created_at": utcnow()}
        )

    def get_session_user(self, token: str):
        snap = self.db.collection("sessions").document(token).get()
        if not snap.exists:
            return None
        return self.get_user(snap.to_dict()["user_id"])

    def delete_user_sessions(self, user_id: int):
        batch = self.db.batch()
        docs = (
            self.db.collection("sessions")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .stream()
        )
        for d in docs:
            batch.delete(d.reference)
        batch.commit()

    # ================= Partidas =================

    def _game_ref(self, game_id: int):
        return self.db.collection("games").document(str(game_id))

    def get_game(self, game_id: int):
        snap = self._game_ref(game_id).get()
        return _game_obj(snap.to_dict()) if snap.exists else None

    def list_games(self, statuses: list[str] | None = None):
        col = self.db.collection("games")
        if statuses:
            docs = col.where(
                filter=firestore.FieldFilter("status", "in", statuses)
            ).stream()
        else:
            docs = col.stream()
        games = [_game_obj(d.to_dict()) for d in docs]
        games.sort(key=lambda g: g.created_at, reverse=True)
        return games

    def find_active_game(self):
        games = self.list_games(["open", "in_progress"])
        return games[0] if games else None

    def create_game(self, game_type, admin, buy_in_amount):
        gid = self._next_id("games")
        data = {
            "id": gid,
            "game_type": game_type,
            "status": "open",
            "buy_in_amount": buy_in_amount,
            "admin": _user_mini(admin),
            "admin_id": admin.id,
            "created_at": utcnow(),
            "started_at": None,
            "finished_at": None,
            "winner": None,
            "winner_id": None,
            "participants": [
                _new_participant(admin)
            ],
            "buyins": [],
            "photos": [],
        }
        self._game_ref(gid).set(data)
        return _game_obj(data)

    def delete_game(self, game_id: int):
        self._game_ref(game_id).delete()

    def update_game(self, game_id: int, mutator):
        """
        Ejecuta `mutator(dict)` sobre el documento de la partida dentro de una
        transacción. El mutator modifica el dict in-place o devuelve un mensaje
        de error (str) para abortar. Devuelve el game_obj actualizado.
        """
        ref = self._game_ref(game_id)

        @firestore.transactional
        def _txn(txn):
            snap = ref.get(transaction=txn)
            if not snap.exists:
                raise LookupError("Partida no encontrada")
            data = snap.to_dict()
            result = mutator(data)
            if isinstance(result, str):
                raise ValueError(result)
            txn.set(ref, data)
            return data

        data = _txn(self.db.transaction())
        return _game_obj(data)


# ---------- helpers de forma de datos ----------

def _user_mini(user):
    """Copia mínima de usuario para embeber en partidas."""
    return {"id": user.id, "username": user.username, "emoji": user.emoji}


def _new_participant(user, role="player"):
    return {
        "user": _user_mini(user),
        "user_id": user.id,
        "position": None,
        "eliminated_at": None,
        "exit_requested": False,
        "role": role,
        "joined_at": utcnow(),
    }


def _user_obj(d):
    if d is None:
        return None
    return SimpleNamespace(
        id=d["id"],
        username=d["username"],
        emoji=d.get("emoji", "🂡"),
        password_hash=d.get("password_hash"),
        is_super=d.get("is_super", False),
        created_at=_to_dt(d.get("created_at")),
    )


def _participant_obj(d):
    return SimpleNamespace(
        user=SimpleNamespace(**d["user"]),
        user_id=d["user_id"],
        position=d.get("position"),
        eliminated_at=_to_dt(d.get("eliminated_at")),
        exit_requested=d.get("exit_requested", False),
        role=d.get("role", "player"),
        joined_at=_to_dt(d.get("joined_at")),
    )


def _buyin_obj(d):
    return SimpleNamespace(
        id=d["id"],
        user=SimpleNamespace(**d["user"]),
        user_id=d["user_id"],
        status=d["status"],
        requested_at=_to_dt(d.get("requested_at")),
        resolved_at=_to_dt(d.get("resolved_at")),
    )


def _game_obj(d):
    if d is None:
        return None
    return SimpleNamespace(
        id=d["id"],
        game_type=d["game_type"],
        status=d["status"],
        buy_in_amount=d.get("buy_in_amount"),
        admin=SimpleNamespace(**d["admin"]),
        admin_id=d["admin_id"],
        created_at=_to_dt(d.get("created_at")),
        started_at=_to_dt(d.get("started_at")),
        finished_at=_to_dt(d.get("finished_at")),
        winner=SimpleNamespace(**d["winner"]) if d.get("winner") else None,
        winner_id=d.get("winner_id"),
        participants=[_participant_obj(p) for p in d.get("participants", [])],
        buyins=[_buyin_obj(b) for b in d.get("buyins", [])],
        photos=[_photo_obj(p) for p in d.get("photos", [])],
    )


def _photo_obj(d):
    return SimpleNamespace(
        id=d["id"],
        blob=d["blob"],
        user=SimpleNamespace(**d["user"]),
        user_id=d["user_id"],
        uploaded_at=_to_dt(d.get("uploaded_at")),
    )
