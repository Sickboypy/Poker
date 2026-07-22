"""
Almacenamiento de fotos en Google Cloud Storage.

Las fotos se guardan en un bucket privado. Para mostrarlas generamos URLs
firmadas de corta duración, así el bucket nunca queda público pero los
jugadores pueden ver las fotos desde su teléfono.

El nombre del bucket se toma de la variable de entorno PHOTOS_BUCKET.
Si no está seteada, la subida de fotos queda deshabilitada (la app sigue
funcionando normalmente para todo lo demás).
"""

import os
import uuid
from datetime import timedelta

_bucket_name = os.environ.get("PHOTOS_BUCKET")
_client = None
_bucket = None


def enabled() -> bool:
    return bool(_bucket_name)


def _get_bucket():
    global _client, _bucket
    if _bucket is None:
        from google.cloud import storage
        _client = storage.Client()
        _bucket = _client.bucket(_bucket_name)
    return _bucket


ALLOWED_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}

MAX_BYTES = 10 * 1024 * 1024  # 10 MB por foto


def upload_photo(game_id: int, data: bytes, content_type: str) -> str:
    """Sube una foto y devuelve el nombre del objeto (blob) en el bucket."""
    ext = ALLOWED_TYPES.get(content_type, "jpg")
    blob_name = f"games/{game_id}/{uuid.uuid4().hex}.{ext}"
    blob = _get_bucket().blob(blob_name)
    blob.upload_from_string(data, content_type=content_type)
    return blob_name


def signed_url(blob_name: str, minutes: int = 60) -> str:
    """URL temporal para ver la foto sin exponer el bucket."""
    blob = _get_bucket().blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=minutes),
        method="GET",
    )


def delete_photo(blob_name: str) -> None:
    try:
        _get_bucket().blob(blob_name).delete()
    except Exception:
        pass  # si ya no existe, no pasa nada
