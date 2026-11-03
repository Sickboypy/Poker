# Swarm Descent

Shooter espacial de horror en 3D para navegador y VR (Meta Quest), con
cooperativo en red. Se despliega solo en Google Cloud Run cada vez que se
hace push a `main`.

## Cómo jugar

1. Abrí la URL del servicio en el navegador (en el Quest: Meta Quest Browser).
2. Escribí un **código de sala**. Todos los que juegan juntos usan el mismo
   (por ejemplo `chanchito`). Sin código se entra a la sala `publica`.
3. Elegí `swarm_coop.html` y tocá **ENTER VR**.

También se puede compartir el link directo:
`https://LA-URL-DEL-SERVICIO/swarm_coop.html?sala=chanchito`

## Archivos

| Archivo | Para qué |
|---|---|
| `swarm_coop.html` | El juego completo (un solo archivo). |
| `servidor_vr.py` | Sirve el juego y reenvía los mensajes de red entre jugadores. Solo usa la biblioteca estándar de Python. |
| `Dockerfile` / `.dockerignore` | La imagen del contenedor. Solo copia el servidor y los `.html`. |
| `.github/workflows/deploy.yml` | El pipeline: compila la imagen, la sube y despliega en Cloud Run. |

## Despliegue (automático)

Cada push a `main` despliega el servicio `swarm` en `southamerica-east1`
(São Paulo, la región más cercana). Usa la misma autenticación y el mismo
Artifact Registry que tenía la app de póquer: no hay que configurar nada nuevo.

Configuración importante del servicio (está en `deploy.yml`):

- `--timeout 3600`: las conexiones de red duran hasta 60 minutos; después
  Cloud Run las corta y el juego se reconecta solo.
- `--max-instances 1`: las salas viven en la memoria del servidor, así que
  todos los jugadores tienen que caer en la misma instancia.
- `--min-instances 0`: cuando nadie juega, no corre (y no cobra). El primero
  en entrar espera unos segundos mientras arranca.

## Jugar en la red local (sin Cloud Run)

```
python servidor_vr.py
```

Sin la variable `PORT`, el servidor arranca en modo local: HTTPS en el
puerto 8443 con un certificado autofirmado que genera solo la primera vez.
Los visores entran a `https://IP-DE-TU-PC:8443/`.
