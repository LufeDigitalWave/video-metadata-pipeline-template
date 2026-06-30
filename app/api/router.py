import uuid
from typing import Annotated

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db, Job, create_job, get_job, update_job
from app.core import storage

router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    # Video
    "video/mp4", "video/x-msvideo", "video/quicktime",
    "video/x-matroska", "video/webm", "video/mpeg",
    # Image
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/tiff", "image/bmp", "image/svg+xml",
    # Document
    "application/pdf",
}


def _job_to_dict(job: Job) -> dict:
    return {
        "job_id": str(job.id),
        "filename": job.filename,
        "content_type": job.content_type,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "polling_url": f"/jobs/{job.id}",
    }


async def _get_arq_pool():
    return await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    file: Annotated[UploadFile, File(description="File to process (video, image, PDF)")],
    db: AsyncSession = Depends(get_db),
):
    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported content type: {file.content_type}. "
                f"Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
            ),
        )

    # Read and validate file size
    data = await file.read()
    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB} MB.",
        )
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Build a unique storage key
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "bin"
    storage_key = f"{uuid.uuid4()}.{ext}"

    # Upload to MinIO
    await storage.upload_file(storage_key, data, file.content_type)

    # Create job record
    job = await create_job(
        db,
        filename=file.filename or "unnamed",
        storage_key=storage_key,
        content_type=file.content_type,
    )

    # Enqueue ARQ task
    pool = await _get_arq_pool()
    await pool.enqueue_job("process_media", str(job.id))
    await pool.aclose()

    return {
        "job_id": str(job.id),
        "status": job.status,
        "polling_url": f"/jobs/{job.id}",
    }


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid job ID format.")

    job = await get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found.")

    return _job_to_dict(job)


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------

@router.get("/jobs")
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    job_status: str | None = Query(None, alias="status", description="Filter by status"),
):
    offset = (page - 1) * page_size

    query = select(Job)
    count_query = select(func.count()).select_from(Job)

    if job_status:
        query = query.where(Job.status == job_status)
        count_query = count_query.where(Job.status == job_status)

    query = query.order_by(Job.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    jobs = result.scalars().all()

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [_job_to_dict(j) for j in jobs],
    }


# ---------------------------------------------------------------------------
# DELETE /jobs/{job_id}
# ---------------------------------------------------------------------------

@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid job ID format.")

    job = await get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found.")

    # Delete from MinIO
    await storage.delete_file(job.storage_key)

    # Delete DB record
    await db.delete(job)
    await db.commit()

    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
