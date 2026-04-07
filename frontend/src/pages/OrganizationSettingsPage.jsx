import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Box, Button, Divider, Paper, Stack, TextField, Typography } from "@mui/material";
import {
  authMe,
  getAuthToken,
  getOrganization,
  putOrganization,
  setAuthSession,
  uploadOrganizationLogo,
} from "../api";
import { useStreetAutocomplete } from "../components/GooglePlacesAutocomplete";
import { useI18n } from "../i18n/I18nContext";
import { isValidEmail, isValidUsPhone10, normalizeUsPhoneDigits } from "../utils/validation";

function normalizeEin(s) {
  const d = String(s || "").replace(/\D/g, "").slice(0, 9);
  return d;
}

/**
 * Tenant administrator: organization profile, employer block for HR forms (structured address + EIN), logo.
 */
function OrganizationSettingsPage() {
  const { t } = useI18n();
  const [row, setRow] = useState(null);
  const [displayName, setDisplayName] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [logoUrl, setLogoUrl] = useState("");

  const [employerLegalName, setEmployerLegalName] = useState("");
  const [employerStreet, setEmployerStreet] = useState("");
  const [employerApt, setEmployerApt] = useState("");
  const [employerCity, setEmployerCity] = useState("");
  const [employerState, setEmployerState] = useState("");
  const [employerZip, setEmployerZip] = useState("");
  const [employerEin, setEmployerEin] = useState("");

  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  const { inputRef: employerStreetRef, hasMapsKey } = useStreetAutocomplete((place) => {
    if (place.street) setEmployerStreet(place.street);
    if (place.city) setEmployerCity(place.city);
    if (place.state) setEmployerState(place.state);
    if (place.zip) setEmployerZip(place.zip);
  });

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
      setEmployerLegalName(r.employer_legal_name || r.display_name || "");
      setEmployerStreet(r.employer_street || "");
      setEmployerApt(r.employer_apt || "");
      setEmployerCity(r.employer_city || "");
      setEmployerState(r.employer_state || "");
      setEmployerZip(r.employer_zip || "");
      setEmployerEin(r.employer_ein || "");
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
    const dn = displayName.trim();
    if (!dn) {
      setError(t("organization.errDisplayName"));
      setSaving(false);
      return;
    }
    const eln = employerLegalName.trim();
    const st = employerStreet.trim();
    const ct = employerCity.trim();
    const stt = employerState.trim().slice(0, 2).toUpperCase();
    const zip = String(employerZip || "").replace(/\D/g, "").slice(0, 10);
    const ein = normalizeEin(employerEin);
    if (!eln || !st || !ct || !stt || !zip || ein.length !== 9) {
      setError(t("organization.errEmployerRequired"));
      setSaving(false);
      return;
    }
    const em = email.trim();
    if (em && !isValidEmail(em)) {
      setError(t("organization.errEmail"));
      setSaving(false);
      return;
    }
    const ph = normalizeUsPhoneDigits(phone);
    if (ph && !isValidUsPhone10(ph)) {
      setError(t("organization.errPhone"));
      setSaving(false);
      return;
    }
    try {
      await putOrganization({
        display_name: dn,
        logo_url: logoUrl.trim(),
        address: address.trim(),
        phone: ph || null,
        email: em || null,
        employer_legal_name: eln,
        employer_street: st,
        employer_apt: employerApt.trim() || null,
        employer_city: ct,
        employer_state: stt,
        employer_zip: zip,
        employer_ein: ein,
      });
      const me = await authMe();
      setAuthSession({ token: getAuthToken(), user: me.data });
      window.dispatchEvent(new CustomEvent("washpro-user-refresh"));
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || "Save failed.");
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
    <Box className="page" sx={{ p: { xs: 1.2, md: 2 }, maxWidth: 720 }}>
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

          <Divider sx={{ my: 1 }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {t("organization.employerSectionTitle")}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t("organization.employerSectionBlurb")}
            {hasMapsKey ? ` ${t("organization.mapsHint")}` : ""}
          </Typography>
          <TextField
            label={t("organization.employerLegalName")}
            value={employerLegalName}
            onChange={(e) => setEmployerLegalName(e.target.value)}
            required
            fullWidth
            size="small"
          />
          <TextField
            inputRef={employerStreetRef}
            label={t("organization.employerStreet")}
            value={employerStreet}
            onChange={(e) => setEmployerStreet(e.target.value)}
            required
            fullWidth
            size="small"
          />
          <TextField
            label={t("organization.employerApt")}
            value={employerApt}
            onChange={(e) => setEmployerApt(e.target.value)}
            fullWidth
            size="small"
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              label={t("organization.employerCity")}
              value={employerCity}
              onChange={(e) => setEmployerCity(e.target.value)}
              required
              fullWidth
              size="small"
            />
            <TextField
              label={t("organization.employerState")}
              value={employerState}
              onChange={(e) => setEmployerState(e.target.value.slice(0, 2).toUpperCase())}
              required
              fullWidth
              size="small"
              inputProps={{ maxLength: 2 }}
            />
            <TextField
              label={t("organization.employerZip")}
              value={employerZip}
              onChange={(e) => setEmployerZip(e.target.value.replace(/\D/g, "").slice(0, 10))}
              required
              fullWidth
              size="small"
            />
          </Stack>
          <TextField
            label={t("organization.employerEin")}
            value={employerEin}
            onChange={(e) => setEmployerEin(e.target.value.replace(/\D/g, "").slice(0, 9))}
            required
            fullWidth
            size="small"
            helperText={t("organization.employerEinHelp")}
          />

          <Divider sx={{ my: 1 }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {t("organization.contactSectionTitle")}
          </Typography>
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
              helperText={t("organization.phoneHelp")}
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
