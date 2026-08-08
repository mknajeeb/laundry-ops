import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
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
import { Backspace } from "@mui/icons-material";
import {
  attendancePinSwitchRole,
  createTaskTrackingSwitchIdempotencyKey,
  getPublicOrgBranding,
  getPublicOrganizationsForAttendance,
} from "../api";
import {
  OpsMobileShell,
  OpsSwitchRoleFlow,
  OPS_MOBILE,
} from "../opsMobile";
import { createSwitchRoleController } from "../opsMobile/createSwitchRoleController";
import { openRoleFlowEmployeeError } from "../opsMobile/switchRoleFlowHelpers";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";
import {
  clearPinHubAppSession,
  clearPinHubSession,
  loadPinHubSession,
  pinHubMenuPath,
  takePinHubPinForSlug,
} from "../utils/pinHubSession";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import TenantLogo from "../components/TenantLogo";

const PIN_LEN = 4;
const STORAGE_KEY = "washpro_attendance_org_slug";
const SUCCESS_DELAY_MS = 900;

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
  if (slug === "veewash") return VEEWASH_LOGO_URL;
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
    color: OPS_MOBILE.navy,
    border: `1px solid ${alpha(OPS_MOBILE.blue, 0.22)}`,
    bgcolor: alpha("#fff", 0.92),
    "&:hover": { bgcolor: alpha(OPS_MOBILE.cobalt, 0.12) },
    "&.Mui-disabled": { opacity: 0.45 },
  };
}

/**
 * Mobile PIN role switch — full-screen cards via shared OpsSwitchRoleFlow.
 * Routes: /attendance/role, /attendance/role/:orgSlug
 */
export default function AttendanceRoleSwitchPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const fromHub = searchParams.get("from") === "hub";
  const { orgSlug: orgSlugParam } = useParams();
  const routeSlug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);

  const [selectedSlug, setSelectedSlug] = useState("");
  const [orgs, setOrgs] = useState([]);
  const [orgsLoading, setOrgsLoading] = useState(!routeSlug);
  const slug = routeSlug || selectedSlug;

  const [pin, setPin] = useState("");
  const [pendingPin, setPendingPin] = useState("");
  // from=hub: skip PIN keypad flash — show opening until select/unavailable.
  const [phase, setPhase] = useState(fromHub ? "opening" : "pin"); // opening | pin | select | success | unavailable
  const [selectionTree, setSelectionTree] = useState([]);
  const [flowStep, setFlowStep] = useState("role"); // role | category
  const [roleId, setRoleId] = useState(null);
  const [categoryId, setCategoryId] = useState(null);
  const [currentCategoryId, setCurrentCategoryId] = useState(null);
  const [currentRoleId, setCurrentRoleId] = useState(null);
  const [firstName, setFirstName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [flowError, setFlowError] = useState("");
  const [pending, setPending] = useState(false);
  const [pendingCategoryId, setPendingCategoryId] = useState(null);
  const [successLabel, setSuccessLabel] = useState("");
  const [branding, setBranding] = useState(null);
  const [unavailableMessage, setUnavailableMessage] = useState(
    "Role change isn’t available right now.",
  );

  const punchInFlightRef = useRef(false);
  const prevPinLenRef = useRef(0);
  const hubPinUsedRef = useRef(false);
  const controllerRef = useRef(null);

  const pinDigits = useMemo(() => String(pin || "").replace(/\D/g, "").slice(0, PIN_LEN), [pin]);
  const logoSrc = attendanceLogoSrc(slug, branding?.logo_url);

  const goPinLauncher = useCallback(
    ({ lock = false } = {}) => {
      if (lock) {
        clearPinHubSession();
        clearPinHubAppSession();
      }
      navigate(pinHubMenuPath(slug), { replace: true });
    },
    [navigate, slug],
  );

  const onBack = useCallback(() => {
    // Preserve unlocked PIN hub session.
    navigate(pinHubMenuPath(slug), { replace: true });
  }, [navigate, slug]);

  const onLock = useCallback(() => {
    goPinLauncher({ lock: true });
  }, [goPinLauncher]);

  useLayoutEffect(() => {
    return applyAttendancePwaManifest(routeSlug || selectedSlug, "role");
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

  const applySelectionBody = useCallback((body, cleanPin) => {
    const tree = Array.isArray(body.selection_tree) ? body.selection_tree : [];
    setPendingPin(cleanPin);
    setSelectionTree(tree);
    setFirstName(body.employee_first_name || "");
    setCurrentCategoryId(
      body.current_category_id != null ? Number(body.current_category_id) : null,
    );
    setCurrentRoleId(body.current_role_id != null ? Number(body.current_role_id) : null);
    // Always open on the role list (Operator / Folder, …). Do not skip to category
    // just because a current role already exists — that felt like an intermediate screen.
    setRoleId(null);
    setCategoryId(null);
    setFlowStep("role");
    setFlowError("");
    setPending(false);
    setPendingCategoryId(null);
    setSuccessLabel("");
    setPhase("select");
    setPin("");
    prevPinLenRef.current = 0;
  }, []);

  const openPickerFromPin = useCallback(
    async (digits, opts = {}) => {
      if (!slug || punchInFlightRef.current) return;
      const clean = String(digits || "").replace(/\D/g, "");
      const hubToken = opts.hubToken ? String(opts.hubToken) : "";
      if (!hubToken && clean.length !== PIN_LEN) return;
      punchInFlightRef.current = true;
      setLoading(true);
      setError("");
      try {
        const res = await attendancePinSwitchRole(slug, clean, {
          ...(hubToken ? { hubToken } : {}),
        });
        const status = res?.status ?? 0;
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (status >= 200 && status < 300 && body.ok && body.needs_selection) {
          applySelectionBody(body, clean || "hub");
          return;
        }
        setUnavailableMessage(openRoleFlowEmployeeError(body, status));
        setPhase("unavailable");
        setPendingPin(clean || "hub");
        setFirstName(body.employee_first_name || loadPinHubSession()?.employee_first_name || "");
        setPin("");
        prevPinLenRef.current = 0;
      } catch (e) {
        setUnavailableMessage(
          openRoleFlowEmployeeError(e?.response?.data, e?.response?.status, {
            network: !e?.response,
            timeout: e?.code === "ECONNABORTED",
          }),
        );
        setPhase("unavailable");
        setPin("");
        prevPinLenRef.current = 0;
      } finally {
        punchInFlightRef.current = false;
        setLoading(false);
      }
    },
    [slug, applySelectionBody],
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

  /** From /pin hub: reuse hub_token (no second bcrypt); PIN kept only as local session glue. */
  useEffect(() => {
    if (!fromHub || !slug || hubPinUsedRef.current) return;
    if (phase !== "opening" && phase !== "pin") return;
    const hub = loadPinHubSession();
    const hubPin = takePinHubPinForSlug(slug);
    const hubToken = hub?.token && hub?.organization_slug === slug ? String(hub.token) : "";
    if (!hubToken && (!hubPin || hubPin.length !== PIN_LEN)) {
      // Stale hub navigation without session — show unavailable rather than blank dialog.
      hubPinUsedRef.current = true;
      setPhase("unavailable");
      return;
    }
    hubPinUsedRef.current = true;
    if (hub?.employee_first_name) setFirstName(hub.employee_first_name);
    void openPickerFromPin(hubPin || "", { hubToken });
  }, [fromHub, slug, phase, openPickerFromPin]);

  // Bind controller whenever selection context is ready.
  useEffect(() => {
    if (phase !== "select" || !pendingPin || !slug) {
      controllerRef.current = null;
      return undefined;
    }
    const hubToken =
      fromHub && loadPinHubSession()?.organization_slug === slug
        ? String(loadPinHubSession()?.token || "")
        : "";
    const controller = createSwitchRoleController({
      selectionTree,
      currentCategoryId,
      currentRoleId,
      pin: pendingPin === "hub" ? "" : pendingPin,
      hubToken,
      slug,
      switchRoleApi: attendancePinSwitchRole,
      createIdempotencyKey: createTaskTrackingSwitchIdempotencyKey,
      successDelayMs: SUCCESS_DELAY_MS,
      onSuccess: () => {
        goPinLauncher({ lock: false });
      },
    });
    controllerRef.current = controller;
    const unsub = controller.subscribe((snap) => {
      setFlowStep(snap.step);
      setRoleId(snap.roleId);
      setCategoryId(snap.categoryId);
      setPending(snap.pending);
      setPendingCategoryId(snap.pendingCategoryId);
      setFlowError(snap.error);
      setSuccessLabel(snap.successLabel);
      if (snap.phase === "success") setPhase("success");
    });
    // Sync initial controller snapshot (always role-first).
    const snap0 = controller.getState();
    setFlowStep(snap0.step);
    setRoleId(snap0.roleId);
    setCategoryId(snap0.categoryId);
    return () => {
      unsub();
      controllerRef.current = null;
    };
    // Recreate when assignment context changes; role/category taps go through controller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    phase,
    pendingPin,
    slug,
    selectionTree,
    currentCategoryId,
    currentRoleId,
    goPinLauncher,
  ]);

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

  if (phase === "opening") {
    return (
      <OpsMobileShell>
        <Stack spacing={2} alignItems="center" sx={{ py: 6 }}>
          <CircularProgress size={36} />
          <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted }}>Opening role…</Typography>
        </Stack>
      </OpsMobileShell>
    );
  }

  if (phase === "select" || phase === "success" || phase === "unavailable") {
    return (
      <OpsSwitchRoleFlow
        employeeName={firstName}
        selectionTree={selectionTree}
        step={flowStep}
        roleId={roleId}
        onSelectRole={(role) => controllerRef.current?.setRole(role)}
        onSelectCategory={(cat) => controllerRef.current?.selectCategory(cat)}
        onBackToRoles={() => controllerRef.current?.backToRoles()}
        currentCategoryId={currentCategoryId}
        currentRoleId={currentRoleId}
        pending={pending}
        pendingCategoryId={pendingCategoryId}
        error={flowError}
        onClearError={() => {
          setFlowError("");
          controllerRef.current?.clearError();
        }}
        onRetry={() => controllerRef.current?.clearError()}
        onBack={onBack}
        onLock={onLock}
        unavailable={phase === "unavailable"}
        unavailableMessage={unavailableMessage}
        success={phase === "success"}
        successLabel={successLabel}
      />
    );
  }

  // Direct-navigation PIN entry (standalone role PWA without hub session).
  return (
    <OpsMobileShell>
      <Paper
        elevation={0}
        sx={{
          width: "100%",
          borderRadius: `${OPS_MOBILE.radius.card}px`,
          p: { xs: 2, sm: 2.5 },
          bgcolor: alpha("#fff", 0.96),
          boxShadow: `0 8px 28px -16px ${alpha(OPS_MOBILE.navy, 0.35)}`,
        }}
      >
        <Stack spacing={2} alignItems="center">
          {logoSrc ? (
            <Box
              component="img"
              src={logoSrc}
              alt=""
              sx={{ height: 40, width: "auto", maxWidth: "60%", objectFit: "contain" }}
            />
          ) : (
            <TenantLogo size={40} />
          )}
          <Typography sx={{ fontWeight: 900, fontSize: "1.35rem", color: OPS_MOBILE.navy }}>
            Role
          </Typography>

          {!routeSlug && (
            <FormControl fullWidth size="small">
              <InputLabel id="role-org">Organization</InputLabel>
              <Select
                labelId="role-org"
                label="Organization"
                value={selectedSlug}
                disabled={orgsLoading}
                onChange={(e) => {
                  const s = sanitizeSlug(e.target.value);
                  setSelectedSlug(s);
                  if (s) navigate(`/attendance/role/${encodeURIComponent(s)}`, { replace: true });
                }}
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

          <Stack direction="row" spacing={1.25} justifyContent="center">
            {Array.from({ length: PIN_LEN }).map((_, i) => (
              <Box
                key={i}
                sx={{
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  bgcolor: i < pinDigits.length ? OPS_MOBILE.blue : alpha(OPS_MOBILE.navy, 0.15),
                }}
              />
            ))}
          </Stack>

          {loading ? <CircularProgress size={28} /> : null}

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
                  <Button key={key} disabled={loading || !pinDigits} onClick={pinClear} sx={digitKeySx()}>
                    C
                  </Button>
                );
              }
              if (key === "⌫") {
                return (
                  <IconButton
                    key={key}
                    disabled={loading || !pinDigits}
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
                  onClick={() => appendDigit(key)}
                  sx={digitKeySx()}
                >
                  {key}
                </Button>
              );
            })}
          </Box>

          <Button
            onClick={onBack}
            sx={{ textTransform: "none", fontWeight: 800, minHeight: OPS_MOBILE.touchMin }}
          >
            PIN
          </Button>
        </Stack>
      </Paper>
    </OpsMobileShell>
  );
}
