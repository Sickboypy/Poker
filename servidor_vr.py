#!/usr/bin/env python3
"""
Servidor HTTPS + WebSocket para jugar Swarm Descent en VR, solo o en red.
Funciona igual en tu PC (modo local) y en Google Cloud Run (modo nube):
si existe la variable de entorno PORT (Cloud Run la define) escucha en HTTP
plano en ese puerto, porque Cloud Run ya pone el HTTPS con certificado válido.

- Sirve los .html de esta carpeta (WebXR exige HTTPS).
- En /ws reenvía mensajes en tiempo real entre los jugadores conectados
  (cooperativo). Todo en el MISMO puerto, así el certificado se acepta una
  sola vez por visor.
- El certificado autofirmado se genera solo la primera vez (sin openssl).

USO:
    1) Poné este archivo en la MISMA carpeta que los .html del juego.
    2) Ejecutá:   python servidor_vr.py
    3) En cada visor (Quest 3, Quest 2...) abrí el navegador y entrá a la
       dirección que muestra la consola, por ejemplo:
           https://192.168.1.50:8443/
       Ahí aparece la lista de juegos: elegí swarm_coop.html para jugar en red.
    4) El navegador avisa que el certificado no es de confianza:
       Avanzado -> Continuar (es tu propio certificado).
    5) Tocá "ENTER VR".

La PC y los visores tienen que estar en la MISMA red WiFi.
"""

import asyncio
import base64
import datetime
import hashlib
import html
import json
import mimetypes
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import urllib.parse

PORT = 8443
BASE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
CERT = os.path.join(BASE, "vr_cert.pem")
KEY = os.path.join(BASE, "vr_key.pem")
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MSG = 64 * 1024            # tamaño máximo de un mensaje de juego
IDLE_TIMEOUT = 30              # s sin mensajes → se considera desconectado
BLOCKED_EXT = (".pem", ".py", ".pyc", ".key")   # nunca servir la clave privada ni el código


