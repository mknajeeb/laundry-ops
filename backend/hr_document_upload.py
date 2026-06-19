"""Store employee HR document files (PDF/images) for document record file_uri."""

from __future__ import annotations

import os
import re
import uuid
from urllib.parse import urlparse

ALLOWED_EXTENSIONS = frozenset({"pdf", "png", "jpg", "jpeg", "webp", "gif"})
MAX_BYTES = 15 * 1024 * 1024
_SAFE_EXT_RE = re.compile(r"^[a-f0-9]{32}\.(pdf|png|jpg|jpeg|webp|gif)$", re.I)
_HR_MEDIA_PATH_RE = re.compile(
    r"/media/hr-documents/(\d+)/(\d+)/([a-f0-9]{32}\.(?:pdf|png|jpg|jpeg|webp|gif))$",
    re.I,
)


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


def build_hr_document_media_path(organization_id: int, user_id: int, stored_filename: str) -> str:
    return f"/media/hr-documents/{int(organization_id)}/{int(user_id)}/{stored_filename}"


def build_hr_document_media_url(organization_id: int, user_id: int, stored_filename: str) -> str:
    from backend.app import _public_api_base_for_uploads

    base = _public_api_base_for_uploads()
    return f"{base}{build_hr_document_media_path(organization_id, user_id, stored_filename)}"


def parse_hr_document_file_uri(file_uri: str) -> dict | None:
    """Resolve org/user/filename/blob_name from a stored HR document URI."""
    s = (file_uri or "").strip()
    if not s:
        return None

    path = urlparse(s).path or s
    m = _HR_MEDIA_PATH_RE.search(path)
    if m:
        org_id, uid, filename = int(m.group(1)), int(m.group(2)), m.group(3)
        return {
            "organization_id": org_id,
            "user_id": uid,
            "filename": filename,
            "blob_name": f"hr-documents/{org_id}/{uid}/{filename}",
        }

    from backend.app import _blob_name_from_url

    blob_name = _blob_name_from_url(s)
    if blob_name and blob_name.startswith("hr-documents/"):
        parts = blob_name.split("/")
        if len(parts) >= 4:
            try:
                org_id, uid = int(parts[1]), int(parts[2])
            except ValueError:
                return None
            filename = parts[3]
            if is_safe_hr_document_filename(filename):
                return {
                    "organization_id": org_id,
                    "user_id": uid,
                    "filename": filename,
                    "blob_name": blob_name,
                }
    return None


def read_employee_document_bytes(file_uri: str) -> tuple[bytes, str]:
    """Load HR document bytes from local disk or private Azure Blob."""
    ref = parse_hr_document_file_uri(file_uri)
    if not ref:
        raise ValueError("Unsupported or invalid file location")

    org_id = ref["organization_id"]
    user_id = ref["user_id"]
    filename = ref["filename"]
    root = os.path.join(_local_hr_document_root(), str(org_id), str(user_id))
    fp = os.path.join(root, filename)
    if os.path.isfile(fp):
        with open(fp, "rb") as fh:
            return fh.read(), _infer_document_content_type(filename)

    from backend.app import _ensure_blob_container

    cc = _ensure_blob_container()
    if cc is not None:
        try:
            bc = cc.get_blob_client(ref["blob_name"])
            props = bc.get_blob_properties()
            ct = getattr(getattr(props, "content_settings", None), "content_type", None)
            data = bc.download_blob().readall()
            return data, ct or _infer_document_content_type(filename)
        except Exception as exc:
            raise ValueError("File not found") from exc

    raise ValueError("File not found")


def save_employee_document_file(
    organization_id: int,
    user_id: int,
    raw: bytes,
    filename: str,
) -> tuple[str, str]:
    """
    Persist bytes and return (file_uri, stored_filename).
    Uses Azure Blob when configured, else local instance/hr_documents.
    file_uri always points at the authenticated media proxy path, never a raw blob URL.
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
    used_blob = False

    try:
        from backend.app import BlobServiceClient, ContentSettings, _ensure_blob_container

        if os.getenv("AZURE_STORAGE_CONNECTION_STRING") and BlobServiceClient is not None:
            cc = _ensure_blob_container()
            if cc is not None:
                blob_name = f"hr-documents/{int(organization_id)}/{int(user_id)}/{stored}"
                bc = cc.get_blob_client(blob_name)
                kwargs = {}
                if ContentSettings is not None:
                    kwargs["content_settings"] = ContentSettings(content_type=ct)
                bc.upload_blob(raw, overwrite=True, **kwargs)
                used_blob = True
    except Exception:
        used_blob = False

    if not used_blob:
        doc_dir = os.path.join(_local_hr_document_root(), str(int(organization_id)), str(int(user_id)))
        os.makedirs(doc_dir, exist_ok=True)
        fp = os.path.join(doc_dir, stored)
        with open(fp, "wb") as out:
            out.write(raw)

    return build_hr_document_media_url(organization_id, user_id, stored), stored


def is_safe_hr_document_filename(filename: str) -> bool:
    return bool(_SAFE_EXT_RE.match(os.path.basename(filename or "")))
