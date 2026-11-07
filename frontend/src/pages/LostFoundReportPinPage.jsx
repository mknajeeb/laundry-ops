import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Alert, Button, Stack, Typography } from "@mui/material";
import { pinLostFoundLocations, pinLostFoundReport } from "../api";
import LostFoundReportForm from "../components/lostFound/LostFoundReportForm";
import { useI18n } from "../i18n/I18nContext";
import { OpsMobileShell, OpsTopBar } from "../opsMobile";
import { clearPinHubSession, loadPinHubSession, pinHubMenuPath } from "../utils/pinHubSession";

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
  const [choices, setChoices] = useState({ washers: [], dryers: [], folding_tables: [] });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);
  const [formKey, setFormKey] = useState(0);

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

  return (
    <OpsMobileShell>
      <OpsTopBar
        title={t("lostFound.report")}
        onBack={() => navigate(pinHubMenuPath(slug))}
        onLock={lock}
        identity={hub.employee_first_name || hub.employee_name || ""}
      />
      {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}
      {done ? (
        <Stack spacing={1.5} sx={{ pt: 1 }}>
          <Alert severity="success">{t("lostFound.success")}</Alert>
          <Typography sx={{ fontWeight: 800 }}>{done.location_label}</Typography>
          <Typography variant="body2" color="text.secondary">{done.reported_at_display}</Typography>
          <Button
            variant="contained"
            onClick={() => {
              setDone(null);
              setFormKey((n) => n + 1);
            }}
            sx={{ fontWeight: 900, textTransform: "none" }}
          >
            {t("lostFound.reportAnother")}
          </Button>
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
}
