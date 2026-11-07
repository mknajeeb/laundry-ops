"""Found-item photographs.

Uses the same private Azure Blob container as HR documents when configured,
and the same local instance fallback. Bytes are never exposed on a public URL.
"""

from __future__ import annotations

import os
import re
import uuid

ALLOWED_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "gif"})
MAX_BYTES = 8 * 1024 * 1024
_SAFE_NAME_RE = re.compile(r"^[a-f0-9]{32}\.(png|jpg|jpeg|webp|gif)$", re.I)
_BLOB_RE = re.compile(
    r"^found-items/(\d+)/([a-f0-9]{32}\.(?:png|jpg|jpeg|webp|gif))$",
    re.I,
)


def _content_type(filename: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "image/jpeg"


def local_root() -> str:
    override = (os.getenv("LOST_FOUND_MEDIA_ROOT") or "").strip()
    root = override or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "instance", "lost_found")
    )
    os.makedirs(root, exist_ok=True)
    return root


def is_safe_blob_name(blob_name: str, organization_id: int) -> bool:
    match = _BLOB_RE.match(blob_name or "")
    return bool(match) and int(match.group(1)) == int(organization_id)


def save_found_item_image(organization_id: int, raw: bytes, filename: str) -> dict[str, str]:
    if not raw:
        raise ValueError("Empty file")
    if len(raw) > MAX_BYTES:
        raise ValueError("Photo is too large (max 8 MB)")
    ext = (filename.rsplit(".", 1)[-1] if "." in (filename or "") else "").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Photos must be png, jpg, jpeg, webp, or gif")
    stored = f"{uuid.uuid4().hex}.{ext}"
    blob_name = f"found-items/{int(organization_id)}/{stored}"
    content_type = _content_type(filename)
    used_blob = False
    try:
        from backend.app import BlobServiceClient, ContentSettings, _ensure_blob_container

        if os.getenv("AZURE_STORAGE_CONNECTION_STRING") and BlobServiceClient is not None:
            container = _ensure_blob_container()
            if container is not None:
                client = container.get_blob_client(blob_name)
                kwargs = {}
                if ContentSettings is not None:
                    kwargs["content_settings"] = ContentSettings(content_type=content_type)
                client.upload_blob(raw, overwrite=False, **kwargs)
                used_blob = True
    except Exception:
        used_blob = False
    if not used_blob:
        folder = os.path.join(local_root(), str(int(organization_id)))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, stored)
        if not _SAFE_NAME_RE.match(stored):
            raise ValueError("Could not store photo")
        with open(path, "wb") as handle:
            handle.write(raw)
    return {
        "blob_name": blob_name,
        "stored_filename": stored,
        "content_type": content_type,
        "storage": "blob" if used_blob else "local",
    }


def discard_found_item_image(stored: dict[str, str]) -> None:
    """Remove a photo that was stored before its report transaction committed."""
    filename = str((stored or {}).get("stored_filename") or "")
    blob_name = str((stored or {}).get("blob_name") or "")
    match = _BLOB_RE.match(blob_name)
    if not match or not _SAFE_NAME_RE.match(filename):
        return
    organization_id = int(match.group(1))
    path = os.path.join(local_root(), str(organization_id), filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    if stored.get("storage") != "blob":
        return
    try:
        from backend.app import _ensure_blob_container

        container = _ensure_blob_container()
        if container is not None:
            container.get_blob_client(blob_name).delete_blob()
    except Exception:
        pass


def read_found_item_image(blob_name: str, organization_id: int) -> tuple[bytes, str]:
    if not is_safe_blob_name(blob_name, organization_id):
        raise ValueError("Photo not found")
    filename = blob_name.rsplit("/", 1)[-1]
    folder = os.path.join(local_root(), str(int(organization_id)))
    path = os.path.join(folder, filename)
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            return handle.read(), _content_type(filename)
    from backend.app import _ensure_blob_container

    container = _ensure_blob_container()
    if container is not None:
        try:
            client = container.get_blob_client(blob_name)
            props = client.get_blob_properties()
            content_type = getattr(getattr(props, "content_settings", None), "content_type", None)
            return client.download_blob().readall(), content_type or _content_type(filename)
        except Exception as exc:
            raise ValueError("Photo not found") from exc
    raise ValueError("Photo not found")
