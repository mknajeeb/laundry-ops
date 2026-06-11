"""Rinse vendor routing — org slug and env mapping."""

from backend.rinse_vendor_config import resolve_rinse_vendor


class TestResolveRinseVendor:
    def test_veewash_slug_maps_to_veewash_without_env(self, monkeypatch):
        monkeypatch.delenv("RINSE_VEEWASH_ORG_IDS", raising=False)
        monkeypatch.delenv("RINSE_WASHPRO_ORG_IDS", raising=False)
        assert resolve_rinse_vendor(99, organization_slug="veewash") == "veewash"

    def test_washpro_slug_maps_to_washpro_without_env(self, monkeypatch):
        monkeypatch.delenv("RINSE_VEEWASH_ORG_IDS", raising=False)
        monkeypatch.delenv("RINSE_WASHPRO_ORG_IDS", raising=False)
        assert resolve_rinse_vendor(99, organization_slug="washpro") == "washpro"

    def test_org_id_env_overrides_slug(self, monkeypatch):
        monkeypatch.setenv("RINSE_WASHPRO_ORG_IDS", "3")
        assert resolve_rinse_vendor(3, organization_slug="veewash") == "washpro"
