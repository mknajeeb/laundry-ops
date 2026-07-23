import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { Backspace, CheckCircle } from "@mui/icons-material";
import {
  attendancePinPunch,
  getPublicOrgBranding,
  getPublicOrganizationsForAttendance,
  getWashproApiBase,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";

const PIN_LEN = 4;
const SUCCESS_RESET_MS = 4000;
const STORAGE_KEY = "washpro_attendance_org_slug";
/** Official V/W mark — transparent PNG served from public assets. */
const VEEWASH_ATTENDANCE_LOGO = VEEWASH_LOGO_URL;

const VW = {
  navy: "#16192b",
  blue: "#2d3d9c",
  cobalt: "#4865ee",
  gold: "#9a7209",
  goldMid: "#d4a84b",
  goldLight: "#fde68a",
  cream: "#faf6e9",
  mist: "#eef2ff",
};

function attendanceLogoSrc(orgSlug, brandingLogoUrl) {
  const slug = sanitizeSlug(orgSlug);
  if (slug === "veewash") return VEEWASH_ATTENDANCE_LOGO;
  const trimmed =
    brandingLogoUrl != null && String(brandingLogoUrl).trim()
      ? String(brandingLogoUrl).trim()
      : "";
  return trimmed ? resolveOrgLogoUrl(trimmed) : null;
}

/** Brand wordmark: gold “Vee” + blue “Wash” (matches marketing site). */
function VeeWashWordmark() {
  return (
    <Typography
      component="div"
      sx={{
        fontWeight: 800,
        fontSize: { xs: "2rem", sm: "2.25rem" },
        letterSpacing: "-0.03em",
        lineHeight: 1.1,
        textAlign: "center",
      }}
    >
      <Box
        component="span"
        sx={{
          background: "linear-gradient(135deg, #fde68a 0%, #d4a84b 45%, #9a7209 100%)",
          WebkitBackgroundClip: "text",
          backgroundClip: "text",
          color: "transparent",
        }}
      >
        Vee
      </Box>
      <Box
        component="span"
        sx={{
          background: "linear-gradient(90deg, #2d3d9c 0%, #4865ee 100%)",
          WebkitBackgroundClip: "text",
          backgroundClip: "text",
          color: "transparent",
        }}
      >
        Wash
      </Box>
    </Typography>
  );
}

/** Map API errors to kiosk-friendly copy. */
function punchMessageFromResponse(data, status, t) {
  if (!data || typeof data !== "object") return null;
  const raw = String(data.error || data.message || "").trim();
  if (!raw) return null;
  const lower = raw.toLowerCase();
  if (lower.includes("invalid pin")) return t("attendance.invalidPin");
  if (lower.includes("kiosk is not enabled") || lower.includes("not enabled for this company")) {
    return t("attendance.kioskDisabled");
  }
  if (lower.includes("contact manager") || lower.includes("clock-in not allowed")) {
    return t("attendance.complianceBlocked");
  }
  if (lower.includes("end your break")) return t("attendance.endBreakFirst");
  if (status === 429) return t("attendance.rateLimited");
  if (status >= 500) return t("attendance.serverError");
  return raw;
}

function punchMessageFromAxiosError(err, t) {
  const status = err?.response?.status;
  const data = err?.response?.data;
  const mapped = punchMessageFromResponse(data, status, t);
  if (mapped) return mapped;
  if (err?.code === "ECONNABORTED" || String(err?.message || "").toLowerCase().includes("timeout")) {
    return t("attendance.timeout");
  }
  if (!err?.response) {
    return t("attendance.networkError");
  }
  const msg = typeof err?.message === "string" ? err.message.trim() : "";
  return msg || t("attendance.punchFailed");
}

function digitKeySx(veewash) {
  if (veewash) {
    return {
      minHeight: { xs: 56, sm: 52 },
      fontSize: "1.4rem",
      fontWeight: 700,
      borderRadius: 2.5,
      color: VW.navy,
      py: 0.5,
      borderWidth: 2,
      borderStyle: "solid",
      borderColor: alpha(VW.cobalt, 0.35),
      bgcolor: "#fff",
      boxShadow: `0 4px 14px -6px ${alpha(VW.blue, 0.28)}`,
      "&:hover": {
        borderColor: VW.cobalt,
        bgcolor: alpha(VW.cobalt, 0.08),
        boxShadow: `0 8px 20px -6px ${alpha(VW.cobalt, 0.35)}`,
      },
      "&.Mui-disabled": { opacity: 0.45 },
    };
  }
  return {
    minHeight: { xs: 56, sm: 52 },
    fontSize: "1.35rem",
    fontWeight: 600,
    borderRadius: 2,
    color: "#0f172a",
    py: 0.5,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: alpha("#2d3d9c", 0.25),
    bgcolor: "#fff",
    "&:hover": {
      borderColor: alpha("#4865ee", 0.55),
      bgcolor: alpha("#4865ee", 0.06),
    },
    "&.Mui-disabled": { opacity: 0.45 },
  };
}

function utilityKeySx(veewash) {
  if (veewash) {
    return {
      minHeight: { xs: 56, sm: 52 },
      fontSize: "0.8rem",
      fontWeight: 700,
      borderRadius: 2.5,
      color: VW.gold,
      py: 0.5,
      borderWidth: 2,
      borderStyle: "solid",
      borderColor: alpha(VW.goldMid, 0.55),
      bgcolor: alpha(VW.cream, 0.85),
      textTransform: "none",
      "&:hover": {
        borderColor: VW.goldMid,
        bgcolor: VW.cream,
      },
    };
  }
  return {
    minHeight: { xs: 56, sm: 52 },
    fontSize: "0.85rem",
    fontWeight: 600,
    borderRadius: 2,
    color: "#334155",
    py: 0.5,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: alpha("#94a3b8", 0.5),
    bgcolor: "#f8fafc",
    textTransform: "none",
    "&:hover": { bgcolor: "#f1f5f9" },
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

function TenantPicker({ orgs, value, onChange, label }) {
  if (!orgs?.length) return null;
  return (
    <FormControl fullWidth size="small" sx={{ maxWidth: 360 }}>
      <InputLabel id="attendance-org-label">{label}</InputLabel>
      <Select
        labelId="attendance-org-label"
        label={label}
        value={value || ""}
        onChange={(e) => onChange(String(e.target.value))}
      >
        {orgs.map((o) => (
          <MenuItem key={o.slug} value={o.slug}>
            {o.display_name || o.slug}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

/**
 * Kiosk attendance: PIN only → clock in/out. No app session, no sidebar.
 */
export default function AttendancePinPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { orgSlug: orgSlugParam } = useParams();
  const routeSlug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);

  const [selectedSlug, setSelectedSlug] = useState("");
  const [orgs, setOrgs] = useState([]);
  const [orgsLoading, setOrgsLoading] = useState(!routeSlug);

  const slug = routeSlug || selectedSlug;

  const [pin, setPin] = useState("");
  const [pendingPin, setPendingPin] = useState("");
  const [selectionTree, setSelectionTree] = useState([]);
  const [pickStep, setPickStep] = useState(null); // null | category | role
  const [pendingCategoryId, setPendingCategoryId] = useState(null);
  const [pendingRoleId, setPendingRoleId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(null);
  const [branding, setBranding] = useState(null);

  const prevPinLenRef = useRef(0);
  const resetTimerRef = useRef(null);
  const punchInFlightRef = useRef(false);

  const localeTag = locale === "es" ? "es-US" : "en-US";

  /** Separate PWA manifest so Android “Add to Home screen” opens attendance, not /login. */
  useLayoutEffect(() => {
    return applyAttendancePwaManifest(routeSlug || selectedSlug);
  }, [routeSlug, selectedSlug]);

  useEffect(() => {
    if (routeSlug) return;
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) setSelectedSlug(sanitizeSlug(saved));
    } catch {
      /* ignore */
    }
  }, [routeSlug]);

  useEffect(() => {
    if (routeSlug) return undefined;
    let cancelled = false;
    setOrgsLoading(true);
    getPublicOrganizationsForAttendance()
      .then((res) => {
        if (cancelled) return;
        const list = Array.isArray(res.data?.organizations) ? res.data.organizations : [];
        setOrgs(list);
      })
      .catch(() => {
        if (!cancelled) setOrgs([]);
      })
      .finally(() => {
        if (!cancelled) setOrgsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [routeSlug]);

  useEffect(() => {
    if (!routeSlug && selectedSlug) {
      try {
        localStorage.setItem(STORAGE_KEY, selectedSlug);
      } catch {
        /* ignore */
      }
    }
  }, [routeSlug, selectedSlug]);

  useEffect(() => {
    if (!slug) {
      setBranding(null);
      return undefined;
    }
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
    return () => applyAppIconFromOrganizationLogo(null);
  }, [branding?.logo_url]);

  const clearSuccessTimer = useCallback(() => {
    if (resetTimerRef.current) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  const resetPinScreen = useCallback(() => {
    clearSuccessTimer();
    setSuccess(null);
    setPin("");
    setError("");
    prevPinLenRef.current = 0;
  }, [clearSuccessTimer]);

  const scheduleReset = useCallback(() => {
    clearSuccessTimer();
    resetTimerRef.current = window.setTimeout(() => {
      resetPinScreen();
    }, SUCCESS_RESET_MS);
  }, [clearSuccessTimer, resetPinScreen]);

  useEffect(() => () => clearSuccessTimer(), [clearSuccessTimer]);

  const pinDigits = String(pin).replace(/\D/g, "");
  const appendDigit = (n) => {
    if (success || loading) return;
    const ch = String(n).replace(/\D/g, "").slice(0, 1);
    if (!ch) return;
    setPin((p) => `${String(p).replace(/\D/g, "")}${ch}`.slice(0, PIN_LEN));
    setError("");
  };
  const pinBackspace = () => {
    if (success || loading) return;
    setPin((p) => String(p).slice(0, -1));
    setError("");
  };
  const pinClear = () => {
    if (success || loading) return;
    setPin("");
    setError("");
  };

  const performPunch = useCallback(
    async (digits, assignment = null) => {
      if (!slug || String(digits || "").replace(/\D/g, "").length !== PIN_LEN) return;
      if (punchInFlightRef.current) return;
      const clean = String(digits).replace(/\D/g, "");
      punchInFlightRef.current = true;
      setError("");
      setSuccess(null);
      setLoading(true);
      try {
        const opts = {};
        if (assignment?.category_id != null) opts.category_id = assignment.category_id;
        if (assignment?.role_id != null) opts.role_id = assignment.role_id;
        const res = await attendancePinPunch(slug, clean, opts);
        const status = res?.status ?? 0;
        const data = res?.data;
        if (typeof data === "string" && data.trim().startsWith("<")) {
          console.error("[attendance] Non-JSON response from API", {
            status,
            apiBase: getWashproApiBase(),
            slug,
          });
          setError(t("attendance.serverError"));
          return;
        }
        const body = data && typeof data === "object" ? data : {};
        if (status >= 200 && status < 300 && body.ok) {
          setSuccess(body);
          setPin("");
          setPendingPin("");
          setPickStep(null);
          setSelectionTree([]);
          prevPinLenRef.current = 0;
          scheduleReset();
          return;
        }
        if (body.needs_category_role && Array.isArray(body.selection_tree)) {
          setPendingPin(clean);
          setSelectionTree(body.selection_tree);
          setPendingCategoryId(null);
          setPendingRoleId(null);
          setPickStep("category");
          setPin("");
          prevPinLenRef.current = 0;
          return;
        }
        const msg =
          punchMessageFromResponse(body, status, t) || t("attendance.punchFailed");
        console.error("[attendance] PIN punch rejected", {
          status,
          body,
          apiBase: getWashproApiBase(),
          slug,
        });
        setError(msg);
        setPin("");
        prevPinLenRef.current = 0;
      } catch (e) {
        const msg = punchMessageFromAxiosError(e, t);
        console.error("[attendance] PIN punch failed", {
          message: e?.message,
          code: e?.code,
          status: e?.response?.status,
          data: e?.response?.data,
          apiBase: getWashproApiBase(),
          slug,
        });
        setError(msg);
        setPin("");
        prevPinLenRef.current = 0;
      } finally {
        punchInFlightRef.current = false;
        setLoading(false);
      }
    },
    [slug, scheduleReset, t],
  );

  useEffect(() => {
    if (!slug || success || loading) return;
    const len = pinDigits.length;
    if (len < PIN_LEN) {
      prevPinLenRef.current = len;
      return;
    }
    if (len === PIN_LEN && prevPinLenRef.current < PIN_LEN) {
      prevPinLenRef.current = PIN_LEN;
      void performPunch(pinDigits);
    }
  }, [slug, pinDigits, performPunch, success, loading]);

  const goToSlugRoute = (newSlug) => {
    const s = sanitizeSlug(newSlug);
    if (s) navigate(`/attendance/${encodeURIComponent(s)}`, { replace: true });
  };

  const formatClockedAt = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString(localeTag, { hour: "numeric", minute: "2-digit" });
  };

  const selectedPickCategory =
    selectionTree.find((c) => Number(c.id) === Number(pendingCategoryId)) || null;
  const pickRoles = selectedPickCategory?.roles || [];

  const confirmCategoryRolePunch = (categoryId, roleId) => {
    const catId = categoryId ?? pendingCategoryId;
    const rId = roleId ?? pendingRoleId;
    if (!pendingPin || !catId || !rId) return;
    setPickStep(null);
    void performPunch(pendingPin, {
      category_id: catId,
      role_id: rId,
    });
  };

  const tenantTitle = branding?.display_name || slug || t("attendance.title");
  const logoSrc = attendanceLogoSrc(slug, branding?.logo_url);
  const isVeeWash = sanitizeSlug(slug) === "veewash";

  useEffect(() => {
    if (!logoSrc || logoSrc.startsWith("http")) return undefined;
    const link = document.createElement("link");
    link.rel = "preload";
    link.as = "image";
    link.href = logoSrc;
    document.head.appendChild(link);
    return () => link.remove();
  }, [logoSrc]);

  // Reserved path: never treat "role" as a company slug on the punch screen.
  if (routeSlug === "role") {
    return <Navigate to="/attendance/role" replace />;
  }

  return (
    <Box
      sx={{
        position: "relative",
        minHeight: "100dvh",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        px: 2,
        py: 3,
        overflow: "hidden",
        background: isVeeWash
          ? `linear-gradient(155deg, #ffffff 0%, ${VW.mist} 42%, ${VW.cream} 100%)`
          : "linear-gradient(180deg, #fafbfd 0%, #f3f6fa 50%, #eef2f8 100%)",
        "&::before": isVeeWash
          ? {
              content: '""',
              position: "absolute",
              top: "-12%",
              right: "-18%",
              width: "55%",
              height: "45%",
              borderRadius: "50%",
              background: `radial-gradient(circle, ${alpha(VW.cobalt, 0.2)} 0%, transparent 70%)`,
              pointerEvents: "none",
            }
          : undefined,
        "&::after": isVeeWash
          ? {
              content: '""',
              position: "absolute",
              bottom: "-8%",
              left: "-15%",
              width: "50%",
              height: "40%",
              borderRadius: "50%",
              background: `radial-gradient(circle, ${alpha(VW.goldMid, 0.22)} 0%, transparent 72%)`,
              pointerEvents: "none",
            }
          : undefined,
      }}
    >
      <Paper
        elevation={0}
        sx={{
          position: "relative",
          zIndex: 1,
          width: "100%",
          maxWidth: 420,
          p: { xs: 2.5, sm: 3 },
          borderRadius: 4,
          border: "1px solid",
          borderColor: isVeeWash ? alpha(VW.cobalt, 0.22) : alpha("#2d3d9c", 0.12),
          boxShadow: isVeeWash
            ? `0 28px 64px -24px ${alpha(VW.blue, 0.35)}, 0 0 0 1px ${alpha(VW.goldMid, 0.12)} inset`
            : "0 24px 60px -28px rgba(45, 61, 156, 0.28)",
          background: isVeeWash
            ? "linear-gradient(180deg, rgba(255,255,255,0.97) 0%, rgba(255,255,255,0.92) 100%)"
            : undefined,
          backdropFilter: isVeeWash ? "blur(12px)" : undefined,
        }}
      >
        <Stack spacing={isVeeWash ? 1.25 : 2} alignItems="center" sx={{ width: "100%" }}>
          {logoSrc ? (
            <Box
              component="img"
              src={logoSrc}
              alt="VeeWash"
              sx={{
                width: isVeeWash ? "min(200px, 58vw)" : "min(240px, 78vw)",
                height: "auto",
                maxHeight: isVeeWash ? 112 : 100,
                objectFit: "contain",
                display: "block",
                mt: isVeeWash ? 0.5 : 0,
                backgroundColor: "transparent",
                // Hide any residual white plate in the PNG against the card.
                mixBlendMode: isVeeWash ? "multiply" : "normal",
                filter: "none",
              }}
            />
          ) : (
            <TenantLogo logoUrl={branding?.logo_url} sx={{ width: 96, height: 96 }} />
          )}
          {isVeeWash ? (
            <VeeWashWordmark />
          ) : (
            <Typography variant="h6" fontWeight={700} textAlign="center" color="#152238">
              {tenantTitle}
            </Typography>
          )}
          <Typography
            variant="subtitle1"
            fontWeight={600}
            textAlign="center"
            sx={{
              color: isVeeWash ? alpha(VW.blue, 0.75) : "#64748b",
              letterSpacing: isVeeWash ? "0.06em" : undefined,
              textTransform: isVeeWash ? "uppercase" : undefined,
              fontSize: isVeeWash ? "0.72rem" : undefined,
            }}
          >
            {t("attendance.enterPin")}
          </Typography>

          {!routeSlug && (
            <Box sx={{ width: "100%" }}>
              {orgsLoading ? (
                <CircularProgress size={24} />
              ) : (
                <TenantPicker
                  orgs={orgs}
                  value={selectedSlug}
                  onChange={(s) => {
                    setSelectedSlug(s);
                    resetPinScreen();
                  }}
                  label={t("attendance.selectCompany")}
                />
              )}
            </Box>
          )}

          {success ? (
            <Stack spacing={1.5} alignItems="center" sx={{ py: 2, width: "100%" }}>
              <CheckCircle sx={{ fontSize: 56, color: "#059669" }} />
              <Typography variant="h6" fontWeight={700} textAlign="center" color="#152238">
                {success.message}
              </Typography>
              {success.clocked_at ? (
                <Typography variant="body2" color="text.secondary">
                  {formatClockedAt(success.clocked_at)}
                </Typography>
              ) : null}
            </Stack>
          ) : (
            <>
              <Box
                sx={{
                  display: "flex",
                  gap: 1,
                  justifyContent: "center",
                  minHeight: 28,
                }}
                aria-label={t("attendance.pinLabel")}
              >
                {Array.from({ length: PIN_LEN }).map((_, i) => (
                  <Box
                    key={i}
                    sx={{
                      width: 14,
                      height: 14,
                      borderRadius: "50%",
                      bgcolor: i < pinDigits.length
                        ? isVeeWash
                          ? VW.cobalt
                          : "#2d3d9c"
                        : alpha(isVeeWash ? VW.cobalt : "#2d3d9c", 0.15),
                      boxShadow: i < pinDigits.length && isVeeWash
                        ? `0 0 12px ${alpha(VW.cobalt, 0.45)}`
                        : "none",
                      transition: "background-color 0.15s",
                    }}
                  />
                ))}
              </Box>

              {loading ? (
                <Stack spacing={0.5} alignItems="center" sx={{ width: "100%", py: 0.5 }}>
                  <CircularProgress
                    size={36}
                    aria-label={t("attendance.checkingPin")}
                    sx={isVeeWash ? { color: VW.cobalt } : undefined}
                  />
                  <Typography variant="body2" color="text.secondary">
                    {t("attendance.checkingPin")}
                  </Typography>
                </Stack>
              ) : null}

              {error ? (
                <Alert severity="error" sx={{ width: "100%" }} onClose={() => setError("")}>
                  {error}
                </Alert>
              ) : null}

              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, 1fr)",
                  gap: 1,
                  width: "100%",
                  maxWidth: 300,
                  opacity: loading || !slug ? 0.55 : 1,
                  pointerEvents: loading || !slug ? "none" : "auto",
                }}
              >
                {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
                  <Button
                    key={n}
                    variant="outlined"
                    onClick={() => appendDigit(n)}
                    sx={digitKeySx(isVeeWash)}
                  >
                    {n}
                  </Button>
                ))}
                <Button variant="outlined" onClick={pinClear} sx={utilityKeySx(isVeeWash)}>
                  {t("attendance.clearPin")}
                </Button>
                <Button variant="outlined" onClick={() => appendDigit(0)} sx={digitKeySx(isVeeWash)}>
                  0
                </Button>
                <IconButton
                  onClick={pinBackspace}
                  sx={utilityKeySx(isVeeWash)}
                  aria-label={t("attendance.backspace")}
                >
                  <Backspace fontSize="small" />
                </IconButton>
              </Box>
            </>
          )}
        </Stack>
      </Paper>

      <Stack direction="row" spacing={2} sx={{ mt: 3 }} flexWrap="wrap" justifyContent="center">
        {slug ? (
          <Button
            component={Link}
            to={`/login/${encodeURIComponent(slug)}`}
            size="small"
            color="inherit"
            sx={{ color: isVeeWash ? alpha(VW.blue, 0.65) : "#64748b" }}
          >
            {t("attendance.adminLogin")}
          </Button>
        ) : null}
        {!routeSlug && selectedSlug ? (
          <Button size="small" onClick={() => goToSlugRoute(selectedSlug)} sx={{ color: "#64748b" }}>
            {t("attendance.bookmarkLink")}
          </Button>
        ) : null}
      </Stack>

      <Dialog
        open={pickStep === "category"}
        onClose={() => {
          if (loading) return;
          setPickStep(null);
          setPendingPin("");
          setSelectionTree([]);
          setPendingCategoryId(null);
          setPendingRoleId(null);
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ fontWeight: 800 }}>{t("attendance.selectCategoryTitle")}</DialogTitle>
        <DialogContent>
          <Grid container spacing={1} sx={{ pt: 1 }}>
            {selectionTree.map((cat) => (
              <Grid item xs={6} key={cat.id}>
                <Button
                  fullWidth
                  variant="outlined"
                  disabled={loading}
                  onClick={() => {
                    setPendingCategoryId(cat.id);
                    setPendingRoleId(null);
                    setPickStep("role");
                  }}
                  sx={{ textTransform: "none", fontWeight: 700, py: 1.6 }}
                >
                  {cat.display_name || cat.name}
                </Button>
              </Grid>
            ))}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button
            disabled={loading}
            onClick={() => {
              setPickStep(null);
              setPendingPin("");
              setSelectionTree([]);
              setPendingCategoryId(null);
              setPendingRoleId(null);
            }}
          >
            {t("attendance.switchRoleCancel") || "Cancel"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={pickStep === "role"}
        onClose={() => {
          if (loading) return;
          setPickStep("category");
          setPendingRoleId(null);
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ fontWeight: 800 }}>{t("attendance.selectRoleTitle")}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5, pt: 0.5 }}>
            {selectedPickCategory?.display_name || selectedPickCategory?.name || ""}
          </Typography>
          <Grid container spacing={1}>
            {pickRoles.map((role) => (
              <Grid item xs={6} key={role.role_id || role.id}>
                <Button
                  fullWidth
                  variant="contained"
                  disabled={loading || !pendingCategoryId}
                  onClick={() => confirmCategoryRolePunch(pendingCategoryId, role.role_id)}
                  sx={{ textTransform: "none", fontWeight: 700, py: 1.6 }}
                >
                  {loading ? (
                    <CircularProgress size={20} color="inherit" />
                  ) : (
                    role.role_name || role.display_name || role.name
                  )}
                </Button>
              </Grid>
            ))}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button
            disabled={loading}
            onClick={() => {
              setPickStep("category");
              setPendingRoleId(null);
            }}
          >
            Back
          </Button>
          <Button
            disabled={loading}
            onClick={() => {
              setPickStep(null);
              setPendingPin("");
              setSelectionTree([]);
              setPendingCategoryId(null);
              setPendingRoleId(null);
            }}
          >
            {t("attendance.switchRoleCancel") || "Cancel"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
