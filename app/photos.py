"""
Almacenamiento de fotos en Google Cloud Storage.

Las fotos se guardan en un bucket privado. Para mostrarlas generamos URLs
firmadas de corta duracion, asi el bucket nunca queda publico pero los
jugadores pueden ver las fotos desde su telefono.

Firma de URLs en Cloud Run
--------------------------
En Cloud Run las credenciales por defecto son "token-based" (no traen una
clave privada local), asi que la firma normal de URLs falla. La solucion es
firmar usando la API IAM SignBlob: le pasamos a la libreria el email de la
cuenta de servicio y un access token, y ella usa esa API para firmar sin
necesitar la clave privada. Esto requiere el rol
roles/iam.serviceAccountTokenCreator sobre la propia cuenta (ya otorgado).

El nombre del bucket se toma de la variable de entorno PHOTOS_BUCKET.
Si no esta seteada, la subida de fotos queda deshabilitada.
"""

import os
import uuid
from datetime import timedelta

_bucket_name = os.environ.get("PHOTOS_BUCKET")
_client = None
_bucket = None
_signing_email = None
_credentials = None


def enabled() -> bool:
    return bool(_bucket_name)


def _get_bucket():
    global _client, _bucket
    if _bucket is None:
        from google.cloud import storage
        _client = storage.Client()
        _bucket = _client.bucket(_bucket_name)
    return _bucket


def _signing_context():
    """
    Devuelve (service_account_email, access_token) para firmar via IAM SignBlob.
    El token se refresca en cada uso porque es de corta vida.
    """
    global _signing_email, _credentials
    import google.auth
    from google.auth.transport import requests as gauth_requests

    if _credentials is None:
        _credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    _credentials.refresh(gauth_requests.Request())

    email = _signing_email
    if email is None:
        email = getattr(_credentials, "service_account_email", None)
        if not email or email == "default":
            email = _fetch_metadata_email() or email
        _signing_email = email

    return email, _credentials.token


def _fetch_metadata_email():
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/"
            "service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.read().decode().strip()
    except Exception:
        return None


ALLOWED_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}

MAX_BYTES = 10 * 1024 * 1024  # 10 MB por foto


def upload_photo(game_id: int, data: bytes, content_type: str) -> str:
    ext = ALLOWED_TYPES.get(content_type, "jpg")
    blob_name = f"games/{game_id}/{uuid.uuid4().hex}.{ext}"
    blob = _get_bucket().blob(blob_name)
    blob.upload_from_string(data, content_type=content_type)
    return blob_name


def signed_url(blob_name: str, minutes: int = 60) -> str:
    blob = _get_bucket().blob(blob_name)
    email, token = _signing_context()
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=minutes),
        method="GET",
        service_account_email=email,
        access_token=token,
    )


def delete_photo(blob_name: str) -> None:
    try:
        _get_bucket().blob(blob_name).delete()
    except Exception:
        pass
