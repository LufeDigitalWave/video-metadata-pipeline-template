import asyncio
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone

from arq import ArqRedis
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.database import AsyncSessionFactory, update_job, get_job
from app.core import storage


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_video_metadata(path: str) -> dict:
    """Use ffprobe to extract video metadata."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        None,
    )
    fmt = data.get("format", {})

    metadata: dict = {
        "duration_seconds": float(fmt.get("duration", 0)),
        "size_bytes": int(fmt.get("size", 0)),
        "format_name": fmt.get("format_name"),
    }

    if video_stream:
        # fps as fraction string like "30000/1001"
        fps_raw = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = fps_raw.split("/")
            fps = round(int(num) / int(den), 3) if int(den) else 0
        except Exception:
            fps = 0

        metadata["video"] = {
            "codec": video_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": fps,
            "pixel_format": video_stream.get("pix_fmt"),
        }

    if audio_stream:
        metadata["audio"] = {
            "codec": audio_stream.get("codec_name"),
            "channels": audio_stream.get("channels"),
            "sample_rate": audio_stream.get("sample_rate"),
        }

    return metadata


def _extract_image_metadata(path: str) -> dict:
    """Use Pillow to extract image metadata."""
    from PIL import Image

    with Image.open(path) as img:
        exif_data: dict = {}
        try:
            raw_exif = img._getexif()  # type: ignore[attr-defined]
            if raw_exif:
                from PIL.ExifTags import TAGS
                exif_data = {TAGS.get(k, k): str(v) for k, v in raw_exif.items()}
        except Exception:
            pass

        return {
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "format": img.format,
            "size_bytes": os.path.getsize(path),
            "exif": exif_data,
        }


def _extract_pdf_metadata(path: str) -> dict:
    """Use PyMuPDF to extract PDF metadata."""
    import fitz  # type: ignore[import]

    doc = fitz.open(path)
    try:
        meta = doc.metadata or {}
        return {
            "page_count": doc.page_count,
            "title": meta.get("title"),
            "author": meta.get("author"),
            "subject": meta.get("subject"),
            "creator": meta.get("creator"),
            "producer": meta.get("producer"),
            "creation_date": meta.get("creationDate"),
            "modification_date": meta.get("modDate"),
            "encrypted": doc.is_encrypted,
            "size_bytes": os.path.getsize(path),
        }
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# ARQ task
# ---------------------------------------------------------------------------

async def process_media(ctx: dict, job_id: str) -> dict:
    """
    ARQ worker function.

    Lifecycle:
        queued -> processing -> done | failed
    """
    async with AsyncSessionFactory() as db:
        job = await get_job(db, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        await update_job(db, job_id, status="processing")

    # Download file from MinIO to a temporary location
    file_data = await storage.download_file(job.storage_key)

    suffix = f"_{job.filename}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_data)
        tmp_path = tmp.name

    try:
        content_type = job.content_type or ""

        if content_type.startswith("video/"):
            result = await asyncio.get_event_loop().run_in_executor(
                None, _extract_video_metadata, tmp_path
            )
        elif content_type.startswith("image/"):
            result = await asyncio.get_event_loop().run_in_executor(
                None, _extract_image_metadata, tmp_path
            )
        elif content_type == "application/pdf":
            result = await asyncio.get_event_loop().run_in_executor(
                None, _extract_pdf_metadata, tmp_path
            )
        else:
            result = {
                "message": "Unsupported content type — no specific extractor available",
                "content_type": content_type,
                "size_bytes": len(file_data),
            }

        async with AsyncSessionFactory() as db:
            await update_job(
                db,
                job_id,
                status="done",
                result=result,
                completed_at=datetime.now(timezone.utc),
            )

        return result

    except Exception as exc:
        async with AsyncSessionFactory() as db:
            await update_job(
                db,
                job_id,
                status="failed",
                error=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
        raise

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# ARQ WorkerSettings
# ---------------------------------------------------------------------------

class WorkerSettings:
    functions = [process_media]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10
    job_timeout = 300  # 5 minutes per job
