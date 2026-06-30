from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.database import create_tables
from app.api.router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(
    title="Async Media Processing Pipeline",
    description=(
        "Upload files (video, image, PDF) and extract metadata asynchronously. "
        "Jobs are queued via ARQ (Redis), processed by workers, and results are "
        "stored in PostgreSQL. Files are kept in MinIO (S3-compatible storage)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
