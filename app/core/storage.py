import io
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        _ensure_bucket(_client)
    return _client


def _ensure_bucket(client: Minio) -> None:
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)


async def upload_file(key: str, data: bytes, content_type: str) -> str:
    client = get_client()
    stream = io.BytesIO(data)
    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=key,
        data=stream,
        length=len(data),
        content_type=content_type,
    )
    scheme = "https" if settings.MINIO_SECURE else "http"
    return f"{scheme}://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET}/{key}"


async def download_file(key: str) -> bytes:
    client = get_client()
    response = client.get_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=key,
    )
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def delete_file(key: str) -> None:
    client = get_client()
    try:
        client.remove_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=key,
        )
    except S3Error:
        pass


async def get_presigned_url(key: str, expires: int = 3600) -> str:
    client = get_client()
    url = client.presigned_get_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=key,
        expires=timedelta(seconds=expires),
    )
    return url
