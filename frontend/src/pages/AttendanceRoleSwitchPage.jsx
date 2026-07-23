import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { Link, useNavigate, useParams } from "react-router-dom";
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
  attendancePinSwitchRole,
  createTaskTrackingSwitchIdempotencyKey,
  getPublicOrgBranding,
  getPublicOrganizationsForAttendance,
  getWashproApiBase,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";
import { roleChoiceButtonSx } from "../utils/roleChoiceButtonSx";

const PIN_LEN = 4;
const SUCCESS_RESET_MS = 3500;
const STORAGE_KEY = "washpro_attendance_org_slug";
const VEEWASH_ATTENDANCE_LOGO = VEEWASH_LOGO_URL;

const VW = {
  navy: "#16192b",
  blue: "#2d3d9c",
  cobalt: "#4865ee",
  gold: "#9a7209",
  goldMid: "#d4a84b",
  cream: "#faf6e9",
  mist: "#eef2ff",
};

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

function attendanceLogoSrc(orgSlug, brandingLogoUrl) {
  const slug = sanitizeSlug(orgSlug);
  if (slug === "veewash") return VEEWASH_ATTENDANCE_LOGO;
  const trimmed =
    brandingLogoUrl != null && String(brandingLogoUrl).trim()
      ? String(brandingLogoUrl).trim()
      : "";
  return trimmed ? resolveOrgLogoUrl(trimmed) : null;
}

/** Same wordmark as /attendance. */
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

function mapSwitchRoleError(body, status, t) {
  const raw = (body?.error || "").toString();
  const lower = raw.toLowerCase();
  if (status === 429 || lower.includes("too many")) return t("attendance.rateLimited");
  if (lower.includes("clocked in") || lower.includes("fichado")) {
    return t("attendance.switchRoleNotClockedIn");
  }
  if (lower.includes("disabled") || lower.includes("desactiv")) {
    return t("attendance.switchRoleDisabled");
  }
  if (lower.includes("kiosk") || lower.includes("not enabled")) {
    return t("attendance.kioskDisabled");
  }
  if (status === 401 || lower.includes("invalid pin") || lower.includes("pin no válido")) {
    return t("attendance.invalidPin");
  }
  if (status >= 500) return t("attendance.serverError");
  return raw || t("attendance.punchFailed");
}

/**
 * Mobile PIN role switch — same chrome as /attendance, Switch Role copy + EN/ESP.
 * Route: /attendance/role/:orgSlug
 */
