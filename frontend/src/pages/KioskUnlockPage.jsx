import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { Groups } from "@mui/icons-material";
import {
  authAttendancePinUnlock,
  getPublicActiveClockIns,
  getPublicOrgBranding,
  getSavedUser,
  setAuthSession,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";

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

function displayInitials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

/**
 * Public lock screen after shared-device clock actions: employee enters payroll PIN to resume session.
 */
export default function KioskUnlockPage({ onLoggedIn }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { orgSlug: orgSlugParam } = useParams();
  const slug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);
  const [teamPeople, setTeamPeople] = useState([]);
  const [teamLoading, setTeamLoading] = useState(true);

  const localeTag = locale === "es" ? "es-US" : "en-US";

  const formatClockIn = useCallback(
    (iso) => {
      if (!iso) return "";
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "";
      return d.toLocaleTimeString(localeTag, { hour: "numeric", minute: "2-digit" });
    },
    [localeTag],
  );

  const loadTeam = useCallback(async () => {
    if (!slug) return;
    try {
      const res = await getPublicActiveClockIns(slug);
      if (res.status === 200 && Array.isArray(res.data?.people)) {
        setTeamPeople(res.data.people);
      } else {
        setTeamPeople([]);
      }
    } catch {
      setTeamPeople([]);
    } finally {
      setTeamLoading(false);
    }
  }, [slug]);

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

  useEffect(() => {
    applyAppIconFromOrganizationLogo(branding?.logo_url ?? null);
    return () => {
      try {
        const u = getSavedUser();
        applyAppIconFromOrganizationLogo(u?.organization_logo_url ?? null);
      } catch {
        applyAppIconFromOrganizationLogo(null);
      }
    };
  }, [branding?.logo_url]);

  useEffect(() => {
    if (!slug) return undefined;
    setTeamLoading(true);
    loadTeam();
    const id = window.setInterval(loadTeam, 45000);
    return () => window.clearInterval(id);
  }, [slug, loadTeam]);

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

  const orgTitle = branding?.display_name || slug;

  return (
    <Box
      sx={{
        minHeight: "100%",
        py: { xs: 2.5, sm: 4 },
        px: { xs: 1.5, sm: 2.5 },
        background: `
          radial-gradient(ellipse 85% 55% at 15% 5%, ${alpha("#6366f1", 0.35)}, transparent 52%),
          radial-gradient(ellipse 70% 45% at 92% 88%, ${alpha("#0ea5e9", 0.22)}, transparent 48%),
          linear-gradient(168deg, #0b1220 0%, #111827 42%, #0f172a 100%)
        `,
      }}
    >
      <Box sx={{ maxWidth: 1080, mx: "auto" }}>
        <Paper
          elevation={0}
          sx={{
            mb: 2.5,
            p: { xs: 2, sm: 2.5 },
            borderRadius: 4,
            border: "1px solid",
            borderColor: alpha("#ffffff", 0.12),
            bgcolor: alpha("#ffffff", 0.06),
            backdropFilter: "blur(14px)",
          }}
        >
          <Stack direction="row" alignItems="center" spacing={2} sx={{ minWidth: 0 }}>
            <TenantLogo logoUrl={branding?.logo_url} size={52} sx={{ flexShrink: 0 }} />
            <Box sx={{ minWidth: 0 }}>
              <Typography
                sx={{
                  fontSize: { xs: "1.35rem", sm: "1.6rem" },
                  fontWeight: 700,
                  color: "#f8fafc",
                  letterSpacing: "-0.02em",
                  lineHeight: 1.2,
                }}
                noWrap
                title={orgTitle}
              >
                {orgTitle}
              </Typography>
              <Typography sx={{ color: alpha("#e2e8f0", 0.75), fontSize: 13, mt: 0.35 }}>
                {t("kiosk.heroSubtitle")}
              </Typography>
            </Box>
          </Stack>
        </Paper>

        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2.5}
          alignItems="stretch"
          sx={{ justifyContent: "center" }}
        >
          {/* PIN card — first on mobile */}
          <Paper
            elevation={0}
            sx={{
              order: { xs: 1, md: 2 },
              width: { xs: "100%", md: 400 },
              flexShrink: 0,
              p: { xs: 2.25, sm: 3 },
              borderRadius: 4,
              border: "1px solid",
              borderColor: alpha("#ffffff", 0.14),
              bgcolor: alpha("#ffffff", 0.96),
              backdropFilter: "blur(12px)",
              boxShadow: `0 24px 48px ${alpha("#000000", 0.35)}`,
            }}
          >
            <Typography
              variant="overline"
              sx={{ letterSpacing: "0.12em", color: "text.secondary", fontWeight: 700 }}
            >
              {t("kiosk.unlockSection")}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2, mt: 0.75, lineHeight: 1.45 }}>
              {t("kiosk.pinCardHint")}
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
              sx={{
                "& .MuiOutlinedInput-root": { borderRadius: 2 },
              }}
            />
            {error ? (
              <Alert severity="error" sx={{ mt: 2, width: "100%" }}>
                {error}
              </Alert>
            ) : null}
            <Button
              variant="contained"
              fullWidth
              disabled={loading}
              onClick={submit}
              size="large"
              sx={{
                mt: 2,
                py: 1.35,
                borderRadius: 2,
                fontWeight: 700,
                textTransform: "none",
                fontSize: "1rem",
                boxShadow: "0 8px 24px rgba(37, 99, 235, 0.35)",
              }}
            >
              {loading ? <CircularProgress size={22} color="inherit" /> : t("kiosk.unlock")}
            </Button>
            <Button
              component={Link}
              to={`/login/${encodeURIComponent(slug)}`}
              size="small"
              sx={{ mt: 1.5, textTransform: "none" }}
            >
              {t("kiosk.useFullLogin")}
            </Button>
          </Paper>

          {/* Team at work */}
          <Paper
            elevation={0}
            sx={{
              order: { xs: 2, md: 1 },
              flex: 1,
              minHeight: { xs: 280, md: 420 },
              p: { xs: 2.25, sm: 3 },
              borderRadius: 4,
              border: "1px solid",
              borderColor: alpha("#ffffff", 0.12),
              bgcolor: alpha("#ffffff", 0.07),
              backdropFilter: "blur(14px)",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
              <Groups sx={{ color: alpha("#e2e8f0", 0.9), fontSize: 28 }} />
              <Typography
                variant="h6"
                sx={{ fontWeight: 700, color: "#f8fafc", letterSpacing: "-0.02em" }}
              >
                {t("kiosk.atWorkNow")}
              </Typography>
            </Stack>

            {teamLoading ? (
              <Box sx={{ flex: 1, display: "grid", placeItems: "center", py: 6 }}>
                <CircularProgress sx={{ color: alpha("#e2e8f0", 0.8) }} />
              </Box>
            ) : teamPeople.length === 0 ? (
              <Box
                sx={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  py: 4,
                  px: 2,
                  borderRadius: 2,
                  bgcolor: alpha("#000000", 0.2),
                  border: `1px dashed ${alpha("#ffffff", 0.15)}`,
                }}
              >
                <Typography sx={{ color: alpha("#cbd5e1", 0.95), textAlign: "center" }}>
                  {t("kiosk.noOneClockedIn")}
                </Typography>
              </Box>
            ) : (
              <Stack
                spacing={1.25}
                sx={{
                  flex: 1,
                  overflowY: "auto",
                  pr: 0.5,
                  maxHeight: { xs: 360, md: 520 },
                }}
              >
                {teamPeople.map((p) => (
                  <Stack
                    key={String(p.user_id)}
                    direction="row"
                    alignItems="center"
                    spacing={1.5}
                    sx={{
                      p: 1.5,
                      borderRadius: 2.5,
                      bgcolor: alpha("#000000", 0.22),
                      border: `1px solid ${alpha("#ffffff", 0.08)}`,
                    }}
                  >
                    <Avatar
                      sx={{
                        width: 44,
                        height: 44,
                        fontWeight: 700,
                        bgcolor: alpha("#6366f1", 0.85),
                        color: "#fff",
                      }}
                    >
                      {displayInitials(p.display_name)}
                    </Avatar>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography
                        sx={{
                          fontWeight: 700,
                          color: "#f8fafc",
                          fontSize: "1rem",
                          lineHeight: 1.25,
                        }}
                        noWrap
                        title={p.display_name}
                      >
                        {p.display_name}
                      </Typography>
                      <Typography sx={{ fontSize: 12.5, color: alpha("#94a3b8", 1), mt: 0.25 }}>
                        {t("kiosk.clockedInAt").replace("{time}", formatClockIn(p.clock_in_at))}
                      </Typography>
                    </Box>
                    {p.on_break ? (
                      <Chip
                        label={t("kiosk.onBreakBadge")}
                        size="small"
                        sx={{
                          fontWeight: 700,
                          bgcolor: alpha("#f59e0b", 0.95),
                          color: "#0f172a",
                          flexShrink: 0,
                        }}
                      />
                    ) : (
                      <Chip
                        label={t("kiosk.workingBadge")}
                        size="small"
                        sx={{
                          fontWeight: 700,
                          bgcolor: alpha("#10b981", 0.9),
                          color: "#fff",
                          flexShrink: 0,
                        }}
                      />
                    )}
                  </Stack>
                ))}
              </Stack>
            )}
          </Paper>
        </Stack>
      </Box>
    </Box>
  );
}
