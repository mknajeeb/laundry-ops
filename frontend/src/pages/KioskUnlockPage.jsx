import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { Backspace, Groups, KeyboardArrowDown, KeyboardArrowUp } from "@mui/icons-material";
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

const MAX_PIN_LEN = 10;

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
  const teamScrollRef = useRef(null);
  const [teamCanScrollUp, setTeamCanScrollUp] = useState(false);
  const [teamCanScrollDown, setTeamCanScrollDown] = useState(false);

  const localeTag = locale === "es" ? "es-US" : "en-US";

  const updateTeamScrollArrows = useCallback(() => {
    const el = teamScrollRef.current;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    setTeamCanScrollUp(scrollTop > 2);
    setTeamCanScrollDown(scrollTop + clientHeight < scrollHeight - 2);
  }, []);

  const scrollTeamList = useCallback(
    (dir) => {
      const el = teamScrollRef.current;
      if (!el) return;
      const step = Math.max(88, Math.round(el.clientHeight * 0.72));
      el.scrollBy({ top: dir === "up" ? -step : step, behavior: "smooth" });
      window.setTimeout(updateTeamScrollArrows, 400);
    },
    [updateTeamScrollArrows],
  );

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

  useLayoutEffect(() => {
    if (teamLoading || teamPeople.length === 0) return;
    const id = window.requestAnimationFrame(() => updateTeamScrollArrows());
    return () => window.cancelAnimationFrame(id);
  }, [teamPeople, teamLoading, updateTeamScrollArrows]);

  useEffect(() => {
    const el = teamScrollRef.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => updateTeamScrollArrows());
    ro.observe(el);
    return () => ro.disconnect();
  }, [teamPeople.length, teamLoading, updateTeamScrollArrows]);

  const pinDigits = String(pin).replace(/\D/g, "");
  const appendDigit = (n) => {
    const ch = String(n).replace(/\D/g, "").slice(0, 1);
    if (!ch) return;
    setPin((p) => `${String(p).replace(/\D/g, "")}${ch}`.slice(0, MAX_PIN_LEN));
    setError("");
  };
  const pinBackspace = () => {
    setPin((p) => String(p).slice(0, -1));
    setError("");
  };
  const pinClear = () => {
    setPin("");
    setError("");
  };

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
    const digits = pinDigits;
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
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5, mt: 0.75, lineHeight: 1.45 }}>
              {t("kiosk.pinCardHint")}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1, fontWeight: 600 }}>
              {t("kiosk.pinLabel")}
            </Typography>
            <Box
              sx={{
                display: "flex",
                justifyContent: "center",
                gap: 1.25,
                minHeight: 44,
                alignItems: "center",
                mb: 2,
                flexWrap: "wrap",
              }}
              aria-live="polite"
              aria-label={t("kiosk.pinLabel")}
            >
              {Array.from({
                length: Math.min(MAX_PIN_LEN, Math.max(4, pinDigits.length || 4)),
              }).map((_, i) => (
                <Box
                  key={i}
                  sx={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    bgcolor: i < pinDigits.length ? "primary.main" : "action.disabledBackground",
                    opacity: i < pinDigits.length ? 1 : 0.45,
                  }}
                />
              ))}
            </Box>
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: "repeat(3, 1fr)",
                gap: 1,
                width: "100%",
                maxWidth: 300,
                mx: "auto",
              }}
            >
              {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((num) => (
                <Button
                  key={num}
                  variant="outlined"
                  disabled={loading}
                  onClick={() => appendDigit(num)}
                  sx={{
                    minHeight: 54,
                    fontSize: "1.4rem",
                    fontWeight: 700,
                    borderRadius: 2,
                    borderWidth: 2,
                  }}
                >
                  {num}
                </Button>
              ))}
              <IconButton
                aria-label="Backspace"
                disabled={loading || !pinDigits.length}
                onClick={pinBackspace}
                sx={{
                  minHeight: 54,
                  borderRadius: 2,
                  border: "2px solid",
                  borderColor: "divider",
                }}
              >
                <Backspace sx={{ fontSize: 28 }} />
              </IconButton>
              <Button
                variant="outlined"
                disabled={loading}
                onClick={() => appendDigit(0)}
                sx={{
                  minHeight: 54,
                  fontSize: "1.4rem",
                  fontWeight: 700,
                  borderRadius: 2,
                  borderWidth: 2,
                }}
              >
                0
              </Button>
              <Button
                variant="outlined"
                color="secondary"
                disabled={loading || !pinDigits.length}
                onClick={pinClear}
                sx={{ minHeight: 54, borderRadius: 2, fontWeight: 600, textTransform: "none" }}
              >
                {t("kiosk.clearPin")}
              </Button>
            </Box>
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
              minWidth: 0,
              minHeight: { xs: 280, md: 360 },
              maxHeight: { xs: "min(62vh, 520px)", md: "min(72vh, 640px)" },
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
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2, flexShrink: 0 }}>
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
              <>
                <Box
                  ref={teamScrollRef}
                  onScroll={updateTeamScrollArrows}
                  sx={{
                    flex: 1,
                    minHeight: 0,
                    overflowY: "auto",
                    overflowX: "hidden",
                    pr: 0.5,
                    WebkitOverflowScrolling: "touch",
                  }}
                >
                  <Stack spacing={1.25}>
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
                </Box>
                <Stack
                  direction="row"
                  justifyContent="center"
                  alignItems="center"
                  spacing={2}
                  sx={{
                    pt: 1.5,
                    mt: "auto",
                    flexShrink: 0,
                    borderTop: `1px solid ${alpha("#ffffff", 0.1)}`,
                  }}
                >
                  <IconButton
                    size="large"
                    onClick={() => scrollTeamList("up")}
                    disabled={!teamCanScrollUp}
                    aria-label={t("kiosk.scrollTeamUp")}
                    sx={{
                      color: "#f8fafc",
                      bgcolor: alpha("#000000", 0.35),
                      "&:disabled": { opacity: 0.35 },
                      "&:hover": { bgcolor: alpha("#000000", 0.5) },
                    }}
                  >
                    <KeyboardArrowUp sx={{ fontSize: 32 }} />
                  </IconButton>
                  <IconButton
                    size="large"
                    onClick={() => scrollTeamList("down")}
                    disabled={!teamCanScrollDown}
                    aria-label={t("kiosk.scrollTeamDown")}
                    sx={{
                      color: "#f8fafc",
                      bgcolor: alpha("#000000", 0.35),
                      "&:disabled": { opacity: 0.35 },
                      "&:hover": { bgcolor: alpha("#000000", 0.5) },
                    }}
                  >
                    <KeyboardArrowDown sx={{ fontSize: 32 }} />
                  </IconButton>
                </Stack>
              </>
            )}
          </Paper>
        </Stack>
      </Box>
    </Box>
  );
}