export default function AttendanceRoleSwitchPage() {
  const { t, locale, setLocale } = useI18n();
  const navigate = useNavigate();
  const { orgSlug: orgSlugParam } = useParams();
  const routeSlug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);

  const [selectedSlug, setSelectedSlug] = useState("");
  const [orgs, setOrgs] = useState([]);
  const [orgsLoading, setOrgsLoading] = useState(!routeSlug);
  const slug = routeSlug || selectedSlug;

  const [pin, setPin] = useState("");
  const [pendingPin, setPendingPin] = useState("");
  const [phase, setPhase] = useState("pin"); // pin | pick | role | success
  const [selectionTree, setSelectionTree] = useState([]);
  const [pendingCategoryId, setPendingCategoryId] = useState(null);
  const [currentLabel, setCurrentLabel] = useState("");
  const [firstName, setFirstName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successLabel, setSuccessLabel] = useState("");
  const [branding, setBranding] = useState(null);

  const punchInFlightRef = useRef(false);
  const prevPinLenRef = useRef(0);
  const idempotencyKeyRef = useRef(null);
  const resetTimerRef = useRef(null);

  const pinDigits = useMemo(() => String(pin || "").replace(/\D/g, "").slice(0, PIN_LEN), [pin]);
  const isVeeWash = sanitizeSlug(slug) === "veewash";
  const logoSrc = attendanceLogoSrc(slug, branding?.logo_url);
  const tenantTitle = branding?.display_name || slug || t("attendance.switchRoleTitle");

  const selectedCategory =
    selectionTree.find((c) => Number(c.id) === Number(pendingCategoryId)) || null;
  const rolesForCategory = selectedCategory?.roles || [];

  const clearResetTimer = () => {
    if (resetTimerRef.current) {
      clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  };

  const resetToPin = useCallback(() => {
    clearResetTimer();
    setPin("");
    setPendingPin("");
    setPhase("pin");
    setSelectionTree([]);
    setPendingCategoryId(null);
    setCurrentLabel("");
    setFirstName("");
    setSuccessLabel("");
    setError("");
    idempotencyKeyRef.current = null;
    prevPinLenRef.current = 0;
    punchInFlightRef.current = false;
  }, []);

  useLayoutEffect(() => {
    return applyAttendancePwaManifest(routeSlug || selectedSlug);
  }, [routeSlug, selectedSlug]);

  useEffect(() => {
    if (routeSlug) return;
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const s = sanitizeSlug(saved);
      if (s && s !== "role") {
        navigate(`/attendance/role/${encodeURIComponent(s)}`, { replace: true });
      }
    } catch {
      /* ignore */
    }
  }, [routeSlug, navigate]);

  useEffect(() => {
    if (routeSlug) {
      try {
        localStorage.setItem(STORAGE_KEY, routeSlug);
      } catch {
        /* ignore */
      }
    }
  }, [routeSlug]);

  useEffect(() => {
    if (routeSlug) return undefined;
    let cancelled = false;
    (async () => {
      setOrgsLoading(true);
      try {
        const res = await getPublicOrganizationsForAttendance();
        if (cancelled) return;
        const list = Array.isArray(res.data?.organizations) ? res.data.organizations : [];
        setOrgs(list);
      } catch {
        if (!cancelled) setOrgs([]);
      } finally {
        if (!cancelled) setOrgsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [routeSlug]);

  useEffect(() => {
    if (!slug) {
      setBranding(null);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await getPublicOrgBranding(slug);
        if (cancelled) return;
        setBranding(res.data || null);
        applyAppIconFromOrganizationLogo(res.data?.logo_url);
      } catch {
        if (!cancelled) setBranding(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const openPickerFromPin = useCallback(
    async (digits) => {
      if (!slug || punchInFlightRef.current) return;
      const clean = String(digits || "").replace(/\D/g, "");
      if (clean.length !== PIN_LEN) return;
      punchInFlightRef.current = true;
      setLoading(true);
      setError("");
      try {
        const res = await attendancePinSwitchRole(slug, clean);
        const status = res?.status ?? 0;
        const data = res?.data;
        if (typeof data === "string" && data.trim().startsWith("<")) {
          console.error("[role-switch] Non-JSON response", {
            status,
            apiBase: getWashproApiBase(),
            slug,
          });
          setError(t("attendance.serverError"));
          setPin("");
          prevPinLenRef.current = 0;
          return;
        }
        const body = data && typeof data === "object" ? data : {};
        if (status >= 200 && status < 300 && body.ok && body.needs_selection) {
          setPendingPin(clean);
          setSelectionTree(Array.isArray(body.selection_tree) ? body.selection_tree : []);
          setFirstName(body.employee_first_name || "");
          setCurrentLabel(body.current_display_label || "");
          setPendingCategoryId(null);
          idempotencyKeyRef.current = createTaskTrackingSwitchIdempotencyKey();
          setPhase("pick");
          setPin("");
          prevPinLenRef.current = 0;
          return;
        }
        setError(mapSwitchRoleError(body, status, t));
        setPin("");
        prevPinLenRef.current = 0;
      } catch (e) {
        console.error("[role-switch] open failed", e?.message, getWashproApiBase());
        if (e?.code === "ECONNABORTED") {
          setError(t("attendance.timeout"));
        } else if (!e?.response) {
          setError(t("attendance.networkError"));
        } else {
          setError(mapSwitchRoleError(e?.response?.data, e?.response?.status, t));
        }
        setPin("");
        prevPinLenRef.current = 0;
      } finally {
        punchInFlightRef.current = false;
        setLoading(false);
      }
    },
    [slug, t],
  );

  useEffect(() => {
    if (!slug || phase !== "pin" || loading) return;
    const len = pinDigits.length;
    if (len < PIN_LEN) {
      prevPinLenRef.current = len;
      return;
    }
    if (len === PIN_LEN && prevPinLenRef.current < PIN_LEN) {
      prevPinLenRef.current = PIN_LEN;
      void openPickerFromPin(pinDigits);
    }
  }, [slug, pinDigits, openPickerFromPin, phase, loading]);

  const confirmRole = async (categoryId, roleId) => {
    if (!pendingPin || !categoryId || !roleId || punchInFlightRef.current) return;
    punchInFlightRef.current = true;
    setLoading(true);
    setError("");
    if (!idempotencyKeyRef.current) {
      idempotencyKeyRef.current = createTaskTrackingSwitchIdempotencyKey();
    }
    const key = idempotencyKeyRef.current;
    try {
      const res = await attendancePinSwitchRole(slug, pendingPin, {
        category_id: categoryId,
        role_id: roleId,
        idempotency_key: key,
      });
      const status = res?.status ?? 0;
      const body = res?.data && typeof res.data === "object" ? res.data : {};
      if (status >= 200 && status < 300 && body.ok) {
        setSuccessLabel(
          body.display_label || body.segment?.display_label || t("attendance.switchRoleSuccess"),
        );
        setPhase("success");
        clearResetTimer();
        resetTimerRef.current = setTimeout(() => resetToPin(), SUCCESS_RESET_MS);
        return;
      }
      setError(mapSwitchRoleError(body, status, t));
    } catch (e) {
      if (e?.code === "ECONNABORTED") {
        setError(t("attendance.timeout"));
      } else if (!e?.response) {
        setError(t("attendance.networkError"));
      } else {
        setError(mapSwitchRoleError(e?.response?.data, e?.response?.status, t));
      }
    } finally {
      punchInFlightRef.current = false;
      setLoading(false);
    }
  };

  const appendDigit = (d) => {
    if (loading || phase !== "pin") return;
    setError("");
    setPin((prev) => `${String(prev).replace(/\D/g, "")}${d}`.slice(0, PIN_LEN));
  };

  const pinBackspace = () => {
    if (loading || phase !== "pin") return;
    setPin((prev) => String(prev || "").slice(0, -1));
  };

  const pinClear = () => {
    if (loading || phase !== "pin") return;
    setPin("");
    prevPinLenRef.current = 0;
  };

  const goToSlugRoute = (newSlug) => {
    const s = sanitizeSlug(newSlug);
    if (s) navigate(`/attendance/role/${encodeURIComponent(s)}`, { replace: true });
  };

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
      <Box sx={{ position: "absolute", top: 12, right: 12, zIndex: 2 }}>
        <Stack direction="row" spacing={0.5} alignItems="center">
          {["en", "es"].map((code) => {
            const selected = locale === code;
            return (
              <Button
                key={code}
                size="small"
                onClick={() => setLocale(code)}
                sx={{
                  minWidth: 40,
                  px: 1,
                  py: 0.4,
                  fontSize: 11,
                  fontWeight: 800,
                  lineHeight: 1.2,
                  borderRadius: 1.5,
                  textTransform: "uppercase",
                  boxShadow: "none",
                  ...(selected
                    ? {
                        bgcolor: VW.cobalt,
                        color: "#fff",
                        "&:hover": { bgcolor: VW.blue },
                      }
                    : {
                        bgcolor: alpha("#fff", 0.9),
                        color: alpha(VW.navy, 0.55),
                        border: `1px solid ${alpha(VW.cobalt, 0.25)}`,
                        "&:hover": { bgcolor: alpha(VW.cobalt, 0.08) },
                      }),
                }}
              >
                {code === "en" ? t("attendance.localeEn") : t("attendance.localeEs")}
              </Button>
            );
          })}
        </Stack>
      </Box>

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
            {phase === "pin" ? t("attendance.switchRoleTitle") : t("attendance.enterPin")}
          </Typography>

          {!routeSlug && phase === "pin" ? (
            <Box sx={{ width: "100%" }}>
              {orgsLoading ? (
                <CircularProgress size={24} />
              ) : (
                <FormControl fullWidth size="small" sx={{ maxWidth: 360 }}>
                  <InputLabel id="role-switch-org">{t("attendance.selectCompany")}</InputLabel>
                  <Select
                    labelId="role-switch-org"
                    label={t("attendance.selectCompany")}
                    value={selectedSlug || ""}
                    onChange={(e) => {
                      const s = String(e.target.value);
                      setSelectedSlug(s);
                      resetToPin();
                      goToSlugRoute(s);
                    }}
                  >
                    {orgs.map((o) => (
                      <MenuItem key={o.slug} value={o.slug}>
                        {o.display_name || o.slug}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
            </Box>
          ) : null}

          {phase === "success" ? (
            <Stack spacing={1.5} alignItems="center" sx={{ py: 2, width: "100%" }}>
              <CheckCircle sx={{ fontSize: 56, color: "#059669" }} />
              <Typography variant="h6" fontWeight={700} textAlign="center" color="#152238">
                {firstName
                  ? t("attendance.switchRoleHi").replace("{name}", firstName)
                  : t("attendance.switchRoleSuccess")}
              </Typography>
              <Typography variant="body2" color="text.secondary" textAlign="center">
                {successLabel}
              </Typography>
            </Stack>
          ) : null}

          {phase === "pick" || phase === "role" ? (
            <Stack spacing={1.75} sx={{ width: "100%" }}>
              {error && phase === "pick" ? (
                <Alert severity="error" sx={{ width: "100%" }} onClose={() => setError("")}>
                  {error}
                </Alert>
              ) : null}
              <Box
                sx={{
                  p: 1.5,
                  borderRadius: 2.5,
                  bgcolor: alpha(VW.cobalt, 0.06),
                  border: `1px solid ${alpha(VW.cobalt, 0.16)}`,
                }}
              >
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  {firstName
                    ? t("attendance.switchRoleHi").replace("{name}", firstName)
                    : t("attendance.switchRoleCurrent")}
                </Typography>
                <Typography fontWeight={800} sx={{ mt: 0.25 }}>
                  {currentLabel || "—"}
                </Typography>
              </Box>

              <Typography fontWeight={800}>{t("attendance.selectCategoryTitle")}</Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
                {selectionTree.map((cat) => (
                  <Button
                    key={cat.id}
                    disabled={loading}
                    onClick={() => {
                      setPendingCategoryId(cat.id);
                      setPhase("role");
                    }}
                    sx={{
                      textTransform: "none",
                      fontWeight: 800,
                      py: 1.6,
                      borderRadius: 2.5,
                      border: "2px solid",
                      borderColor:
                        Number(pendingCategoryId) === Number(cat.id)
                          ? VW.cobalt
                          : alpha(VW.cobalt, 0.2),
                      bgcolor:
                        Number(pendingCategoryId) === Number(cat.id)
                          ? alpha(VW.cobalt, 0.12)
                          : "#fff",
                      color: VW.navy,
                    }}
                  >
                    {cat.name}
                  </Button>
                ))}
              </Box>

              <Button
                onClick={resetToPin}
                disabled={loading}
                sx={{ textTransform: "none", fontWeight: 700 }}
              >
                {t("attendance.switchRoleCancel")}
              </Button>
            </Stack>
          ) : null}

          {phase === "pin" ? (
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
                      boxShadow:
                        i < pinDigits.length && isVeeWash
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

              <Button
                component={Link}
                to={
                  slug
                    ? `/attendance/maintenance/${encodeURIComponent(slug)}`
                    : "/attendance/maintenance"
                }
                fullWidth
                variant="contained"
                disabled={!slug}
                sx={{
                  mt: 1,
                  textTransform: "none",
                  fontWeight: 800,
                  minHeight: 48,
                  borderRadius: 2.5,
                  maxWidth: 300,
                }}
              >
                {t("attendance.maintenanceTasks")}
              </Button>
            </>
          ) : null}
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
      </Stack>

      <Dialog
        open={phase === "role"}
        onClose={() => {
          if (loading) return;
          setPhase("pick");
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ fontWeight: 800 }}>{t("attendance.selectRoleTitle")}</DialogTitle>
        <DialogContent>
          {error ? (
            <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>
              {error}
            </Alert>
          ) : null}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5, pt: 0.5 }}>
            {selectedCategory?.name || ""}
          </Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
            {rolesForCategory.map((role) => (
              <Button
                key={role.role_id || role.id}
                disabled={loading || !pendingCategoryId}
                onClick={() => confirmRole(pendingCategoryId, role.role_id)}
                variant="outlined"
                sx={{
                  textTransform: "none",
                  fontWeight: 800,
                  py: 1.8,
                  borderRadius: 2.5,
                  ...roleChoiceButtonSx(role.role_name),
                }}
              >
                {loading ? <CircularProgress size={22} color="inherit" /> : role.role_name}
              </Button>
            ))}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button disabled={loading} onClick={() => setPhase("pick")}>
            Back
          </Button>
          <Button disabled={loading} onClick={resetToPin}>
            {t("attendance.switchRoleCancel")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
