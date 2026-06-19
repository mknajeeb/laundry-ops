"""HR document upload URL and private blob read helpers."""

from __future__ import annotations

from backend.hr_document_upload import (
    build_hr_document_media_path,
    build_hr_document_media_url,
    parse_hr_document_file_uri,
)


def test_build_hr_document_media_path():
    assert (
        build_hr_document_media_path(3, 29, "f4c05a73c9c4494983286ad4408857c3.png")
        == "/media/hr-documents/3/29/f4c05a73c9c4494983286ad4408857c3.png"
    )


def test_parse_media_url():
    ref = parse_hr_document_file_uri(
        "https://laundryops-api.example.com/media/hr-documents/3/29/abcd1234567890123456789012345678.pdf"
    )
    assert ref is not None
    assert ref["organization_id"] == 3
    assert ref["user_id"] == 29
    assert ref["filename"] == "abcd1234567890123456789012345678.pdf"
    assert ref["blob_name"] == "hr-documents/3/29/abcd1234567890123456789012345678.pdf"


def test_parse_legacy_blob_url():
    ref = parse_hr_document_file_uri(
        "https://laundryopsstorage01.blob.core.windows.net/order-tickets/hr-documents/3/29/f4c05a73c9c4494983286ad4408857c3.png"
    )
    assert ref is not None
    assert ref["organization_id"] == 3
    assert ref["user_id"] == 29
    assert ref["filename"] == "f4c05a73c9c4494983286ad4408857c3.png"


def test_save_returns_media_url_not_blob(monkeypatch):
    import backend.app as app_mod
    import backend.hr_document_upload as mod

    class _FakeBlobClient:
        url = "https://storage.blob.core.windows.net/order-tickets/hr-documents/1/2/deadbeef.png"

        def upload_blob(self, raw, overwrite=True, **kwargs):
            return None

    class _FakeContainer:
        def get_blob_client(self, name):
            return _FakeBlobClient()

    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setattr(app_mod, "BlobServiceClient", object())
    monkeypatch.setattr(app_mod, "_ensure_blob_container", lambda: _FakeContainer())
    monkeypatch.setattr(app_mod, "_public_api_base_for_uploads", lambda: "https://api.example.com")

    uri, stored = mod.save_employee_document_file(1, 2, b"png-bytes", "scan.png")
    assert stored.endswith(".png")
    assert uri == build_hr_document_media_url(1, 2, stored)
    assert "blob.core.windows.net" not in uri
