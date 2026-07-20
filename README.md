# ♠ Mesa Final — Poker Tracker

Web app multi-usuario para las noches de póquer con amigos, en modalidad
**eliminación directa**: se juega hasta que queda un solo jugador en pie.
Cada jugador entra desde su propio celular con su cuenta.

## Cómo funciona una noche

1. Cada jugador se registra una sola vez (usuario + contraseña + avatar)
2. Alguien crea la partida → queda como **administrador** de esa noche
(puede fijar el valor de la caja para que la app calcule el pozo)
3. Los demás ven la mesa abierta y se **sientan solos**
4. El admin reparte (arranca la partida)
5. Cada jugador pide **cajas (buy-ins)** desde su teléfono; el admin las
aprueba o rechaza; la app registra cuántas lleva cada uno
6. Para salir: el jugador **pide retirarse** (el admin confirma) o el
admin lo **elimina** directamente cuando pierde
7. El último en pie es el **campeón** 👑 (con confeti y fanfarria en
todos los teléfonos)

Las pantallas se sincronizan solas cada pocos segundos.

## Correr localmente

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Desde cada celular en la misma WiFi: `http://IP-DE-TU-PC:8000`
(escribir el `http://` explícito para que el navegador no fuerce HTTPS).

API interactiva: http://localhost:8000/docs

## Estructura

```
app/
  main.py      # API FastAPI + registro de tipos de juego
  auth.py      # Hash de contraseñas (PBKDF2) y sesiones con cookie
  models.py    # User, Session, Game, GameParticipant, BuyIn
  schemas.py   # Schemas Pydantic
  database.py  # Motor SQLite
static/        # Frontend (vanilla JS, mobile-first)
```

## Agregar un tipo de juego nuevo

1. Sumarlo al diccionario `GAME\_TYPES` en `app/main.py` con `available: True`
2. Implementar su lógica de resultado (posiciones / balance / puntos)
3. El frontend lo muestra automáticamente en "Modalidad"
4. CI/CD test2

