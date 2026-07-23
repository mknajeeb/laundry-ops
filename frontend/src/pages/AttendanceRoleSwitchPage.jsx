import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
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

function VeeWashWordmark() {
  return (
    <Typography
      component="div"
      sx={{
        fontWeight: 800,
        fontSize: { xs: "1.85rem", sm: "2.1rem" },
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
  return {
    minHeight: { xs: 56, sm: 52 },
    fontSize: "1.35rem",
    fontWeight: 700,
    borderRadius: 2.5,
    color: VW.navy,
    py: 0.5,
    borderWidth: veewash ? 2 : 1,
    borderStyle: "solid",
    borderColor: alpha(VW.cobalt, veewash ? 0.35 : 0.25),
    bgcolor: "#fff",
    "&:hover": {
      borderColor: VW.cobalt,
      bgcolor: alpha(VW.cobalt, 0.08),
    },
    "&.Mui-disabled": { opacity: 0.45 },
  };
}

function utilityKeySx() {
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
  };
}

/**
 * Mobile PIN role switch — same attendance look, modern one-screen Category + Role picker.
 * Does not clock in/out. Route: /attendance/role/:orgSlug
 */
export default function AttendanceRoleSwitchPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { orgSlug: orgSlugParam } = useParams();
  const routeSlug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);

  const [selectedSlug, setSelectedSlug] = useState("");
  const [orgs, setOrgs] = useState([]);
  const [orgsLoading, setOrgsLoading] = useState(!routeSlug);
  const slug = routeSlug || selectedSlug;

  const [pin, setPin] = useState("");
  const [pendingPin, setPendingPin] = useState("");
  const [phase, setPhase] = useState("pin"); // pin | pick | success
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
  const tenantTitle = branding?.display_name || slug || "Role switch";

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
    applyAttendancePwaManifest();
  }, []);

  useEffect(() => {
    if (!routeSlug) {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) setSelectedSlug(sanitizeSlug(saved));
      } catch {
        /* ignore */
      }
    }
  }, [routeSlug]);

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
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (status >= 200 && status < 300 && body.ok && body.needs_selection) {
          setPendingPin(clean);
          setSelectionTree(Array.isArray(body.selection_tree) ? body.selection_tree : []);
          setFirstName(body.employee_first_name || "");
          setCurrentLabel(body.current_display_label || "");
          const curCat = body.current_category_id;
          const tree = Array.isArray(body.selection_tree) ? body.selection_tree : [];
          const hasCur = tree.some((c) => Number(c.id) === Number(curCat));
          setPendingCategoryId(hasCur ? Number(curCat) : tree[0]?.id ?? null);
          idempotencyKeyRef.current = createTaskTrackingSwitchIdempotencyKey();
          setPhase("pick");
          setPin("");
          prevPinLenRef.current = 0;
          return;
        }
        setError(body.error || "Could not start role change");
        setPin("");
        prevPinLenRef.current = 0;
      } catch (e) {
        console.error("[role-switch] open failed", e?.message, getWashproApiBase());
        setError(e?.response?.data?.error || e?.message || "Could not start role change");
        setPin("");
        prevPinLenRef.current = 0;
      } finally {
        punchInFlightRef.current = false;
        setLoading(false);
      }
    },
    [slug],
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
        setSuccessLabel(body.display_label || body.segment?.display_label || "Role updated");
        setPhase("success");
        clearResetTimer();
        resetTimerRef.current = setTimeout(() => resetToPin(), SUCCESS_RESET_MS);
        return;
      }
      setError(body.error || "Could not change role");
    } catch (e) {
      const msg =
        e?.code === "ECONNABORTED"
          ? "The role change is taking longer than expected and may already have completed. Wait a moment, then try again if needed."
          : e?.response?.data?.error || e?.message || "Could not change role";
      setError(msg);
    } finally {
      punchInFlightRef.current = false;
      setLoading(false);
    }
  };

  const appendDigit = (d) => {
    if (loading || phase !== "pin") return;
    setError("");
    setPin((prev) => `${prev}${d}`.replace(/\D/g, "").slice(0, PIN_LEN));
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
      }}
    >
      <Paper
        elevation={0}
        sx={{
          position: "relative",
          zIndex: 1,
          width: "100%",
          maxWidth: 440,
          p: { xs: 2.5, sm: 3 },
          borderRadius: 4,
          border: "1px solid",
          borderColor: isVeeWash ? alpha(VW.cobalt, 0.22) : alpha("#2d3d9c", 0.12),
          boxShadow: isVeeWash
            ? `0 28px 64px -24px ${alpha(VW.blue, 0.35)}`
            : "0 24px 60px -28px rgba(45, 61, 156, 0.28)",
          background: "#fff",
        }}
      >
        <Stack spacing={1.5} alignItems="center" sx={{ width: "100%" }}>
          {logoSrc ? (
            <Box
              component="img"
              src={logoSrc}
              alt=""
              sx={{
                width: "min(180px, 52vw)",
                height: "auto",
                maxHeight: 96,
                objectFit: "contain",
              }}
            />
          ) : (
            <TenantLogo logoUrl={branding?.logo_url} sx={{ width: 80, height: 80 }} />
          )}
          {isVeeWash ? <VeeWashWordmark /> : (
            <Typography variant="h6" fontWeight={800} textAlign="center">
              {tenantTitle}
            </Typography>
          )}
          <Typography
            variant="subtitle2"
            fontWeight={700}
            sx={{
              color: alpha(VW.blue, 0.8),
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              fontSize: "0.7rem",
            }}
          >
            Change role
          </Typography>

          {!routeSlug && phase === "pin" ? (
            <Box sx={{ width: "100%" }}>
              {orgsLoading ? (
                <CircularProgress size={24} />
              ) : (
                <FormControl fullWidth size="small">
                  <InputLabel id="role-switch-org">Company</InputLabel>
                  <Select
                    labelId="role-switch-org"
                    label="Company"
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

          {error ? (
            <Alert severity="warning" sx={{ width: "100%" }} onClose={() => setError("")}>
              {error}
            </Alert>
          ) : null}

          {phase === "success" ? (
            <Stack spacing={1.25} alignItems="center" sx={{ py: 2, width: "100%" }}>
              <CheckCircle sx={{ fontSize: 56, color: "#059669" }} />
              <Typography variant="h6" fontWeight={800} textAlign="center">
                {firstName ? `Got it, ${firstName}` : "Role updated"}
              </Typography>
              <Typography color="text.secondary" textAlign="center" fontWeight={600}>
                {successLabel}
              </Typography>
            </Stack>
          ) : null}

          {phase === "pick" ? (
            <Stack spacing={1.75} sx={{ width: "100%" }}>
              <Box
                sx={{
                  p: 1.5,
                  borderRadius: 2.5,
                  bgcolor: alpha(VW.cobalt, 0.06),
                  border: `1px solid ${alpha(VW.cobalt, 0.16)}`,
                }}
              >
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  {firstName ? `Hi ${firstName}` : "Current assignment"}
                </Typography>
                <Typography fontWeight={800} sx={{ mt: 0.25 }}>
                  {currentLabel || "No role selected yet"}
                </Typography>
              </Box>

              <Typography fontWeight={800}>Category</Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 1,
                }}
              >
                {selectionTree.map((cat) => {
                  const selected = Number(pendingCategoryId) === Number(cat.id);
                  return (
                    <Button
                      key={cat.id}
                      disabled={loading}
                      onClick={() => setPendingCategoryId(cat.id)}
                      sx={{
                        textTransform: "none",
                        fontWeight: 800,
                        py: 1.6,
                        borderRadius: 2.5,
                        border: "2px solid",
                        borderColor: selected ? VW.cobalt : alpha(VW.cobalt, 0.2),
                        bgcolor: selected ? alpha(VW.cobalt, 0.12) : "#fff",
                        color: VW.navy,
                      }}
                    >
                      {cat.name}
                    </Button>
                  );
                })}
              </Box>

              <Typography fontWeight={800}>Role</Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 1,
                }}
              >
                {rolesForCategory.map((role) => (
                  <Button
                    key={role.role_id || role.id}
                    disabled={loading || !pendingCategoryId}
                    onClick={() => confirmRole(pendingCategoryId, role.role_id)}
                    variant="contained"
                    disableElevation
                    sx={{
                      textTransform: "none",
                      fontWeight: 800,
                      py: 1.8,
                      borderRadius: 2.5,
                      bgcolor: VW.cobalt,
                      "&:hover": { bgcolor: VW.blue },
                    }}
                  >
                    {loading ? <CircularProgress size={22} color="inherit" /> : role.role_name}
                  </Button>
                ))}
              </Box>

              <Button
                onClick={resetToPin}
                disabled={loading}
                sx={{ textTransform: "none", fontWeight: 700 }}
              >
                Cancel
              </Button>
            </Stack>
          ) : null}

          {phase === "pin" ? (
            <Stack spacing={1.5} alignItems="center" sx={{ width: "100%" }}>
              <Typography color="text.secondary" textAlign="center">
                Enter your attendance PIN to change category and role.
              </Typography>
              <Stack direction="row" spacing={1.25} sx={{ my: 0.5 }}>
                {Array.from({ length: PIN_LEN }).map((_, i) => (
                  <Box
                    key={i}
                    sx={{
                      width: 14,
                      height: 14,
                      borderRadius: "50%",
                      bgcolor: i < pinDigits.length ? VW.cobalt : alpha(VW.cobalt, 0.2),
                    }}
                  />
                ))}
              </Stack>
              <Box
                sx={{
                  width: "100%",
                  display: "grid",
                  gridTemplateColumns: "repeat(3, 1fr)",
                  gap: 1,
                }}
              >
                {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => (
                  <Button
                    key={d}
                    variant="outlined"
                    disabled={loading || !slug}
                    onClick={() => appendDigit(d)}
                    sx={digitKeySx(isVeeWash)}
                  >
                    {d}
                  </Button>
                ))}
                <IconButton
                  disabled={loading || !pinDigits.length}
                  onClick={pinBackspace}
                  sx={{ ...utilityKeySx(), borderRadius: 2.5 }}
                >
                  <Backspace />
                </IconButton>
                <Button
                  variant="outlined"
                  disabled={loading || !slug}
                  onClick={() => appendDigit(0)}
                  sx={digitKeySx(isVeeWash)}
                >
                  0
                </Button>
                <Button
                  variant="outlined"
                  disabled={loading || !pinDigits.length}
                  onClick={pinClear}
                  sx={utilityKeySx()}
                >
                  {t("kiosk.clearPin") || "Clear"}
                </Button>
              </Box>
              {loading ? <CircularProgress size={28} /> : null}
            </Stack>
          ) : null}
        </Stack>
      </Paper>
    </Box>
  );
}
