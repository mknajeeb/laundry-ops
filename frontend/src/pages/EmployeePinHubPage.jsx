import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
import {
  AccessTime,
  AssignmentTurnedIn,
  Backspace,
  Inventory2,
  Login,
  Logout,
  RequestQuote,
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
import {
  OpsLauncherEmpty,
  OpsLauncherGrid,
  OpsMobileShell,
  OpsTopBar,
  OPS_MOBILE,
  ROLE_CLOCK_IN_FIRST_MESSAGE,
  buildPinLauncherTiles,
} from "../opsMobile";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { saveMtlPinSession } from "../utils/maintenanceTaskListHelpers";
import {
  clearPinHubAppSession,
  clearPinHubSession,
  loadPinHubSession,
  markPinHubAppSession,
  savePinHubSession,
} from "../utils/pinHubSession";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";

const PIN_LEN = 4;
const STORAGE_KEY = "washpro_attendance_org_slug";
const VEEWASH_ATTENDANCE_LOGO = VEEWASH_LOGO_URL;

const VW = {
  navy: OPS_MOBILE.navy,
  blue: OPS_MOBILE.blue,
  cobalt: OPS_MOBILE.cobalt,
  mist: OPS_MOBILE.mist,
};

const TILE_ICONS = {
  clock: AccessTime,
  clock_in: Login,
  clock_out: Logout,
  role: SwapHoriz,
  tasks: AssignmentTurnedIn,
  stock: Inventory2,
  revenue: RequestQuote,
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

function iconForTile(tile) {
  if (tile.id === "clock") {
    if (tile.label === "Clock Out") return TILE_ICONS.clock_out;
    if (tile.label === "Clock In") return TILE_ICONS.clock_in;
    return TILE_ICONS.clock;
  }
  return TILE_ICONS[tile.iconKey] || TILE_ICONS.tasks;
}

/**
 * Phone PIN hub — launcher for Clock, Role, Tasks, Stock (permission/state gated).
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

  const launcherTiles = useMemo(() => {
    const built = buildPinLauncherTiles({
      features: hub?.features,
      featureOrder: hub?.feature_order,
      attendance: hub?.attendance,
    });
    return built.map((tile) => ({
      ...tile,
      icon: iconForTile(tile),
    }));
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

  const applyHubBody = useCallback(
    (body, cleanPin) => {
      const sess = {
        token: body.token,
        pin: cleanPin,
        organization_slug: body.organization_slug || slug,
        organization_id: body.organization_id,
        employee_id: body.employee_id,
        employee_name: body.employee_name,
        employee_first_name: body.employee_first_name,
        features: body.features || {},
        feature_order: Array.isArray(body.feature_order) ? body.feature_order : undefined,
        maintenance_token: body.maintenance_token || null,
        expires_in_seconds: body.expires_in_seconds,
        attendance: body.attendance || null,
      };
      savePinHubSession(sess);
      setHub(sess);
      setPhase("menu");
      setPin("");
      prevPinLenRef.current = 0;
    },
    [slug],
  );

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
          applyHubBody(body, clean);
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
    [slug, t, applyHubBody],
  );

  // Restore hub session and always refresh so Current Role updates after role switch.
  useEffect(() => {
    if (!slug) return undefined;
    const existing = loadPinHubSession();
    if (!existing || existing.organization_slug !== slug) return undefined;
    setHub(existing);
    setPhase("menu");
    if (!existing.pin) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await attendancePinHub(slug, existing.pin);
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (!cancelled && res?.status >= 200 && res?.status < 300 && body.ok) {
          applyHubBody(body, existing.pin);
        }
      } catch {
        /* keep cached session */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, applyHubBody]);

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

  const lockSession = () => {
    // Clears PIN hub unlock only — does not call punch APIs or change shift data.
    clearPinHubSession();
    clearPinHubAppSession();
    setHub(null);
    setPhase("pin");
    setPin("");
    setError("");
    prevPinLenRef.current = 0;
  };

  const openFeature = async (tile) => {
    const featureId = tile?.id || tile;
    if (!hub || !slug || featureLoading) return;
    setError("");
    setFeatureLoading(featureId);
    try {
      if (featureId === "clock") {
        if (tile?.disabled || hub?.attendance?.allow_clock_from_hub === false) {
          return;
        }
        navigate(`/attendance/${encodeURIComponent(slug)}?from=hub`);
        return;
      }
      if (featureId === "switch_role") {
        if (tile?.requiresClockIn || hub?.attendance?.clocked_in !== true) {
          setError(ROLE_CLOCK_IN_FIRST_MESSAGE);
          return;
        }
        // Full-screen shared flow on /attendance/role (not an in-hub dialog).
        navigate(`/attendance/role/${encodeURIComponent(slug)}?from=hub`);
        return;
      }
      if (featureId === "checklist") {
        if (tile?.disabled || hub?.features?.checklist?.disabled) {
          return;
        }
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
        if (tile?.disabled || hub?.features?.inventory?.disabled) {
          return;
        }
        const res = await authAttendancePinUnlock(slug, hub.pin, {
          hubToken: hub.token,
          pinHubModule: "inventory",
        });
        const payload = res?.data || {};
        if (!payload?.token || !payload?.user) {
          throw new Error(payload?.error || "Could not unlock inventory");
        }
        markPinHubAppSession(slug);
        setAuthSession(payload);
        onLoggedIn?.(payload.user);
        navigate("/inventory", { replace: true });
        return;
      }
      if (featureId === "revenue_cost") {
        if (tile?.disabled || hub?.features?.revenue_cost?.disabled) {
          return;
        }
        const res = await authAttendancePinUnlock(slug, hub.pin, {
          hubToken: hub.token,
          pinHubModule: "revenue_cost",
        });
        const payload = res?.data || {};
        if (!payload?.token || !payload?.user) {
          throw new Error(payload?.error || "Could not unlock Revenue & Cost");
        }
        markPinHubAppSession(slug);
        setAuthSession(payload);
        onLoggedIn?.(payload.user);
        navigate("/finance/daily-revenue-cost", { replace: true });
        return;
      }
    } catch (e) {
      setError(
        e?.response?.data?.error ||
          e?.message ||
          (!e?.response ? t("attendance.networkError") : "Could not open feature"),
      );
    } finally {
      setFeatureLoading("");
    }
  };

  const goToSlugRoute = (s) => {
    const clean = sanitizeSlug(s);
    if (!clean) return;
    navigate(`/pin/${encodeURIComponent(clean)}`, { replace: true });
  };

  const identity =
    phase === "menu"
      ? (hub?.employee_first_name || hub?.employee_name || "").trim()
      : "";

  return (
    <OpsMobileShell>
      <Paper
        elevation={0}
        sx={{
          width: "100%",
          borderRadius: `${OPS_MOBILE.radius.card}px`,
          p: { xs: 2, sm: 2.5 },
          bgcolor: alpha("#fff", 0.96),
          boxShadow: `0 8px 28px -16px ${alpha(VW.navy, 0.35)}`,
        }}
      >
        <Stack spacing={2} alignItems="stretch">
          {phase === "menu" ? (
            <OpsTopBar
              identity={identity}
              logoSrc={logoSrc}
              onLock={lockSession}
              lockLabel="Lock"
            />
          ) : (
            <Stack spacing={1.25} alignItems="center">
              {logoSrc ? (
                <Box
                  component="img"
                  src={logoSrc}
                  alt=""
                  sx={{ height: 48, width: "auto", maxWidth: "70%", objectFit: "contain" }}
                />
              ) : (
                <TenantLogo size={48} />
              )}
              <Typography
                sx={{
                  fontWeight: 800,
                  fontSize: OPS_MOBILE.type.title,
                  color: VW.navy,
                  textAlign: "center",
                }}
              >
                PIN
              </Typography>
            </Stack>
          )}

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
            <Alert
              severity={error === ROLE_CLOCK_IN_FIRST_MESSAGE ? "info" : "error"}
              sx={{ width: "100%" }}
              onClose={() => setError("")}
            >
              {error}
            </Alert>
          ) : null}

          {phase === "menu" ? (
            <Box sx={{ width: "100%", textAlign: "center", px: 0.5 }}>
              <Typography sx={{ fontWeight: 800, fontSize: "1rem", color: VW.navy }}>
                Current Role:{" "}
                {(hub?.attendance?.clocked_in && hub?.attendance?.current_display_label) || "—"}
              </Typography>
              {!hub?.attendance?.clocked_in ? (
                <Typography sx={{ mt: 0.25, fontWeight: 600, fontSize: "0.9rem", color: alpha(VW.navy, 0.72) }}>
                  Not clocked in
                </Typography>
              ) : null}
            </Box>
          ) : null}

          {phase === "pin" && (
            <Stack spacing={2} alignItems="center">
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
            </Stack>
          )}

          {phase === "menu" &&
            (launcherTiles.length > 0 ? (
              <OpsLauncherGrid
                tiles={launcherTiles}
                busyId={featureLoading}
                disabled={!!featureLoading}
                onSelect={openFeature}
              />
            ) : (
              <OpsLauncherEmpty onLock={lockSession} />
            ))}
        </Stack>
      </Paper>
    </OpsMobileShell>
  );
}
