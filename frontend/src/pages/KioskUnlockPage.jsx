import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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
  authAttendancePinUnlock,
  getPublicOrgBranding,
  getSavedUser,
  setAuthSession,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";

function sanitizeSlug(raw) {
  if (!raw) return "";
  try {
    return decodeURIComponent(String(raw))
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 64);
  } catch {
    return "";
  }
}

/**
 * Public lock screen after shared-device clock actions: employee enters payroll PIN to resume session.
 */
export default function KioskUnlockPage({ onLoggedIn }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { orgSlug: orgSlugParam } = useParams();
  const slug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);

  useEffect(() => {
    if (!slug) return undefined;
    try {
      const u = getSavedUser();
      if (u?.id && String(u.organization_slug || "").toLowerCase() === slug) {
        navigate("/", { replace: true });
      }
    } catch {
      /* ignore */
    }
    return undefined;
  }, [slug, navigate]);

  useEffect(() => {
    if (!slug) return undefined;
    let cancelled = false;
    getPublicOrgBranding(slug)
      .then((res) => {
        if (cancelled) return;
        if (res.status === 200 && res.data && !res.data.error) setBranding(res.data);
        else setBranding(null);
      })
      .catch(() => {
        if (!cancelled) setBranding(null);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (!slug) {
    return (
      <Box sx={{ p: 3, maxWidth: 420, mx: "auto" }}>
        <Alert severity="warning">{t("kiosk.invalidOrg")}</Alert>
        <Button component={Link} to="/login" sx={{ mt: 2 }}>
          {t("kiosk.backToLogin")}
        </Button>
      </Box>
    );
  }

  const submit = async () => {
    const digits = String(pin || "").replace(/\D/g, "");
    setError("");
    if (digits.length < 4) {
      setError(t("kiosk.pinTooShort"));
      return;
    }
    try {
      setLoading(true);
      const res = await authAttendancePinUnlock(slug, digits);
      const payload = res?.data || {};
      if (!payload?.token || !payload?.user) {
        throw new Error("Invalid unlock response.");
      }
      try {
        localStorage.setItem("washpro_org_slug", slug);
      } catch {
        /* ignore */
      }
      setAuthSession(payload);
      onLoggedIn?.(payload.user);
      navigate("/", { replace: true });
    } catch (e) {
      console.error(e);
      const data = e?.response?.data;
      let msg =
        (data && typeof data === "object" && (data.error || data.message)) ||
        (typeof data === "string" ? data : null);
      if (!msg && e?.response?.status === 401) {
        msg = t("kiosk.invalidPin");
      }
      if (!msg) msg = e?.message || t("kiosk.unlockFailed");
      setError(typeof msg === "string" ? msg : t("kiosk.unlockFailed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 2,
        background: "linear-gradient(145deg, #f8fbff 0%, #f2f6ff 45%, #f7fafc 100%)",
      }}
    >
      <Paper elevation={2} sx={{ p: 3, maxWidth: 400, width: "100%" }}>
        <Stack spacing={2} alignItems="center">
          <TenantLogo logoUrl={branding?.logo_url} size={44} />
          <Typography variant="h6" sx={{ fontWeight: 700, textAlign: "center" }}>
            {branding?.display_name || slug}
          </Typography>
          <Typography color="text.secondary" sx={{ textAlign: "center" }}>
            {t("kiosk.subtitle")}
          </Typography>
          <TextField
            label={t("kiosk.pinLabel")}
            type="password"
            inputMode="numeric"
            autoComplete="one-time-code"
            fullWidth
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 10))}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            disabled={loading}
          />
          {error ? (
            <Alert severity="error" sx={{ width: "100%" }}>
              {error}
            </Alert>
          ) : null}
          <Button variant="contained" fullWidth disabled={loading} onClick={submit}>
            {loading ? "…" : t("kiosk.unlock")}
          </Button>
          <Button component={Link} to={`/login/${encodeURIComponent(slug)}`} size="small">
            {t("kiosk.useFullLogin")}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}
