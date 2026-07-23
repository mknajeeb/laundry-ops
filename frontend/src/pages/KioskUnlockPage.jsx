import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
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
import { tenantDefaultRoute } from "../utils/platformAccess";
import { applyKioskPwaManifest } from "../utils/kioskPwaManifest";

const PIN_LEN = 4;

/** Bright cyan/teal digit keys */
function digitKeySx() {
  return {
    minHeight: { xs: 44, sm: 42 },
    fontSize: "1.05rem",
    fontWeight: 600,
    borderRadius: 2,
    color: "#ecfeff",
    py: 0.5,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: alpha("#22d3ee", 0.58),
    bgcolor: alpha("#0891b2", 0.32),
    backdropFilter: "blur(12px)",
    "&:hover": {
      borderColor: alpha("#67e8f9", 0.85),
      bgcolor: alpha("#06b6d4", 0.48),
    },
    "&.Mui-disabled": {
      borderColor: alpha("#22d3ee", 0.18),
      color: alpha("#ecfeff", 0.35),
      bgcolor: alpha("#0891b2", 0.1),
    },
  };
}

/** Violet accent for backspace / clear */
function utilityKeySx() {
  return {
    minHeight: { xs: 44, sm: 42 },
    fontSize: "0.8rem",
    fontWeight: 600,
    borderRadius: 2,
    color: "#f5f3ff",
    py: 0.5,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: alpha("#a78bfa", 0.58),
    bgcolor: alpha("#7c3aed", 0.32),
    backdropFilter: "blur(12px)",
    textTransform: "none",
    "&:hover": {
      borderColor: alpha("#c4b5fd", 0.82),
      bgcolor: alpha("#6d28d9", 0.46),
    },
    "&.Mui-disabled": {
      borderColor: alpha("#a78bfa", 0.18),
      color: alpha("#f5f3ff", 0.35),
      bgcolor: alpha("#7c3aed", 0.1),
    },
  };
}

function utilityIconSx() {
  return {
    minHeight: { xs: 44, sm: 42 },
    borderRadius: 2,
    color: "#ede9fe",
    border: `1px solid ${alpha("#a78bfa", 0.58)}`,
    bgcolor: alpha("#7c3aed", 0.32),
    backdropFilter: "blur(12px)",
    "&:hover": {
      borderColor: alpha("#c4b5fd", 0.82),
      bgcolor: alpha("#6d28d9", 0.46),
    },
    "&.Mui-disabled": {
      opacity: 0.45,
      borderColor: alpha("#a78bfa", 0.15),
      bgcolor: alpha("#7c3aed", 0.08),
    },
  };
}

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

/** Allow only same-origin app paths (e.g. /inventory) after PIN unlock. */
function safeNextPath(raw) {
  if (!raw || typeof raw !== "string") return "";
  const path = raw.trim();
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("://")) return "";
  if (path.includes("\\") || path.includes("\n") || path.includes("\r")) return "";
  const allowed = new Set(["/inventory"]);
  const bare = path.split("?")[0].split("#")[0];
  return allowed.has(bare) ? bare : "";
}

/**
 * Public lock screen after shared-device clock actions: employee enters payroll PIN to resume session.
 * Optional ?next=/inventory deep-links into Inventory after unlock (phone PIN PWA).
 */
