"""Checklist photos stored in MySQL, beside the completion record.

Uses the existing database. No separate file service.
"""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from typing import Any, Mapping

from backend.ta_helpers import table_exists
from backend.task_catalog import TaskCatalogError

PHOTOS_TABLE = "task_completion_photos"
MAX_PHOTOS = 4
MAX_BYTES = 900_000
ALLOWED_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def ensure_task_completion_photo_table(cursor) -> None:
    if table_exists(cursor, PHOTOS_TABLE):
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PHOTOS_TABLE} (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          token VARCHAR(64) NOT NULL,
          content_type VARCHAR(40) NOT NULL,
          byte_size INT NOT NULL,
          image_blob MEDIUMBLOB NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE KEY uq_tcp_token (token),
          INDEX idx_tcp_org (organization_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _decode_photo(raw: Mapping[str, Any]) -> tuple[str, bytes]:
    content_type = str(raw.get("content_type") or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise TaskCatalogError("Photos must be JPEG, PNG, or WebP.")
    payload = str(raw.get("data_base64") or "")
    payload = re.sub(r"^data:[^;]+;base64,", "", payload.strip())
    try:
        blob = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise TaskCatalogError("A photo could not be read.")
    if not blob or len(blob) > MAX_BYTES:
        raise TaskCatalogError("Each photo must be under 900 KB.")
    return content_type, blob


def store_inline_photos(cursor, organization_id: int, photos: list[Any]) -> list[dict[str, str]]:
    ensure_task_completion_photo_table(cursor)
    if len(photos) > MAX_PHOTOS:
        raise TaskCatalogError(f"No more than {MAX_PHOTOS} photos.")
    stored: list[dict[str, str]] = []
    for raw in photos:
        if not isinstance(raw, Mapping):
            raise TaskCatalogError("A photo could not be read.")
        if raw.get("token") and not raw.get("data_base64"):
            stored.append(
                {
                    "token": str(raw.get("token")),
                    "content_type": str(raw.get("content_type") or "image/jpeg"),
                }
            )
            continue
        content_type, blob = _decode_photo(raw)
        token = uuid.uuid4().hex
        cursor.execute(
            f"""
            INSERT INTO {PHOTOS_TABLE}
              (organization_id, token, content_type, byte_size, image_blob)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (int(organization_id), token, content_type, len(blob), blob),
        )
        stored.append({"token": token, "content_type": content_type})
    return stored


def persist_completion_photos(cursor, organization_id: int, validated: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(validated.get("values") or {})
    for key, raw in list(values.items()):
        if not isinstance(raw, list) or not raw or not isinstance(raw[0], Mapping):
            continue
        if not any(isinstance(part, Mapping) and (part.get("data_base64") or part.get("token")) for part in raw):
            continue
        values[key] = store_inline_photos(cursor, organization_id, raw)
    return {"values": values, "remarks": validated.get("remarks")}


def get_photo(cursor, organization_id: int, token: str) -> dict[str, Any] | None:
    ensure_task_completion_photo_table(cursor)
    safe = str(token or "").strip()
    if not re.fullmatch(r"[a-f0-9]{32}", safe):
        return None
    cursor.execute(
        f"""
        SELECT content_type, image_blob
        FROM {PHOTOS_TABLE}
        WHERE organization_id=%s AND token=%s
        LIMIT 1
        """,
        (int(organization_id), safe),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, dict) else None
