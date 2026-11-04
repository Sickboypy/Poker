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

**Fuego amigo:** el anfitrión lo prende o apaga cuando quiera: con la
casilla de la pantalla de inicio del juego, la tecla **G**, o el clic del
stick izquierdo en VR. Vale para todos los de la sala, incluidos los que
entren después. También se puede crear la sala con fuego amigo agregando
`&ff=1` al link.

## Mapas

Al entrar, el juego pregunta qué mapa jugar:

- **Mapa 1 · El Descenso:** bajás sala por sala hasta el reactor y la Reina.
- **Mapa 2 · La Colmena:** un pozo central gigante con turbinas giratorias y
  tres ramas que se juegan en el orden que quieras: la Fundición (barriles y
  tanques), el Invernadero (se corta la luz) y la Galería (francotiradores,
  con un Arsenal opcional). Cada rama limpia activa un relé, que frena una
  turbina, y al volver al pozo te espera una oleada mayor. Con los 3 relés se
  abre la membrana del nido, arriba de todo, donde está la Reina.

El link directo con mapa: `swarm_coop.html?sala=chanchito&mapa=2`. En
cooperativo, el mapa lo fija quien crea la sala; si alguien entra con el
otro, el juego lo pasa solo al mapa correcto.

## Cooperativo

- El primero en entrar a la sala es el **anfitrión**: su visor simula los
  enemigos, las salas, los barriles, los rayos del reactor y la Reina. Los
  demás ven exactamente lo mismo y sus disparos cuentan igual.
- Las balas enemigas se simulan en cada visor: esquivar no tiene demora.
- Los enemigos atacan al jugador vivo más cercano (y prefieren al que los
  está lastimando).
- **Salas:** cuando uno entra, la sala se sella y el que quedó afuera aparece
  adentro por una puerta.
- **Caído:** si te destruyen, quedás a la deriva. Tu compañero te revive
  quedándose cerca 3 segundos (volvés con medio casco). Si caen todos, se
  pierde la partida.
- **Pickups:** cada uno tiene su munición; un pickup es del primero que llega
  y desaparece para todos.
- **Fuego amigo** (opcional): la mitad del daño, con un tope de 50 por
  impacto, así nadie cae de un solo tiro.
- Si el anfitrión se va (o Cloud Run corta su conexión a los 60 minutos),
  otro jugador pasa a ser el anfitrión y la partida sigue donde estaba.
- Al terminar, cualquiera reinicia y recargan todos.

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
