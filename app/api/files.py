"""
POST /v1/files — file upload, validation, sandboxed extraction, RAG indexing (A2.1–A2.6).

Validation pipeline (per A2.2):
  1. Size check.
  2. Magic-bytes validation (NOT extension or MIME header — both are forgeable).
  3. ZIP-container validation for OOXML formats (DOCX/PPTX/XLSX): verify PK header
     AND confirm the archive contains OOXML marker files.
  4. Zip-bomb guard: abort if uncompressed ratio or total size exceeds limits.

After validation:
  - File is saved to a server-side path outside the web root with a non-guessable name.
  - FileMeta row is written to Postgres.
  - An ARQ background job is dispatched for extraction + RAG indexing (A2.6).
  - Response returns {fileId, jobId, artifact} immediately (202 accepted).
"""

import io
import logging
import os
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import insert

from ..auth.permissions import require_permission
from ..config import settings
from ..contracts.context import RequestContext
from ..core.context import get_request_context
from ..store.db import FileMeta

logger = logging.getLogger(__name__)

router = APIRouter()

# ------ Magic-byte signatures ------------------------------------------------

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"

# OOXML marker files that must be present in the ZIP container.
_DOCX_MARKER = "word/"
_PPTX_MARKER = "ppt/"
_XLSX_MARKER = "xl/"

_EXTENSION_TO_MARKER = {
    ".docx": _DOCX_MARKER,
    ".pptx": _PPTX_MARKER,
    ".xlsx": _XLSX_MARKER,
}

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt"}


# ---------------------------------------------------------------------------

@router.post("/files")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(get_request_context),
):
    require_permission(ctx, "files", "upload")

    # 1. Read content (memory-bounded by nginx / uvicorn limit upstream).
    content = await file.read()

    # 2. Size check.
    max_bytes = settings.limits.max_file_size_bytes
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content)} bytes (max {max_bytes} bytes)",
        )

    # 3. Derive and validate extension.
    original_name = file.filename or "upload"
    suffix = Path(original_name).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: '{suffix}'. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    # 4. Magic-bytes validation (ignores declared Content-Type and extension).
    _validate_magic_bytes(content, suffix)

    # 5. OOXML container + zip-bomb check for DOCX/PPTX/XLSX.
    if suffix in _EXTENSION_TO_MARKER:
        _validate_ooxml(content, suffix)

    # 6. Persist to server-side storage (outside web root, non-guessable path).
    file_id = str(uuid.uuid4())
    upload_dir = Path(settings.limits.upload_dir) / ctx.tenant_key
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Non-guessable filename; extension retained for sandbox extractor.
    storage_path = upload_dir / f"{file_id}{suffix}"
    storage_path.write_bytes(content)

    # 7. Write FileMeta to Postgres.
    async with request.app.state.session_factory() as session:
        stmt = insert(FileMeta).values(
            id=file_id,
            tenant_key=ctx.tenant_key,
            filename=original_name,
            filesize=len(content),
            mime_type=_suffix_to_mime(suffix),
            storage_path=str(storage_path),
            extraction_status="pending",
            user_id=ctx.user_id,
        )
        await session.execute(stmt)
        await session.commit()

    # 8. Dispatch ARQ background job for extraction + RAG indexing.
    job_id: str | None = None
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool:
        job = await arq_pool.enqueue_job(
            "extract_and_index_file",
            tenant_key=ctx.tenant_key,
            file_id=file_id,
            file_path=str(storage_path),
            job_id=file_id,          # reuse file_id as job_id for simplicity
        )
        job_id = job.job_id if job else None

        # Update the FileMeta with the job_id.
        async with request.app.state.session_factory() as session:
            from sqlalchemy import update
            await session.execute(
                update(FileMeta)
                .where(FileMeta.id == file_id)
                .values(extraction_status="extracting", job_id=job_id)
            )
            await session.commit()

    audit = getattr(request.app.state, "audit_logger", None)
    if audit:
        await audit.log(ctx, action="file_upload", tool="upload_file", status="success")

    logger.info("File uploaded: file_id=%s tenant=%s size=%d", file_id, ctx.tenant_key, len(content))

    return {
        "fileId": file_id,
        "jobId": job_id,
        "artifact": {
            "id": file_id,
            "type": "uploaded_file",
            "title": original_name,
            "status": "uploaded",
        },
    }


@router.get("/files/{file_id}/status")
async def file_status(
    file_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Poll extraction progress.  Returns the FileMeta status and ARQ job progress."""
    from sqlalchemy import select
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(FileMeta).where(
                FileMeta.id == file_id,
                FileMeta.tenant_key == ctx.tenant_key,
            )
        )
        meta = result.scalar_one_or_none()

    if meta is None:
        raise HTTPException(status_code=404, detail="File not found.")

    progress = None
    if meta.job_id:
        raw = await request.app.state.redis.get(
            f"{ctx.tenant_key}:job:{meta.job_id}:progress"
        )
        if raw:
            import json
            progress = json.loads(raw)

    return {
        "fileId": file_id,
        "filename": meta.filename,
        "extractionStatus": meta.extraction_status,
        "progress": progress,
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_magic_bytes(content: bytes, suffix: str) -> None:
    if suffix == ".pdf":
        if not content.startswith(_PDF_MAGIC):
            raise HTTPException(status_code=400, detail="File content is not a valid PDF (bad magic bytes).")
    elif suffix in (".docx", ".pptx", ".xlsx"):
        if not content.startswith(_ZIP_MAGIC):
            raise HTTPException(
                status_code=400,
                detail=f"File content is not a valid {suffix.lstrip('.')} (missing ZIP magic bytes).",
            )
    # CSV and TXT have no reliable magic bytes; accept them.


def _validate_ooxml(content: bytes, suffix: str) -> None:
    """Validate ZIP container, check for OOXML structure, and guard against zip bombs."""
    lim = settings.limits
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infos = zf.infolist()

            # Zip-bomb: uncompressed total size check.
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > lim.max_zip_uncompressed_bytes:
                raise HTTPException(
                    status_code=400,
                    detail="File rejected: uncompressed content exceeds the maximum allowed size.",
                )

            # Zip-bomb: compression ratio check.
            if len(content) > 0:
                ratio = total_uncompressed / len(content)
                if ratio > lim.max_zip_expansion_ratio:
                    raise HTTPException(
                        status_code=400,
                        detail="File rejected: compression ratio too high (potential zip bomb).",
                    )

            # OOXML structure check: must contain the expected sub-directory.
            marker = _EXTENSION_TO_MARKER.get(suffix, "")
            names = {info.filename for info in infos}
            if not any(n.startswith(marker) for n in names):
                raise HTTPException(
                    status_code=400,
                    detail=f"File is not a valid {suffix.lstrip('.')} document (missing OOXML structure).",
                )

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="File is not a valid ZIP/OOXML container.")


def _suffix_to_mime(suffix: str) -> str:
    return {
        ".pdf":  "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv":  "text/csv",
        ".txt":  "text/plain",
    }.get(suffix, "application/octet-stream")
