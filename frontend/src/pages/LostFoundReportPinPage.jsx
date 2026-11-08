import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Alert, Button, Stack, Typography } from "@mui/material";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { getPublicOrgBranding, pinLostFoundLocations, pinLostFoundReport } from "../api";
import LostFoundReportForm from "../components/lostFound/LostFoundReportForm";
import { useI18n } from "../i18n/I18nContext";
import { OpsMobileShell, OpsTopBar } from "../opsMobile";
import { clearPinHubSession, loadPinHubSession, pinHubMenuPath } from "../utils/pinHubSession";
import { VEEWASH_BRAND, VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";
import { displayFoundLocation, veewashIssueCatalog } from "../utils/lostFoundLocation";

const VEEWASH_THEME = createTheme({
  palette: { primary: { main: VEEWASH_BRAND.primary, dark: VEEWASH_BRAND.primaryDark } },
});

function slugOf(raw) {
  try {
    return decodeURIComponent(String(raw || "")).toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 64);
  } catch {
    return "";
  }
}

export default function LostFoundReportPinPage() {
  const { orgSlug } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const slug = slugOf(orgSlug);
  const hub = useMemo(() => loadPinHubSession(), []);
  const [choices, setChoices] = useState(() => (slug === "veewash" ? veewashIssueCatalog() : { washers: [], dryers: [], folding_tables: [], dehumidifiers: [], redry_pockets: [] }));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);
  const [formKey, setFormKey] = useState(0);
  const [logoSrc, setLogoSrc] = useState(slug === "veewash" ? VEEWASH_LOGO_URL : null);

  useEffect(() => {
    if (!slug) return undefined;
    let cancelled = false;
    getPublicOrgBranding(slug)
      .then((res) => {
        if (cancelled) return;
        const url = res?.data?.logo_url;
        if (slug === "veewash") setLogoSrc(VEEWASH_LOGO_URL);
        else if (url) setLogoSrc(resolveOrgLogoUrl(url));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    if (!hub?.token || !slug) return undefined;
    let cancelled = false;
    pinLostFoundLocations(slug, hub.pin, { hubToken: hub.token })
      .then((res) => {
        if (!cancelled && res?.data?.ok) setChoices(res.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [hub, slug]);

  const lock = () => {
    clearPinHubSession();
    navigate(`/pin/${encodeURIComponent(slug)}`, { replace: true });
  };

  const submit = async (payload) => {
    if (!hub?.token) {
      setError(t("lostFound.pinAgain"));
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const res = await pinLostFoundReport(slug, hub.pin, { hubToken: hub.token, ...payload });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("lostFound.saveFailed"));
      setDone(body.item);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || t("lostFound.saveFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  if (!hub?.token) {
    return (
      <OpsMobileShell>
        <Alert severity="warning">{t("lostFound.pinAgain")}</Alert>
        <Button onClick={lock}>{t("lostFound.back")}</Button>
      </OpsMobileShell>
    );
  }

  const page = (
    <OpsMobileShell showLocaleToggle contentSx={{ gap: 1 }} maxWidth={440}>
      <OpsTopBar
        title={t("lostFound.report")}
        logoSrc={logoSrc}
        backLabel={t("lostFound.back")}
        onBack={() => navigate(pinHubMenuPath(slug))}
        onLock={lock}
      />
      {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}
      {done ? (
        <Stack spacing={1.5} sx={{ pt: 1 }}>
          <Alert severity="success">{t("lostFound.success")}</Alert>
          <Typography sx={{ fontWeight: 800 }}>{displayFoundLocation(done, t)}</Typography>
          <Typography variant="body2" color="text.secondary">{done.reported_at_display}</Typography>
          <Button
            variant="contained"
            onClick={() => {
              setDone(null);
              setFormKey((n) => n + 1);
            }}
            sx={{ fontWeight: 800, textTransform: "none" }}
          >
            {t("lostFound.reportAnother")}
          </Button>
          <Button onClick={lock} sx={{ textTransform: "none" }}>{t("lostFound.backToPin")}</Button>
        </Stack>
      ) : (
        <LostFoundReportForm
          key={formKey}
          choices={choices}
          submitting={submitting}
          onSubmit={submit}
        />
      )}
    </OpsMobileShell>
  );
  return slug === "veewash" ? <ThemeProvider theme={VEEWASH_THEME}>{page}</ThemeProvider> : page;
}