export default function KioskUnlockPage({ onLoggedIn }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { orgSlug: orgSlugParam } = useParams();
  const slug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);
  const nextPath = useMemo(() => safeNextPath(searchParams.get("next")), [searchParams]);
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);
  const [teamPeople, setTeamPeople] = useState([]);
  const [teamLoading, setTeamLoading] = useState(true);
  const teamScrollRef = useRef(null);
  const prevPinLenRef = useRef(0);
  const [teamCanScrollUp, setTeamCanScrollUp] = useState(false);
  const [teamCanScrollDown, setTeamCanScrollDown] = useState(false);

  useLayoutEffect(() => {
    if (nextPath !== "/inventory") return undefined;
    return applyKioskPwaManifest(slug, "inventory");
  }, [slug, nextPath]);

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
    setPin((p) => `${String(p).replace(/\D/g, "")}${ch}`.slice(0, PIN_LEN));
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

  const performUnlock = useCallback(
    async (digits) => {
      if (!slug || String(digits || "").replace(/\D/g, "").length !== PIN_LEN) return;
      const clean = String(digits).replace(/\D/g, "");
      setError("");
      try {
        setLoading(true);
        const res = await authAttendancePinUnlock(slug, clean);
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
        navigate(nextPath || tenantDefaultRoute(payload.user), { replace: true });
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
        setPin("");
        prevPinLenRef.current = 0;
      } finally {
        setLoading(false);
      }
    },
    [slug, navigate, onLoggedIn, t, nextPath],
  );

  useEffect(() => {
    if (!slug) return;
    const len = pinDigits.length;
    if (len < PIN_LEN) {
      prevPinLenRef.current = len;
      return;
    }
    if (len === PIN_LEN && prevPinLenRef.current < PIN_LEN) {
      prevPinLenRef.current = PIN_LEN;
      void performUnlock(pinDigits);
    }
  }, [slug, pinDigits, performUnlock]);

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

  const orgTitle = branding?.display_name || slug;

  return (
    <Box
      sx={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        py: { xs: 1, sm: 1.25 },
        px: { xs: 1, sm: 1.5 },
        background: `
          radial-gradient(ellipse 85% 55% at 15% 5%, ${alpha("#6366f1", 0.28)}, transparent 52%),
          radial-gradient(ellipse 70% 45% at 92% 88%, ${alpha("#0ea5e9", 0.18)}, transparent 48%),
          linear-gradient(168deg, #0b1220 0%, #111827 42%, #0f172a 100%)
        `,
      }}
    >
      <Box
        sx={{
          maxWidth: 1080,
          mx: "auto",
          width: "100%",
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        <Paper
          elevation={0}
          sx={{
            mb: { xs: 1, sm: 1.25 },
            py: { xs: 1, sm: 1.15 },
            px: { xs: 1.25, sm: 1.5 },
            borderRadius: 3,
            border: "1px solid",
            borderColor: alpha("#ffffff", 0.14),
            bgcolor: alpha("#ffffff", 0.06),
            backdropFilter: "blur(14px)",
            flexShrink: 0,
          }}
        >
          <Stack direction="row" alignItems="center" spacing={1.5} sx={{ minWidth: 0 }}>
            <TenantLogo logoUrl={branding?.logo_url} size={40} sx={{ flexShrink: 0 }} />
            <Typography
              sx={{
                fontSize: { xs: "1.15rem", sm: "1.25rem" },
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
          </Stack>
        </Paper>

        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={{ xs: 1.25, sm: 1.5 }}
          alignItems="stretch"
          sx={{ flex: 1, minHeight: 0, justifyContent: "center" }}
        >
          {/* PIN — compact glass keypad; right column on tablet */}
          <Paper
            elevation={0}
            sx={{
              order: { xs: 1, sm: 2 },
              width: { xs: "100%", sm: 268 },
              flexShrink: 0,
              alignSelf: { xs: "stretch", sm: "flex-start" },
              p: { xs: 1.35, sm: 1.5 },
              borderRadius: 3,
              border: "1px solid",
              borderColor: alpha("#ffffff", 0.18),
              bgcolor: alpha("#ffffff", 0.06),
              backdropFilter: "blur(16px)",
              boxShadow: `0 12px 40px ${alpha("#000000", 0.25)}`,
            }}
          >
            <Box sx={{ position: "relative" }}>
              {loading ? (
                <Box
                  sx={{
                    position: "absolute",
                    inset: 0,
                    zIndex: 2,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    borderRadius: 2,
                    bgcolor: alpha("#0f172a", 0.72),
                    backdropFilter: "blur(6px)",
                  }}
                >
                  <CircularProgress sx={{ color: alpha("#22d3ee", 0.95) }} />
                </Box>
              ) : null}
              <Box sx={{ pointerEvents: loading ? "none" : "auto" }}>
                <Box
                  sx={{
                    display: "flex",
                    justifyContent: "center",
                    gap: 1,
                    minHeight: 32,
                    alignItems: "center",
                    mb: 1.25,
                  }}
                  aria-live="polite"
                  aria-label={t("kiosk.pinLabel")}
                >
                  {Array.from({ length: PIN_LEN }).map((_, i) => (
                    <Box
                      key={i}
                      sx={{
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        bgcolor: i < pinDigits.length ? alpha("#22d3ee", 0.95) : alpha("#ffffff", 0.14),
                        boxShadow:
                          i < pinDigits.length ? `0 0 12px ${alpha("#22d3ee", 0.5)}` : "none",
                      }}
                    />
                  ))}
                </Box>
                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3, 1fr)",
                    gap: 0.65,
                    width: "100%",
                    maxWidth: 244,
                    mx: "auto",
                  }}
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((num) => (
                    <Button
                      key={num}
                      variant="outlined"
                      disableElevation
                      disabled={loading}
                      onClick={() => appendDigit(num)}
                      sx={digitKeySx()}
                    >
                      {num}
                    </Button>
                  ))}
                  <IconButton
                    aria-label="Backspace"
                    disabled={loading || !pinDigits.length}
                    onClick={pinBackspace}
                    sx={utilityIconSx()}
                  >
                    <Backspace sx={{ fontSize: 22 }} />
                  </IconButton>
                  <Button
                    variant="outlined"
                    disableElevation
                    disabled={loading}
                    onClick={() => appendDigit(0)}
                    sx={digitKeySx()}
                  >
                    0
                  </Button>
                  <Button
                    variant="outlined"
                    disableElevation
                    disabled={loading || !pinDigits.length}
                    onClick={pinClear}
                    sx={utilityKeySx()}
                  >
                    {t("kiosk.clearPin")}
                  </Button>
                </Box>
              </Box>
            </Box>
            {error ? (
              <Alert
                severity="error"
                sx={{
                  mt: 1.25,
                  width: "100%",
                  py: 0.25,
                  "& .MuiAlert-message": { fontSize: 13 },
                }}
              >
                {error}
              </Alert>
            ) : null}
            <Button
              component={Link}
              to={`/login/${encodeURIComponent(slug)}`}
              size="small"
              sx={{
                mt: 1,
                textTransform: "none",
                fontSize: 12,
                color: alpha("#e2e8f0", 0.75),
                minHeight: 0,
                py: 0.25,
              }}
            >
              {t("kiosk.useFullLogin")}
            </Button>
          </Paper>

          {/* Team at work — priority height on tablets */}
          <Paper
            elevation={0}
            sx={{
              order: { xs: 2, sm: 1 },
              flex: 1,
              minWidth: 0,
              minHeight: { xs: "min(42vh, 340px)", sm: 200 },
              maxHeight: { xs: "min(48vh, 380px)", sm: "none" },
              p: { xs: 1.35, sm: 1.5 },
              borderRadius: 3,
              border: "1px solid",
              borderColor: alpha("#ffffff", 0.14),
              bgcolor: alpha("#ffffff", 0.06),
              backdropFilter: "blur(14px)",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.25, flexShrink: 0 }}>
              <Groups sx={{ color: alpha("#e2e8f0", 0.88), fontSize: 24 }} />
              <Typography
                sx={{
                  fontWeight: 700,
                  fontSize: { xs: "1.05rem", sm: "1.1rem" },
                  color: "#f8fafc",
                  letterSpacing: "-0.02em",
                }}
              >
                {t("kiosk.atWorkNow")}
              </Typography>
            </Stack>

            {teamLoading ? (
              <Box sx={{ flex: 1, display: "grid", placeItems: "center", py: 4 }}>
                <CircularProgress size={36} sx={{ color: alpha("#e2e8f0", 0.8) }} />
              </Box>
            ) : teamPeople.length === 0 ? (
              <Box
                sx={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  py: 3,
                  px: 2,
                  borderRadius: 2,
                  bgcolor: alpha("#000000", 0.18),
                  border: `1px dashed ${alpha("#ffffff", 0.12)}`,
                }}
              >
                <Typography sx={{ fontSize: 14, color: alpha("#cbd5e1", 0.95), textAlign: "center" }}>
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
                  <Stack spacing={1}>
                    {teamPeople.map((p) => (
                      <Stack
                        key={String(p.user_id)}
                        direction="row"
                        alignItems="center"
                        spacing={1.25}
                        sx={{
                          p: 1.15,
                          borderRadius: 2,
                          bgcolor: alpha("#000000", 0.2),
                          border: `1px solid ${alpha("#ffffff", 0.08)}`,
                        }}
                      >
                        <Avatar
                          sx={{
                            width: 40,
                            height: 40,
                            fontSize: "0.95rem",
                            fontWeight: 700,
                            bgcolor: alpha("#6366f1", 0.82),
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
                              fontSize: "0.92rem",
                              lineHeight: 1.25,
                            }}
                            noWrap
                            title={p.display_name}
                          >
                            {p.display_name}
                          </Typography>
                          <Typography sx={{ fontSize: 12, color: alpha("#94a3b8", 1), mt: 0.15 }}>
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
                  spacing={1.5}
                  sx={{
                    pt: 1,
                    mt: "auto",
                    flexShrink: 0,
                    borderTop: `1px solid ${alpha("#ffffff", 0.1)}`,
                  }}
                >
                  <IconButton
                    size="medium"
                    onClick={() => scrollTeamList("up")}
                    disabled={!teamCanScrollUp}
                    aria-label={t("kiosk.scrollTeamUp")}
                    sx={{
                      color: "#f8fafc",
                      bgcolor: alpha("#ffffff", 0.08),
                      border: `1px solid ${alpha("#ffffff", 0.15)}`,
                      "&:disabled": { opacity: 0.35 },
                      "&:hover": { bgcolor: alpha("#ffffff", 0.14) },
                    }}
                  >
                    <KeyboardArrowUp sx={{ fontSize: 26 }} />
                  </IconButton>
                  <IconButton
                    size="medium"
                    onClick={() => scrollTeamList("down")}
                    disabled={!teamCanScrollDown}
                    aria-label={t("kiosk.scrollTeamDown")}
                    sx={{
                      color: "#f8fafc",
                      bgcolor: alpha("#ffffff", 0.08),
                      border: `1px solid ${alpha("#ffffff", 0.15)}`,
                      "&:disabled": { opacity: 0.35 },
                      "&:hover": { bgcolor: alpha("#ffffff", 0.14) },
                    }}
                  >
                    <KeyboardArrowDown sx={{ fontSize: 26 }} />
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
