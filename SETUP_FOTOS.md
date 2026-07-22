# Configurar las fotos (Google Cloud Storage)

La app guarda las fotos de cada partida en un bucket privado de GCS y las
muestra con URLs firmadas temporales (el bucket nunca queda público).

Los permisos ya los diste antes (`roles/storage.objectAdmin` a la cuenta de
Cloud Run). Falta crear el bucket y decirle a la app cómo se llama.
Reemplazá `TU_PROYECTO` por tu Project ID.

## 1. Elegí un nombre único de bucket

Los nombres de bucket son únicos a nivel mundial. Usá algo como:
`poker-highlander-fotos-TU_PROYECTO` (poné tu proyecto para que sea único).

## 2. Crear el bucket (en tu región)

```bash
gcloud storage buckets create gs://poker-highlander-fotos-TU_PROYECTO \
  --location=us-central1 \
  --uniform-bucket-level-access
```

## 3. Decirle a la app el nombre del bucket

La app lee el bucket de la variable de entorno PHOTOS_BUCKET. La seteamos
en el servicio de Cloud Run (sin el prefijo `gs://`):

```bash
gcloud run services update poker \
  --region us-central1 \
  --update-env-vars PHOTOS_BUCKET=poker-highlander-fotos-TU_PROYECTO
```

Cloud Run va a reiniciar el servicio con la variable nueva. Listo: a partir de
ahí aparece el botón de subir fotos.

## 4. (Importante) Firma de URLs en Cloud Run

Para generar las URLs firmadas, la cuenta de servicio necesita poder "firmar".
Dale este rol una vez (reemplazá NUMERO por el número de proyecto que ya usaste,
1085237925702 en tu caso):

```bash
gcloud iam service-accounts add-iam-policy-binding \
  NUMERO-compute@developer.gserviceaccount.com \
  --member="serviceAccount:NUMERO-compute@developer.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

Si en algún momento las fotos no cargan (error al generar el link), casi
siempre es por esto: ese rol faltante.

## Notas

- Si NO configurás el bucket, la app funciona igual en todo lo demás; solo
  que el botón de subir foto avisa que no está disponible.
- Formatos aceptados: JPG, PNG, WEBP, HEIC. Máximo 10 MB por foto.
- Las fotos se pueden subir durante la partida o después, desde el detalle
  de la partida en el Historial.
- Quien sube una foto (o el superadmin) puede borrarla.
- Costo: para un grupo de amigos, entra en la capa gratuita de GCS.
