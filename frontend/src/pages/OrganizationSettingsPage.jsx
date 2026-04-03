import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  authMe,
  getAuthToken,
  getOrganization,
  putOrganization,
  setAuthSession,
  uploadOrganizationLogo,
} from "../api";
import { useI18n } from "../i18n/I18nContext";

/**
 * Tenant administrator only: display name, contact, logo. Slug is read-only.
 */
function OrganizationSettingsPage() {
  const { t } = useI18n();
  const [row, setRow] = useState(null);
  const [displayName, setDisplayName] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  const teamLoginUrl = useMemo(() => {
    if (!row?.slug) return "";
    return `${window.location.origin}/login/${encodeURIComponent(String(row.slug).toLowerCase())}`;
  }, [row?.slug]);

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await getOrganization();
      const r = res.data || {};
      setRow(r);
      setDisplayName(r.display_name || "");
      setAddress(r.address || "");
      setPhone(r.phone || "");
      setEmail(r.email || "");
      setLogoUrl(r.logo_url || "");
    } catch (e) {
      setError(e?.response?.data?.error || "Could not load organization.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await putOrganization({
        display_name: displayName.trim(),
        logo_url: logoUrl.trim(),
        address: address.trim(),
        phone: phone.trim(),
        email: email.trim(),
      });
      const me = await authMe();
      setAuthSession({ token: getAuthToken(), user: me.data });
      window.dispatchEvent(new CustomEvent("washpro-user-refresh"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function onPickFile(ev) {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const res = await uploadOrganizationLogo(file);
      const url = res.data?.logo_url;
      if (url) setLogoUrl(url);
      const me = await authMe();
      setAuthSession({ token: getAuthToken(), user: me.data });
      window.dispatchEvent(new CustomEvent("washpro-user-refresh"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Box className="page" sx={{ p: { xs: 1.2, md: 2 }, maxWidth: 560 }}>
      <Typography variant="h4" className="page-title" sx={{ mb: 1 }}>
        {t("organization.pageTitle")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t("organization.tenantOnlyBlurb")}
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2, borderRadius: 2 }}>
        {row ? (
          <>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              {t("organization.slugLabel")}: <strong>{row.slug}</strong>
            </Typography>
            {teamLoginUrl ? (
              <Box sx={{ mb: 2, p: 1.5, bgcolor: "#f1f5f9", borderRadius: 1, border: "1px solid #e2e8f0" }}>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                  {t("organization.teamLoginBox")}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{ fontFamily: "ui-monospace, monospace", wordBreak: "break-all", mb: 1 }}
                >
                  {teamLoginUrl}
                </Typography>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(teamLoginUrl);
                      setCopiedUrl(true);
                      setTimeout(() => setCopiedUrl(false), 2000);
                    } catch {
                      /* ignore */
                    }
                  }}
                >
                  {copiedUrl ? t("organization.copied") : t("organization.copyLink")}
                </Button>
              </Box>
            ) : null}
          </>
        ) : null}
        <Stack component="form" onSubmit={save} spacing={2}>
          <TextField
            label={t("platformOrgs.displayName")}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            fullWidth
            size="small"
          />
          <TextField
            label={t("organization.address")}
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            fullWidth
            size="small"
            multiline
            minRows={2}
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              label={t("organization.phone")}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              fullWidth
              size="small"
            />
            <TextField
              label={t("organization.email")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              fullWidth
              size="small"
            />
          </Stack>
          <TextField
            label={t("organization.logoUrlLabel")}
            value={logoUrl}
            onChange={(e) => setLogoUrl(e.target.value)}
            fullWidth
            size="small"
            placeholder="https://cdn.example.com/logo.png"
            helperText={t("organization.logoUrlHelp")}
          />
          {logoUrl ? (
            <Box
              sx={{
                border: "1px solid #e2e8f0",
                borderRadius: 1,
                p: 1,
                display: "flex",
                justifyContent: "center",
                bgcolor: "#f8fafc",
              }}
            >
              <img
                src={logoUrl}
                alt=""
                style={{ maxHeight: 56, maxWidth: "100%", objectFit: "contain" }}
                onError={(e) => {
                  e.target.style.display = "none";
                }}
              />
            </Box>
          ) : null}
          <Box>
            <Button variant="outlined" component="label" disabled={uploading || saving} size="small">
              {uploading ? t("organization.uploading") : t("organization.uploadLogo")}
              <input type="file" hidden accept="image/png,image/jpeg,image/webp,image/gif" onChange={onPickFile} />
            </Button>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
              {t("organization.logoUploadLocalHint")}
            </Typography>
          </Box>
          <Button type="submit" variant="contained" disabled={saving || uploading}>
            {saving ? t("common.saving") : t("common.save")}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}

export default OrganizationSettingsPage;
