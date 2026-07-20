# Configurar Firestore en Cloud Run

Guía para conectar la app a Firestore (datos persistentes) y dejar listo GCS
para las fotos de más adelante. Reemplazá `TU_PROYECTO` y `TU_SERVICIO` por
los tuyos, y `REGION` por la que uses (ej: `southamerica-east1`).

## 1. Habilitar las APIs

```bash
gcloud services enable firestore.googleapis.com storage.googleapis.com \
  --project TU_PROYECTO
```

## 2. Crear la base de datos Firestore

Firestore tiene dos modos; usá **Native mode** (el que sirve para apps).
Se crea una sola vez por proyecto:

```bash
gcloud firestore databases create \
  --location=REGION \
  --project TU_PROYECTO
```

> Si te dice que ya existe una base en modo Datastore, tenés que usar un
> proyecto nuevo para Firestore Native, o crear una base con `--database` nombrada.
> Para un proyecto nuevo esto no pasa.

## 3. Darle permiso a Cloud Run para usar Firestore

Cloud Run corre con una cuenta de servicio. Hay que darle el rol de usuario de Firestore.

Averiguá qué cuenta usa tu servicio:

```bash
gcloud run services describe TU_SERVICIO \
  --region REGION --project TU_PROYECTO \
  --format="value(spec.template.spec.serviceAccountName)"
```

Si sale vacío, usa la cuenta por defecto de Compute:
`NUMERO-compute@developer.gserviceaccount.com` (el NÚMERO lo ves con
`gcloud projects describe TU_PROYECTO --format="value(projectNumber)"`).

Dale los roles (a la cuenta que corresponda):

```bash
CUENTA="LA_CUENTA_DE_ARRIBA"

gcloud projects add-iam-policy-binding TU_PROYECTO \
  --member="serviceAccount:${CUENTA}" \
  --role="roles/datastore.user"

# Para las fotos (GCS), más adelante:
gcloud projects add-iam-policy-binding TU_PROYECTO \
  --member="serviceAccount:${CUENTA}" \
  --role="roles/storage.objectAdmin"
```

La librería detecta el proyecto sola dentro de Cloud Run (no hace falta
pasar credenciales ni variables de entorno). `firestore.Client()` simplemente
funciona.

## 4. Probar en local (opcional)

Para correr la app en tu compu apuntando al Firestore real:

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=TU_PROYECTO
uvicorn app.main:app --reload
```

Esto usa tus credenciales de gcloud. Ojo: escribe en la base de verdad.

## 5. Deploy

No cambia nada de tu pipeline actual. Hacés commit desde GitHub Desktop y
tu CI/CD reconstruye y despliega como siempre. La diferencia es que ahora
los datos viven en Firestore, así que **sobreviven a los reinicios del
contenedor**: podés no usar la app por horas y al volver está todo.

## Costos

Para un grupo de amigos jugando al póquer, el uso entra de sobra en la
**capa gratuita** de Firestore (50k lecturas y 20k escrituras por día).
No deberías pagar nada.

---

## Cómo quedaron guardados los datos

- `users/{username}` — un documento por jugador
- `sessions/{token}` — sesiones de login
- `games/{id}` — cada partida con sus participantes y cajas embebidos
  (toda la noche en un solo documento, para que las eliminaciones y cajas
  sean atómicas aunque varios toquen la app a la vez)
- `counters/{users|games}` — para mantener los ids cortos (1, 2, 3...)

Podés ver y editar todo esto a mano desde la consola web de Firestore.
