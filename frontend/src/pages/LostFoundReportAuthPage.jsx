import { useEffect, useState } from "react";
import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import LostFoundReportForm from "../components/lostFound/LostFoundReportForm";
import { getLostFoundLocations, getSavedUser, postLostFoundReport } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_BRAND } from "../theme/veewashBrand";
import { displayFoundLocation, veewashIssueCatalog } from "../utils/lostFoundLocation";
import { reportFailureMessage, savedReport } from "../utils/lostFoundSubmit";

const VEEWASH_THEME = createTheme({
  palette: { primary: { main: VEEWASH_BRAND.primary, dark: VEEWASH_BRAND.primaryDark } },
});

function messageForReportKey(key, t, body) {
  if (key === "reporting_not_allowed") return t("lostFound.cannotReport");
  if (key === "pin_session") return t("lostFound.pinAgain");
  if (key === "photo_required") return t("lostFound.photoRequired");
  if (key === "redry_one_reason" || key === "redry_flag_required") return t("lostFound.redry.flagRequired");
  if (key === "pocket_required") return t("lostFound.redry.pocketRequired");
  if (key && key !== "Forbidden") return body?.error || key;
  return t("lostFound.saveFailed");
}

export default function LostFoundReportAuthPage() {
  const { t } = useI18n();
  const user = getSavedUser() || {};
  const slug = String(user.organization_slug || user.organization?.slug || "").toLowerCase();
  const [choices, setChoices] = useState(slug === "veewash" ? veewashIssueCatalog() : {});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);
  const [formKey, setFormKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getLostFoundLocations()
      .then((res) => {
        if (!cancelled && res?.data?.ok) setChoices(res.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const submit = async (payload) => {
    setSubmitting(true);
    setError("");
    try {
      const res = await postLostFoundReport(payload);
      const body = res?.data || {};
      const saved = savedReport(body);
      if (!saved) {
        const key = reportFailureMessage(body, t("lostFound.saveFailed"));
        throw new Error(messageForReportKey(key, t, body));
      }
      setDone(saved);
    } catch (err) {
      const data = err?.response?.data;
      const key = reportFailureMessage(data, "");
      setError(key ? messageForReportKey(key, t, data) : (err?.message || t("lostFound.saveFailed")));
    } finally {
      setSubmitting(false);
    }
  };

  const page = (
    <Box sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: 880, mx: "auto" }}>
      <Typography variant="h5" sx={{ fontWeight: 800, mb: 1 }}>{t("lostFound.report")}</Typography>
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {done ? (
        <Stack spacing={1.25}>
          <Alert severity="success">{t("lostFound.success")}</Alert>
          <Typography sx={{ fontWeight: 800 }}>{displayFoundLocation(done, t)}</Typography>
          <Typography variant="body2" color="text.secondary">{done.reported_at_display}</Typography>
          <Button
            onClick={() => {
              setDone(null);
              setFormKey((n) => n + 1);
            }}
            sx={{ minHeight: 52, textTransform: "none", fontWeight: 800, color: "#fff", bgcolor: "#16192b", borderRadius: "14px", "&:hover": { bgcolor: "#2d3d9c" } }}
          >
            {t("lostFound.reportAnother")}
          </Button>
        </Stack>
      ) : (
        <LostFoundReportForm key={formKey} choices={choices} submitting={submitting} onSubmit={submit} />
      )}
    </Box>
  );
  return slug === "veewash" ? <ThemeProvider theme={VEEWASH_THEME}>{page}</ThemeProvider> : page;
}
