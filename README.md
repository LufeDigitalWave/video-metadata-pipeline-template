# Async Media Processing Pipeline Template

![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![ARQ](https://img.shields.io/badge/ARQ-async%20jobs-E34F26)
![MinIO](https://img.shields.io/badge/MinIO-S3--compatible-C72E49?logo=minio&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

A production-ready async file processing pipeline built with FastAPI, ARQ (async Redis job queue), MinIO (S3-compatible storage), and PostgreSQL. Upload any supported file via a REST endpoint, have it processed asynchronously by a dedicated worker, and poll for results when ready. The demo use case is **video metadata extraction** (duration, codec, resolution, fps), but the processor is a single function you can swap for any use case: PDF analysis, image classification, audio transcription, document parsing, and more.

---

## Key Features

- **Async job queue** — ARQ + Redis; workers run independently from the API
- **S3-compatible storage** — MinIO stores uploaded files; presigned URLs available
- **Real-time status polling** — `GET /jobs/{id}` returns `queued | processing | done | failed`
- **Multi-type support** — video (ffprobe), image (Pillow), PDF (PyMuPDF)
- **Docker Compose ready** — one command brings up API, worker, Postgres, Redis, MinIO
- **Pydantic Settings** — all config via environment variables, `.env` file supported
- **Async SQLAlchemy** — non-blocking DB access throughout

---

## Architecture

```
Client
  |
  POST /upload
  |-- validate type + size
  |-- upload to MinIO (storage_key)
  |-- INSERT jobs (status=queued)
  |-- ARQ enqueue process_media(job_id)
  |
  <-- { job_id, status: "queued", polling_url }

ARQ Worker (separate process)
  |
  dequeue process_media(job_id)
  |-- UPDATE jobs SET status='processing'
  |-- download file from MinIO to /tmp
  |-- extract metadata (ffprobe / Pillow / PyMuPDF)
  |-- UPDATE jobs SET status='done', result={...}
  |-- delete /tmp file

Client
  |
  GET /jobs/{job_id}
  <-- { status: "done", result: { duration, codec, resolution, ... } }
```

---

## Supported File Types

| Type  | Content-Type                    | Library   | Extracted fields                                      |
|-------|---------------------------------|-----------|-------------------------------------------------------|
| Video | `video/mp4`, `video/x-matroska`, etc. | ffprobe   | duration, codec, width, height, fps, audio codec      |
| Image | `image/jpeg`, `image/png`, etc. | Pillow    | width, height, mode, format, EXIF data                |
| PDF   | `application/pdf`               | PyMuPDF   | page count, title, author, subject, encryption status |

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/LufeDigitalWave/video-metadata-pipeline-template.git
cd video-metadata-pipeline-template

cp .env.example .env
# Edit .env and set real passwords for MINIO_ACCESS_KEY / MINIO_SECRET_KEY / DATABASE_URL
```

### 2. Start all services

```bash
docker compose up --build
```

Services:
- API: http://localhost:8000
- MinIO Console: http://localhost:9001
- Postgres: localhost:5432
- Redis: localhost:6379

### 3. Upload a file

```bash
# Upload a video
curl -X POST http://localhost:8000/upload \
  -F "file=@/path/to/video.mp4"

# Response:
# { "job_id": "abc123", "status": "queued", "polling_url": "/jobs/abc123" }
```

### 4. Poll for results

```bash
curl http://localhost:8000/jobs/abc123

# Response when done:
# {
#   "job_id": "abc123",
#   "status": "done",
#   "result": {
#     "duration_seconds": 142.5,
#     "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
#     "video": { "codec": "h264", "width": 1920, "height": 1080, "fps": 29.97 },
#     "audio": { "codec": "aac", "channels": 2, "sample_rate": "44100" }
#   }
# }
```

### 5. List jobs

```bash
# All jobs
curl "http://localhost:8000/jobs"

# Filter by status, paginate
curl "http://localhost:8000/jobs?status=done&page=1&page_size=10"
```

---

## API Reference

### `POST /upload`

Upload a file for async processing.

**Request:** `multipart/form-data` with field `file`

**Constraints:**
- Max size: `MAX_FILE_SIZE_MB` (default 500 MB)
- Allowed types: video/*, image/*, application/pdf

**Response `202 Accepted`:**
```json
{
  "job_id": "uuid",
  "status": "queued",
  "polling_url": "/jobs/uuid"
}
```

---

### `GET /jobs/{job_id}`

Get the current status and result of a job.

**Response `200 OK`:**
```json
{
  "job_id": "uuid",
  "filename": "video.mp4",
  "content_type": "video/mp4",
  "status": "done",
  "result": { ... },
  "error": null,
  "created_at": "2024-01-01T10:00:00Z",
  "completed_at": "2024-01-01T10:00:05Z"
}
```

Possible `status` values: `queued`, `processing`, `done`, `failed`

---

### `GET /jobs`

List jobs with pagination and optional status filter.

**Query params:**
- `page` (default: 1)
- `page_size` (default: 20, max: 100)
- `status` (optional: `queued | processing | done | failed`)

**Response:**
```json
{
  "page": 1,
  "page_size": 20,
  "total": 42,
  "total_pages": 3,
  "items": [...]
}
```

---

### `DELETE /jobs/{job_id}`

Delete a job record and its corresponding file in MinIO.

**Response:** `204 No Content`

---

## Adapting to Your Use Case

The only file you need to modify is `app/workers/processor.py`.

The `process_media` function follows this contract:

```python
async def process_media(ctx: dict, job_id: str) -> dict:
    # 1. Load job from DB (already done — job.content_type, job.storage_key)
    # 2. Download bytes from MinIO
    # 3. YOUR LOGIC HERE — return a JSON-serializable dict
    # 4. DB update to status=done/failed happens automatically
```

### Example swaps

| Use case              | Replace extraction with                          |
|-----------------------|--------------------------------------------------|
| Audio transcription   | `openai.Audio.transcribe()` or `whisper`         |
| Image classification  | `torch` / `transformers` inference               |
| PDF text extraction   | `pdfplumber`, `pypdf`                            |
| Document summarization| Claude / OpenAI API call on extracted text       |
| Virus scanning        | `clamav` subprocess                              |
| Video thumbnail       | `ffmpeg` subprocess → upload result to MinIO     |

The job queue, storage, status tracking, and API layer all stay the same.

---

## Environment Variables

| Variable           | Default                                                    | Description                     |
|--------------------|------------------------------------------------------------|---------------------------------|
| `DATABASE_URL`     | `postgresql+asyncpg://media:CHANGE_ME@localhost:5432/...` | Async Postgres DSN              |
| `REDIS_URL`        | `redis://localhost:6379`                                   | Redis DSN for ARQ               |
| `MINIO_ENDPOINT`   | `localhost:9000`                                           | MinIO host:port                 |
| `MINIO_ACCESS_KEY` | `CHANGE_ME`                                                | MinIO access key                |
| `MINIO_SECRET_KEY` | `CHANGE_ME_secret`                                         | MinIO secret key                |
| `MINIO_BUCKET`     | `media-pipeline`                                           | Bucket name (auto-created)      |
| `MINIO_SECURE`     | `false`                                                    | Use HTTPS for MinIO             |
| `MAX_FILE_SIZE_MB` | `500`                                                      | Upload size limit in MB         |

---

## Project Structure

```
.
├── app/
│   ├── api/
│   │   └── router.py          # FastAPI endpoints (upload, jobs CRUD)
│   ├── core/
│   │   ├── config.py          # Pydantic Settings
│   │   ├── database.py        # SQLAlchemy models + async helpers
│   │   └── storage.py         # MinIO client wrapper
│   ├── workers/
│   │   └── processor.py       # ARQ task + WorkerSettings
│   └── main.py                # FastAPI app entry point
├── migrations/
│   └── 001_schema.sql         # Raw SQL migration (alternative to ORM)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
