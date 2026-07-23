import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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
import {
  AssignmentTurnedIn,
  Backspace,
  Inventory2,
  SwapHoriz,
} from "@mui/icons-material";
import {
  attendancePinHub,
  authAttendancePinUnlock,
  getPublicOrgBranding,
  getPublicOrganizationsForAttendance,
  setAuthSession,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { saveMtlPinSession } from "../utils/maintenanceTaskListHelpers";
import {
  clearPinHubSession,
  loadPinHubSession,
  savePinHubSession,
} from "../utils/pinHubSession";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";

const PIN_LEN = 4;
const STORAGE_KEY = "washpro_attendance_org_slug";
const VEEWASH_ATTENDANCE_LOGO = VEEWASH_LOGO_URL;

const VW = {
  navy: "#16192b",
  blue: "#2d3d9c",
  cobalt: "#4865ee",
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

function digitKeySx() {
  return {
    minHeight: { xs: 52, sm: 48 },
    fontSize: "1.25rem",
    fontWeight: 700,
    borderRadius: 2,
    color: VW.navy,
    border: `1px solid ${alpha(VW.blue, 0.22)}`,
    bgcolor: alpha("#fff", 0.92),
    "&:hover": { bgcolor: alpha(VW.cobalt, 0.12) },
    "&.Mui-disabled": { opacity: 0.45 },
  };
}

const FEATURE_META = {
  switch_role: {
    title: "Switch Role",
    subtitle: "Change category & role while clocked in",
    icon: SwapHoriz,
    color: "#2d3d9c",
  },
  checklist: {
    title: "End-of-day checklist",
    subtitle: "Maintenance task list",
    icon: AssignmentTurnedIn,
    color: "#0f766e",
  },
  inventory: {
    title: "Inventory",
    subtitle: "Open inventory with your PIN",
    icon: Inventory2,
    color: "#0e7490",
  },
};

/**
 * Phone PIN hub — one route for Switch Role, Checklist, Inventory (permission-gated).
 * Route: /pin/:orgSlug
 */
export default function EmployeePinHubPage({ onLoggedIn }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { orgSlug: orgSlugParam } = useParams();
  const routeSlug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);

  const [selectedSlug, setSelectedSlug] = useState("");
  const [orgs, setOrgs] = useState([]);
  const [orgsLoading, setOrgsLoading] = useState(!routeSlug);
  const slug = routeSlug || selectedSlug;

  const [pin, setPin] = useState("");
  const [phase, setPhase] = useState("pin"); // pin | menu
  const [hub, setHub] = useState(null);
  const [loading, setLoading] = useState(false);
  const [featureLoading, setFeatureLoading] = useState("");
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);

  const punchInFlightRef = useRef(false);
  const prevPinLenRef = useRef(0);

  const pinClean = useMemo(() => String(pin || "").replace(/\D/g, "").slice(0, PIN_LEN), [pin]);
  const logoSrc = attendanceLogoSrc(slug, branding?.logo_url);

  const allowedFeatures = useMemo(() => {
    const features = hub?.features || {};
    return ["switch_role", "checklist", "inventory"].filter((id) => features?.[id]?.allowed);
  }, [hub]);

  useLayoutEffect(() => {
    return applyAttendancePwaManifest(routeSlug || selectedSlug, "hub");
  }, [routeSlug, selectedSlug]);

  useEffect(() => {
    if (routeSlug) return;
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const s = sanitizeSlug(saved);
      if (s && s !== "role" && s !== "maintenance" && s !== "pin") {
        navigate(`/pin/${encodeURIComponent(s)}`, { replace: true });
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
        setOrgs(Array.isArray(res.data?.organizations) ? res.data.organizations : []);
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

  useEffect(() => {
    if (!slug) return;
    const existing = loadPinHubSession();
    if (!existing || existing.organization_slug !== slug) return;
    setHub(existing);
    setPhase("menu");
  }, [slug]);

  const openHubFromPin = useCallback(
    async (digits) => {
      if (!slug || punchInFlightRef.current) return;
      const clean = String(digits || "").replace(/\D/g, "");
      if (clean.length !== PIN_LEN) return;
      punchInFlightRef.current = true;
      setLoading(true);
      setError("");
      try {
        const res = await attendancePinHub(slug, clean);
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (res?.status >= 200 && res?.status < 300 && body.ok) {
          const sess = {
            token: body.token,
            pin: clean,
            organization_slug: body.organization_slug || slug,
            organization_id: body.organization_id,
            employee_id: body.employee_id,
            employee_name: body.employee_name,
            employee_first_name: body.employee_first_name,
            features: body.features || {},
            maintenance_token: body.maintenance_token || null,
            expires_in_seconds: body.expires_in_seconds,
          };
          savePinHubSession(sess);
          setHub(sess);
          setPhase("menu");
          setPin("");
          prevPinLenRef.current = 0;
          return;
        }
        setError(body.error || t("attendance.invalidPin") || "Invalid PIN");
        setPin("");
        prevPinLenRef.current = 0;
      } catch (e) {
        setError(e?.response?.data?.error || e?.message || "Could not open PIN menu");
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
    if (phase !== "pin") return;
    if (pinClean.length !== PIN_LEN) {
      prevPinLenRef.current = pinClean.length;
      return;
    }
    if (prevPinLenRef.current === PIN_LEN) return;
    prevPinLenRef.current = PIN_LEN;
    openHubFromPin(pinClean);
  }, [pinClean, phase, openHubFromPin]);

  const pinDigit = (d) => {
    if (loading || phase !== "pin") return;
    setError("");
    setPin((p) => `${String(p || "").replace(/\D/g, "")}${d}`.slice(0, PIN_LEN));
  };
  const pinBackspace = () => {
    setError("");
    setPin((p) => String(p || "").replace(/\D/g, "").slice(0, -1));
    prevPinLenRef.current = 0;
  };
  const pinClear = () => {
    setError("");
    setPin("");
    prevPinLenRef.current = 0;
  };

  const lockAgain = () => {
    clearPinHubSession();
    setHub(null);
    setPhase("pin");
    setPin("");
    setError("");
    setFeatureLoading("");
    prevPinLenRef.current = 0;
  };

  const openFeature = async (featureId) => {
    if (!hub || !slug || featureLoading) return;
    setError("");
    setFeatureLoading(featureId);
    try {
      if (featureId === "switch_role") {
        navigate(`/attendance/role/${encodeURIComponent(slug)}?from=hub`);
        return;
      }
      if (featureId === "checklist") {
        if (hub.maintenance_token) {
          saveMtlPinSession({
            token: hub.maintenance_token,
            organization_slug: hub.organization_slug || slug,
            organization_id: hub.organization_id,
            employee_id: hub.employee_id,
            employee_name: hub.employee_name,
            employee_first_name: hub.employee_first_name,
          });
        }
        navigate(`/attendance/maintenance/${encodeURIComponent(slug)}?from=hub`);
        return;
      }
      if (featureId === "inventory") {
        const res = await authAttendancePinUnlock(slug, hub.pin);
        const payload = res?.data || {};
        if (!payload?.token || !payload?.user) {
          throw new Error(payload?.error || "Could not unlock inventory");
        }
        setAuthSession(payload);
        onLoggedIn?.(payload.user);
        navigate("/inventory", { replace: true });
        return;
      }
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not open feature");
    } finally {
      setFeatureLoading("");
    }
  };

  const goToSlugRoute = (s) => {
    const clean = sanitizeSlug(s);
    if (!clean) return;
    navigate(`/pin/${encodeURIComponent(clean)}`, { replace: true });
  };

  return (
    <Box
      sx={{
        minHeight: "100dvh",
        bgcolor: VW.mist,
        background: `linear-gradient(165deg, ${VW.mist} 0%, #e8eeff 45%, ${alpha(VW.cobalt, 0.12)} 100%)`,
        px: 2,
        py: { xs: 2.5, sm: 4 },
        display: "flex",
        justifyContent: "center",
      }}
    >
      <Paper
        elevation={0}
        sx={{
          width: "100%",
          maxWidth: 420,
          borderRadius: 3,
          p: { xs: 2.5, sm: 3 },
          border: `1px solid ${alpha(VW.blue, 0.14)}`,
          bgcolor: alpha("#fff", 0.94),
        }}
      >
        <Stack spacing={2.25} alignItems="center">
          {logoSrc ? (
            <Box
              component="img"
              src={logoSrc}
              alt=""
              sx={{ height: 56, width: "auto", maxWidth: "70%", objectFit: "contain" }}
            />
          ) : (
            <TenantLogo size={56} />
          )}

          <Typography variant="h5" sx={{ fontWeight: 800, color: VW.navy, textAlign: "center" }}>
            {phase === "menu" ? `Hi${hub?.employee_first_name ? `, ${hub.employee_first_name}` : ""}` : "PIN Menu"}
          </Typography>
          <Typography variant="body2" color="text.secondary" textAlign="center">
            {phase === "menu"
              ? "Choose a feature you have access to"
              : "Enter your attendance PIN"}
          </Typography>

          {!routeSlug && (
            <FormControl fullWidth size="small">
              <InputLabel id="pin-hub-org">Organization</InputLabel>
              <Select
                labelId="pin-hub-org"
                label="Organization"
                value={selectedSlug}
                disabled={orgsLoading}
                onChange={(e) => goToSlugRoute(e.target.value)}
              >
                {(orgs || []).map((o) => (
                  <MenuItem key={o.slug} value={o.slug}>
                    {o.display_name || o.slug}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}

          {error ? (
            <Alert severity="error" sx={{ width: "100%" }} onClose={() => setError("")}>
              {error}
            </Alert>
          ) : null}

          {phase === "pin" && (
            <>
              <Stack direction="row" spacing={1.25} justifyContent="center">
                {Array.from({ length: PIN_LEN }).map((_, i) => (
                  <Box
                    key={i}
                    sx={{
                      width: 14,
                      height: 14,
                      borderRadius: "50%",
                      bgcolor: i < pinClean.length ? VW.blue : alpha(VW.navy, 0.15),
                    }}
                  />
                ))}
              </Stack>

              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, 1fr)",
                  gap: 1,
                  width: "100%",
                  maxWidth: 280,
                }}
              >
                {["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "⌫"].map((key) => {
                  if (key === "C") {
                    return (
                      <Button key={key} disabled={loading || !pinClean} onClick={pinClear} sx={digitKeySx()}>
                        C
                      </Button>
                    );
                  }
                  if (key === "⌫") {
                    return (
                      <IconButton
                        key={key}
                        disabled={loading || !pinClean}
                        onClick={pinBackspace}
                        sx={digitKeySx()}
                      >
                        <Backspace fontSize="small" />
                      </IconButton>
                    );
                  }
                  return (
                    <Button
                      key={key}
                      disabled={loading || !slug}
                      onClick={() => pinDigit(key)}
                      sx={digitKeySx()}
                    >
                      {key}
                    </Button>
                  );
                })}
              </Box>
              {loading ? <CircularProgress size={28} /> : null}
            </>
          )}

          {phase === "menu" && (
            <Stack spacing={1.25} sx={{ width: "100%" }}>
              {allowedFeatures.map((id) => {
                const meta = FEATURE_META[id];
                const Icon = meta.icon;
                const busy = featureLoading === id;
                return (
                  <Button
                    key={id}
                    fullWidth
                    variant="outlined"
                    disabled={!!featureLoading}
                    onClick={() => openFeature(id)}
                    sx={{
                      justifyContent: "flex-start",
                      textAlign: "left",
                      py: 1.5,
                      px: 1.75,
                      borderRadius: 2,
                      borderColor: alpha(meta.color, 0.35),
                      bgcolor: alpha(meta.color, 0.06),
                      color: VW.navy,
                      textTransform: "none",
                      "&:hover": {
                        borderColor: meta.color,
                        bgcolor: alpha(meta.color, 0.12),
                      },
                    }}
                    startIcon={
                      busy ? (
                        <CircularProgress size={22} />
                      ) : (
                        <Icon sx={{ color: meta.color }} />
                      )
                    }
                  >
                    <Box>
                      <Typography sx={{ fontWeight: 700, lineHeight: 1.2 }}>{meta.title}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {meta.subtitle}
                      </Typography>
                    </Box>
                  </Button>
                );
              })}

              <Button onClick={lockAgain} color="inherit" sx={{ textTransform: "none", mt: 0.5 }}>
                Lock / switch person
              </Button>
            </Stack>
          )}

          <Typography variant="caption" color="text.secondary" textAlign="center">
            Shared-tablet clock in/out stays on the attendance kiosk.
          </Typography>
          <Button component={Link} to={slug ? `/attendance/${slug}` : "/attendance"} size="small" sx={{ textTransform: "none" }}>
            Tablet attendance
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}