# ---------------------------------------------------------------------------
#  Certificado
# ---------------------------------------------------------------------------
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_cryptography():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        print("Falta la libreria 'cryptography'. Intentando instalarla...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "cryptography"], check=True)
            import cryptography  # noqa: F401
            return True
        except Exception as e:
            print("\nNo pude instalar 'cryptography' automaticamente: %s" % e)
            print("Instalala a mano con:\n    %s -m pip install cryptography" % sys.executable)
            return False


def make_cert(ip):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import ipaddress

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "swarm-vr")])
    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
    try:
        san.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
    except Exception:
        pass
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )
    with open(KEY, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    with open(CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def ensure_cert(ip):
    if os.path.exists(CERT) and os.path.exists(KEY):
        return True
    if not ensure_cryptography():
        return False
    print("Generando certificado autofirmado (solo la primera vez)...")
    try:
        make_cert(ip)
        return True
    except Exception as e:
        print("\nERROR generando el certificado: %s" % e)
        return False


# ---------------------------------------------------------------------------
#  WebSocket (RFC 6455, lo mínimo necesario)
# ---------------------------------------------------------------------------
def ws_frame(data, op=1):
    n = len(data)
    if n < 126:
        hdr = struct.pack("!BB", 0x80 | op, n)
    elif n < 65536:
        hdr = struct.pack("!BBH", 0x80 | op, 126, n)
    else:
        hdr = struct.pack("!BBQ", 0x80 | op, 127, n)
    return hdr + data


async def read_frame(reader):
    h = await reader.readexactly(2)
    fin, op = h[0] & 0x80, h[0] & 0x0F
    masked, ln = h[1] & 0x80, h[1] & 0x7F
    if ln == 126:
        ln = struct.unpack("!H", await reader.readexactly(2))[0]
    elif ln == 127:
        ln = struct.unpack("!Q", await reader.readexactly(8))[0]
    if ln > MAX_MSG:
        raise ValueError("mensaje demasiado grande")
    mask = await reader.readexactly(4) if masked else None
    data = await reader.readexactly(ln) if ln else b""
    if mask and ln:
        m = (mask * (ln // 4 + 1))[:ln]
        data = (int.from_bytes(data, "big") ^ int.from_bytes(m, "big")).to_bytes(ln, "big")
    return bool(fin), op, data


# ---------------------------------------------------------------------------
#  Salas de juego: cada código de sala (?sala=...) es una partida aparte, con
#  sus propios ids y su anfitrión. Sin código se entra a la sala "publica".
# ---------------------------------------------------------------------------
rooms = {}         # nombre -> {"clients": {id: StreamWriter}, "host": id, "ff": bool}
next_id = 1
ROOM_RE = re.compile(r"^[a-z0-9_-]{1,24}$")


def room_name(query):
    raw = (urllib.parse.parse_qs(query).get("sala") or ["publica"])[0].strip().lower()
    return raw if ROOM_RE.match(raw) else None


def map_choice(query):
    # mapa de la sala: lo fija el que la CREA (1 = El Descenso, 2 = La Colmena)
    raw = (urllib.parse.parse_qs(query).get("mapa") or ["1"])[0]
    return 2 if raw == "2" else 1


def friendly_fire(query):
    # fuego amigo: lo decide el que CREA la sala (los que entran después heredan)
    return (urllib.parse.parse_qs(query).get("ff") or ["0"])[0] == "1"


def send(writer, obj):
    try:
        writer.write(ws_frame(json.dumps(obj, separators=(",", ":")).encode()))
    except Exception:
        pass


def broadcast(room, obj, exclude=None):
    data = ws_frame(json.dumps(obj, separators=(",", ":")).encode())
    for cid, w in list(room["clients"].items()):
        if cid == exclude:
            continue
        # cliente que no lee (visor dormido): no dejamos que acumule memoria
        if w.transport.get_write_buffer_size() > 1_000_000:
            w.close()
            continue
        try:
            w.write(data)
        except Exception:
            pass


async def ws_session(reader, writer, name, ff=False, mapa=1):
    global next_id
    room = rooms.setdefault(name, {"clients": {}, "host": None, "ff": ff, "mapa": mapa})
    clients = room["clients"]
    cid = next_id
    next_id += 1
    clients[cid] = writer
    if room["host"] is None:
        room["host"] = cid
    send(writer, {"t": "welcome", "id": cid, "host": room["host"], "n": len(clients), "sala": name, "ff": room["ff"], "mapa": room["mapa"]})
    broadcast(room, {"t": "join", "id": cid, "n": len(clients)}, exclude=cid)
    print("  [%s] Jugador %d conectado (%d en la sala)%s%s" % (name, cid, len(clients), " [anfitrion]" if room["host"] == cid else "",
                                                            " [fuego amigo]" if room["ff"] and len(clients) == 1 else ""), flush=True)
    frag, frag_op = None, None
    try:
        while True:
            fin, op, data = await asyncio.wait_for(read_frame(reader), IDLE_TIMEOUT)
            if op == 0x8:                                   # cierre
                try:
                    writer.write(ws_frame(b"", 0x8))
                except Exception:
                    pass
                break
            if op == 0x9:                                   # ping → pong
                writer.write(ws_frame(data, 0xA))
                continue
            if op == 0x0:                                   # continuación
                if frag is None:
                    continue
                frag += data
                if not fin:
                    continue
                op, data, frag = frag_op, frag, None
            elif op in (0x1, 0x2) and not fin:
                frag, frag_op = data, op
                continue
            if op != 0x1:
                continue
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            if not isinstance(msg, dict) or not isinstance(msg.get("t"), str) or msg["t"] == "hello":
                continue
            msg["id"] = cid                                 # quién lo mandó (no se puede falsificar)
            if msg["t"] == "ff":                            # fuego amigo: solo lo cambia el anfitrión
                if cid != room["host"]:
                    continue
                room["ff"] = bool(msg.get("on"))
                msg = {"t": "ff", "on": 1 if room["ff"] else 0, "id": cid}
            broadcast(room, msg, exclude=cid)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ssl.SSLError, OSError, ValueError):
        pass
    finally:
        clients.pop(cid, None)
        if room["host"] == cid:
            room["host"] = min(clients) if clients else None
        broadcast(room, {"t": "leave", "id": cid, "host": room["host"], "n": len(clients)})
        if not clients:
            rooms.pop(name, None)                           # sala vacía: se borra
        print("  [%s] Jugador %d desconectado (%d en la sala)" % (name, cid, len(clients)), flush=True)
        try:
            writer.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  HTTP: archivos del juego + índice
# ---------------------------------------------------------------------------
def http_response(writer, code, reason, body=b"", ctype="text/plain; charset=utf-8", head_only=False):
    hdr = ("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
           "Cache-Control: no-store\r\nConnection: close\r\n\r\n" % (code, reason, ctype, len(body)))
    writer.write(hdr.encode() + (b"" if head_only else body))


def index_page():
    games = sorted(f for f in os.listdir(BASE) if f.lower().endswith(".html"))
    items = "".join('<li><a class=g data-f="%s" href="/%s">%s</a></li>' % (html.escape(g), urllib.parse.quote(g), html.escape(g)) for g in games)
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Swarm Descent</title><style>body{background:#05060f;color:#cfe;font:20px monospace;padding:24px}"
            "a{color:#36f9f6;display:block;padding:14px 0}li{list-style:none}"
            "input{font:22px monospace;padding:10px;width:12em;background:#0d1422;color:#fff;border:1px solid #36f9f6}</style>"
            "<h1>Swarm Descent</h1>"
            "<p>Codigo de sala (el mismo para todos los que juegan juntos):<br><input id=sala maxlength=24 placeholder=publica></p>"
            "<p><label><input type=checkbox id=ff style='width:auto;transform:scale(1.6);margin-right:12px'>Fuego amigo"
            " <small>(también se cambia adentro del juego con la tecla G)</small></label></p>"
            "<p>Elegi un juego (swarm_coop.html = en red):</p><ul>%s</ul>"
            "<script>const i=document.getElementById('sala'),ff=document.getElementById('ff');"
            "try{i.value=localStorage.getItem('sala')||'';ff.checked=localStorage.getItem('ff')==='1'}catch(e){}"
            "const up=()=>{const v=i.value.trim().toLowerCase().replace(/[^a-z0-9_-]/g,'').slice(0,24);"
            "try{localStorage.setItem('sala',v);localStorage.setItem('ff',ff.checked?'1':'0')}catch(e){}"
            "const q=[];if(v)q.push('sala='+v);if(ff.checked)q.push('ff=1');"
            "document.querySelectorAll('a.g').forEach(a=>{a.href='/'+encodeURIComponent(a.dataset.f)+(q.length?'?'+q.join('&'):'')})};"
            "i.addEventListener('input',up);ff.addEventListener('change',up);up();</script>" % items).encode()


async def handle(reader, writer):
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
    except Exception:
        writer.close()
        return
    try:
        lines = head.decode("latin-1").split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        parts = urllib.parse.urlsplit(target)
        path = urllib.parse.unquote(parts.path)

        if path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
            name = room_name(parts.query)
            if name is None:
                http_response(writer, 400, "Bad Request", b"codigo de sala invalido")
                await writer.drain()
                return
            key = headers.get("sec-websocket-key", "")
            accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
            writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
            await ws_session(reader, writer, name, friendly_fire(parts.query), map_choice(parts.query))
            return

        head_only = method == "HEAD"
        if method not in ("GET", "HEAD"):
            http_response(writer, 405, "Method Not Allowed", b"405")
        elif path in ("/", "/index.html") and not os.path.exists(os.path.join(BASE, "index.html")):
            http_response(writer, 200, "OK", index_page(), "text/html; charset=utf-8", head_only)
        else:
            full = os.path.realpath(os.path.join(BASE, path.lstrip("/")))
            inside = full.startswith(BASE + os.sep)
            if not inside or not os.path.isfile(full) or full.lower().endswith(BLOCKED_EXT):
                http_response(writer, 404, "Not Found", b"404", head_only=head_only)
            else:
                with open(full, "rb") as f:
                    body = f.read()
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                    ctype += "; charset=utf-8"
                http_response(writer, 200, "OK", body, ctype, head_only)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def quiet_exceptions(loop, context):
    # Los visores rechazan el certificado autofirmado hasta que lo aceptás:
    # esos errores de handshake son normales y no hace falta mostrarlos.
    exc = context.get("exception")
    if isinstance(exc, (ssl.SSLError, ConnectionError, OSError)):
        return
    loop.default_exception_handler(context)


async def main_async(ip):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=CERT, keyfile=KEY)
    asyncio.get_running_loop().set_exception_handler(quiet_exceptions)
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, ssl=ctx)

    print("\n" + "=" * 60)
    print("  SERVIDOR VR LISTO (un jugador o cooperativo en red)")
    print("=" * 60)
    print("  En cada visor (Meta Quest Browser), entra a:")
    print("\n     https://%s:%d/\n" % (ip, PORT))
    print("  y elegi el juego. Para jugar en red: swarm_coop.html")
    print("  (en esta PC:  https://localhost:%d/ )" % PORT)
    print("  El navegador avisara del certificado: Avanzado -> Continuar.")
    print("  Corta el servidor con Ctrl+C.")
    print("=" * 60 + "\n")
    async with server:
        while True:                  # despertar seguido: Ctrl+C responde en Windows
            await asyncio.sleep(0.5)


async def main_cloud(port):
    # Cloud Run: HTTP plano (el HTTPS lo pone Google), puerto de $PORT
    asyncio.get_running_loop().set_exception_handler(quiet_exceptions)
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    print("Swarm Descent escuchando en el puerto %d (modo nube)" % port, flush=True)
    async with server:
        await server.serve_forever()


def main():
    os.chdir(BASE)
    mimetypes.add_type("text/javascript", ".js")
    if os.environ.get("PORT"):
        asyncio.run(main_cloud(int(os.environ["PORT"])))
        return
    ip = get_local_ip()
    if not ensure_cert(ip):
        sys.exit(1)
    mimetypes.add_type("text/javascript", ".js")
    try:
        asyncio.run(main_async(ip))
    except KeyboardInterrupt:
        print("\nServidor detenido.")


if __name__ == "__main__":
    main()
