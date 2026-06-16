"""Store employee HR document files (PDF/images) for document record file_uri."""

from __future__ import annotations

import os
import re
import uuid

ALLOWED_EXTENSIONS = frozenset({"pdf", "png", "jpg", "jpeg", "webp", "gif"})
MAX_BYTES = 15 * 1024 * 1024
_SAFE_EXT_RE = re.compile(r"^[a-f0-9]{32}\.(pdf|png|jpg|jpeg|webp|gif)$", re.I)


def _infer_document_content_type(filename: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "pdf":
        return "application/pdf"
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "image/jpeg"


def _local_hr_document_root() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "instance", "hr_documents"))
    os.makedirs(root, exist_ok=True)
    return root


def save_employee_document_file(
    organization_id: int,
    user_id: int,
    raw: bytes,
    filename: str,
) -> tuple[str, str]:
    """
    Persist bytes and return (public file_uri, stored_filename).
    Uses Azure Blob when configured, else local instance/hr_documents.
    """
    if not raw:
        raise ValueError("Empty file")
    if len(raw) > MAX_BYTES:
        raise ValueError("File too large (max 15 MB)")

    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Allowed types: pdf, png, jpg, jpeg, webp, gif")

    stored = f"{uuid.uuid4().hex}.{ext}"
    ct = _infer_document_content_type(filename)
    url: str | None = None

    try:
        from backend.app import (
            BlobServiceClient,
            ContentSettings,
            _ensure_blob_container,
            _public_api_base_for_uploads,
        )

        if os.getenv("AZURE_STORAGE_CONNECTION_STRING") and BlobServiceClient is not None:
            cc = _ensure_blob_container()
            if cc is not None:
                blob_name = f"hr-documents/{int(organization_id)}/{int(user_id)}/{stored}"
                bc = cc.get_blob_client(blob_name)
                kwargs = {}
                if ContentSettings is not None:
                    kwargs["content_settings"] = ContentSettings(content_type=ct)
                bc.upload_blob(raw, overwrite=True, **kwargs)
                url = bc.url
    except Exception:
        url = None

    if not url:
        from backend.app import _public_api_base_for_uploads

        doc_dir = os.path.join(_local_hr_document_root(), str(int(organization_id)), str(int(user_id)))
        os.makedirs(doc_dir, exist_ok=True)
        fp = os.path.join(doc_dir, stored)
        with open(fp, "wb") as out:
            out.write(raw)
        base = _public_api_base_for_uploads()
        url = f"{base}/media/hr-documents/{int(organization_id)}/{int(user_id)}/{stored}"

    return url, stored


def is_safe_hr_document_filename(filename: str) -> bool:
    return bool(_SAFE_EXT_RE.match(os.path.basename(filename or "")))
