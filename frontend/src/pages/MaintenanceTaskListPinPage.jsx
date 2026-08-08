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
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { Backspace } from "@mui/icons-material";
import {
  attendancePinMaintenanceTasks,
  getPublicMaintenanceTaskListToday,
  getPublicOrgBranding,
  getPublicOrganizationsForAttendance,
  getWashproApiBase,
  patchPublicMaintenanceTaskItem,
  submitPublicMaintenanceTaskList,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
import {
  OpsMobileShell,
  OpsStickyActionBar,
  OpsTaskCard,
  OpsTopBar,
  OPS_MOBILE,
} from "../opsMobile";
import { createTaskSubmitController } from "../opsMobile/createTaskSubmitController";
import { createTaskToggleController } from "../opsMobile/createTaskToggleController";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";
import {
  allTasksChecked,
  clearMtlPinSession,
  compactTaskContext,
  formatDateLong,
  formatTimeEt,
  groupTasksByCategory,
  isCompletedStatus,
  loadMtlPinSession,
  saveMtlPinSession,
  taskProgress,
} from "../utils/maintenanceTaskListHelpers";
import {
  clearPinHubAppSession,
  clearPinHubSession,
  pinHubMenuPath,
} from "../utils/pinHubSession";

const PIN_LEN = 4;
const STORAGE_KEY = "washpro_attendance_org_slug";

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
 * PIN employee End-of-Day Checklist — mobile-first completion flow.
 * Routes: /attendance/maintenance, /attendance/maintenance/:orgSlug
 */
export default function MaintenanceTaskListPinPage() {
  const { t } = useI18n();
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
  const [phase, setPhase] = useState("pin"); // pin | list | submitted | unavailable
  const [session, setSession] = useState(null);
  const [list, setList] = useState(null);
  const [dateDisplay, setDateDisplay] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);
  const [pendingTick, setPendingTick] = useState(0);
  const [unavailableMessage, setUnavailableMessage] = useState(
    "End-of-Day Checklist isn’t available right now.",
  );

  const punchInFlightRef = useRef(false);
  const prevPinLenRef = useRef(0);
  const listRef = useRef(null);
  const toggleRef = useRef(null);
  const submitRef = useRef(null);

  const pinClean = useMemo(() => String(pin || "").replace(/\D/g, "").slice(0, PIN_LEN), [pin]);
  const logoSrc = attendanceLogoSrc(slug, branding?.logo_url);
  const isCompleted = isCompletedStatus(list?.status) || !!list?.read_only;
  const readOnly = isCompleted;
  const canSubmit = !readOnly && allTasksChecked(list);
  const progress = taskProgress(list);
  const employeeLabel =
    session?.employee_first_name ||
    (session?.employee_name || "").split(/\s+/)[0] ||
    "";
  const contextLine = compactTaskContext(employeeLabel, dateDisplay || "Today");

  listRef.current = list;

  const goPinLauncher = useCallback(
    ({ lock = false } = {}) => {
      if (lock) {
        clearMtlPinSession();
        clearPinHubSession();
        clearPinHubAppSession();
      }
      navigate(pinHubMenuPath(slug), { replace: true });
    },
    [navigate, slug],
  );

  const onBack = useCallback(() => {
    // Preserve hub unlock; checklist MTL session stays so Checklist can reopen.
    navigate(pinHubMenuPath(slug), { replace: true });
  }, [navigate, slug]);

  const onLock = useCallback(() => {
    goPinLauncher({ lock: true });
  }, [goPinLauncher]);

  const onDone = useCallback(() => {
    clearMtlPinSession();
    navigate(pinHubMenuPath(slug), { replace: true });
  }, [navigate, slug]);

  useLayoutEffect(() => {
    return applyAttendancePwaManifest(routeSlug || selectedSlug, "maintenance");
  }, [routeSlug, selectedSlug]);

  useEffect(() => {
    if (routeSlug) return;
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const s = sanitizeSlug(saved);
      if (s && s !== "role" && s !== "maintenance") {
        navigate(`/attendance/maintenance/${encodeURIComponent(s)}`, { replace: true });
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

  const loadTodayList = useCallback(async (sess) => {
    const res = await getPublicMaintenanceTaskListToday(sess.token);
    if (res.status === 401) {
      clearMtlPinSession();
      setSession(null);
      setUnavailableMessage("End-of-Day Checklist isn’t available right now.");
      setPhase("unavailable");
      return null;
    }
    if (!(res.status >= 200 && res.status < 300 && res.data?.ok)) {
      throw new Error(res.data?.error || "Could not load task list");
    }
    setList(res.data.list);
    setDateDisplay(res.data.task_date_display || "");
    const done =
      isCompletedStatus(res.data.list?.status) || !!res.data.list?.read_only;
    setPhase(done ? "submitted" : "list");
    return res.data.list;
  }, []);

  useEffect(() => {
    toggleRef.current = createTaskToggleController({
      getList: () => listRef.current,
      setList: (next) => {
        setList(next);
        setPendingTick((n) => n + 1);
      },
      isReadOnly: () => isCompletedStatus(listRef.current?.status) || !!listRef.current?.read_only,
      patchItem: async ({ listId, itemId, completed }) => {
        const sess = loadMtlPinSession() || session;
        return patchPublicMaintenanceTaskItem(sess.token, listId, itemId, { completed });
      },
      onError: (msg) => setError(msg || "Couldn’t save. Try again."),
    });
    submitRef.current = createTaskSubmitController({
      getList: () => listRef.current,
      setList: (next) => setList(next),
      getSessionToken: () => (loadMtlPinSession() || session)?.token,
      submitList: async ({ token, listId }) => submitPublicMaintenanceTaskList(token, listId, {}),
      onError: (msg) => setError(msg || "Couldn’t submit. Try again."),
    });
  }, [session]);

  useEffect(() => {
    const existing = loadMtlPinSession();
    if (!existing || !slug) {
      if (fromHub && slug && !existing) {
        setUnavailableMessage("End-of-Day Checklist isn’t available right now.");
        setPhase("unavailable");
      }
      return;
    }
    if (existing.organization_slug && existing.organization_slug !== slug) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        setSession(existing);
        await loadTodayList(existing);
      } catch {
        if (!cancelled) {
          clearMtlPinSession();
          setSession(null);
          setUnavailableMessage("End-of-Day Checklist isn’t available right now.");
          setPhase("unavailable");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, loadTodayList, fromHub]);

  const openFromPin = useCallback(
    async (digits) => {
      if (!slug || punchInFlightRef.current) return;
      const clean = String(digits || "").replace(/\D/g, "");
      if (clean.length !== PIN_LEN) return;
      punchInFlightRef.current = true;
      setLoading(true);
      setError("");
      try {
        const res = await attendancePinMaintenanceTasks(slug, clean);
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (typeof res?.data === "string" && String(res.data).trim().startsWith("<")) {
          console.error("[mtl] Non-JSON response", { apiBase: getWashproApiBase(), slug });
          setError(t("attendance.serverError"));
          setPin("");
          prevPinLenRef.current = 0;
          return;
        }
        if (!(res.status >= 200 && res.status < 300 && body.ok && body.token)) {
          setError(body.error || t("attendance.invalidPin"));
          setPin("");
          prevPinLenRef.current = 0;
          return;
        }
        const sess = {
          token: body.token,
          employee_id: body.employee_id,
          employee_name: body.employee_name,
          employee_first_name: body.employee_first_name,
          organization_id: body.organization_id,
          organization_slug: slug,
        };
        saveMtlPinSession(sess);
        setSession(sess);
        setPin("");
        prevPinLenRef.current = 0;
        await loadTodayList(sess);
      } catch (e) {
        setUnavailableMessage("End-of-Day Checklist isn’t available right now.");
        setPhase("unavailable");
        setPin("");
        prevPinLenRef.current = 0;
      } finally {
        punchInFlightRef.current = false;
        setLoading(false);
      }
    },
    [slug, t, loadTodayList],
  );

  useEffect(() => {
    if (phase !== "pin") return;
    if (pinClean.length === PIN_LEN && prevPinLenRef.current < PIN_LEN) {
      openFromPin(pinClean);
    }
    prevPinLenRef.current = pinClean.length;
  }, [pinClean, phase, openFromPin]);

  const handleSubmit = async () => {
    if (!submitRef.current?.canSubmit() || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await submitRef.current.submit();
      setPhase("submitted");
    } finally {
      setSubmitting(false);
    }
  };

  const items = list?.items || [];
  const grouped = useMemo(() => groupTasksByCategory(items), [items]);
  void pendingTick;

  // ——— Compact submitted confirmation (no full checklist) ———
  if (phase === "submitted") {
    const submittedAt = formatTimeEt(list?.submitted_at);
    const dateLine = formatDateLong(list?.task_date) || dateDisplay || "Today";
    return (
      <OpsMobileShell contentSx={{ gap: 1.25 }}>
        <Box
          sx={{
            width: "100%",
            borderRadius: `${OPS_MOBILE.radius.card}px`,
            bgcolor: alpha("#fff", 0.96),
            boxShadow: `0 8px 28px -16px ${alpha(OPS_MOBILE.navy, 0.35)}`,
            p: { xs: 1.5, sm: 2 },
            display: "flex",
            flexDirection: "column",
            gap: 1.5,
          }}
        >
          <OpsTopBar title="End-of-Day Checklist" onBack={onBack} backLabel="PIN" onLock={onLock} sticky />
          <Stack spacing={0.5} alignItems="center" sx={{ py: 1.5, textAlign: "center" }}>
            <Typography sx={{ fontWeight: 900, fontSize: "1.15rem", color: OPS_MOBILE.navy }}>
              Maintenance Checklist Submitted
            </Typography>
            <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, fontSize: "0.95rem" }}>
              {dateLine}
            </Typography>
            <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, fontSize: "0.95rem" }}>
              {submittedAt}
            </Typography>
          </Stack>
          <Button
            fullWidth
            variant="contained"
            onClick={onDone}
            sx={{
              minHeight: 52,
              textTransform: "none",
              fontWeight: 900,
              bgcolor: OPS_MOBILE.navy,
            }}
          >
            Done
          </Button>
          <Button
            fullWidth
            onClick={onLock}
            sx={{
              minHeight: 48,
              textTransform: "none",
              fontWeight: 800,
              bgcolor: alpha(OPS_MOBILE.navy, 0.08),
            }}
          >
            Lock
          </Button>
        </Box>
      </OpsMobileShell>
    );
  }

  // ——— List / empty / unavailable ———
  if (phase === "list" || phase === "unavailable") {
    const emptyAssigned = phase === "list" && list && items.length === 0;
    const showUnavailable = phase === "unavailable";

    return (
      <OpsMobileShell
        contentSx={{
          gap: 1.5,
          // Keep sticky Submit/Done from covering the last task card.
          pb: phase === "list" && list && items.length > 0 ? 10 : 2,
        }}
      >
        <Box
          sx={{
            width: "100%",
            borderRadius: `${OPS_MOBILE.radius.card}px`,
            bgcolor: alpha("#fff", 0.96),
            boxShadow: `0 8px 28px -16px ${alpha(OPS_MOBILE.navy, 0.35)}`,
            p: { xs: 1.75, sm: 2.25 },
            display: "flex",
            flexDirection: "column",
            gap: 1.5,
          }}
        >
          <OpsTopBar
            title="End-of-Day Checklist"
            onBack={onBack}
            backLabel="PIN"
            onLock={onLock}
            sticky
          />

          {error ? (
            <Alert severity="error" onClose={() => setError("")} sx={{ borderRadius: 2 }}>
              {error}
            </Alert>
          ) : null}

          {showUnavailable ? (
            <Stack spacing={2.5} sx={{ py: 2 }}>
              <Typography sx={{ fontWeight: 800, fontSize: "1.15rem", textAlign: "center", color: OPS_MOBILE.navy }}>
                {unavailableMessage}
              </Typography>
              <Button
                fullWidth
                onClick={onLock}
                sx={{
                  minHeight: 64,
                  textTransform: "none",
                  fontWeight: 800,
                  fontSize: "1.1rem",
                  bgcolor: alpha(OPS_MOBILE.navy, 0.08),
                }}
              >
                Lock
              </Button>
            </Stack>
          ) : null}

          {emptyAssigned ? (
            <Typography sx={{ fontWeight: 800, fontSize: "1.15rem", textAlign: "center", py: 3, color: OPS_MOBILE.navy }}>
              No tasks assigned
            </Typography>
          ) : null}

          {phase === "list" && list && items.length > 0 ? (
            <>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
                {contextLine ? (
                  <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, fontSize: "0.95rem" }}>
                    {contextLine}
                  </Typography>
                ) : null}
                <Box sx={{ flex: 1 }} />
                <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
                  {progress.done} of {progress.total}
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={progress.total ? (100 * progress.done) / progress.total : 0}
                sx={{
                  height: 6,
                  borderRadius: 99,
                  bgcolor: alpha(OPS_MOBILE.navy, 0.08),
                  "& .MuiLinearProgress-bar": { bgcolor: OPS_MOBILE.cobalt, borderRadius: 99 },
                }}
              />

              <Stack spacing={1.25}>
                {grouped.map((group) => (
                  <Box key={group.category}>
                    <Typography
                      sx={{
                        fontWeight: 800,
                        fontSize: "0.75rem",
                        color: OPS_MOBILE.muted,
                        mb: 0.35,
                      }}
                    >
                      {group.category}
                    </Typography>
                    <Stack spacing={0.75}>
                      {group.items.map((item) => (
                        <OpsTaskCard
                          key={item.id}
                          title={item.task_name_snapshot || "Task"}
                          instruction={item.task_description_snapshot || ""}
                          completed={!!item.completed}
                          readOnly={false}
                          busy={!!toggleRef.current?.isPending(item.id) || submitting}
                          onComplete={() => toggleRef.current?.toggle(item)}
                          onUndo={() => toggleRef.current?.toggle(item)}
                        />
                      ))}
                    </Stack>
                  </Box>
                ))}
              </Stack>
            </>
          ) : null}

          {loading && phase === "list" && !list ? (
            <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
              <CircularProgress size={32} />
            </Box>
          ) : null}
        </Box>

        {phase === "list" && list && items.length > 0 && !readOnly ? (
          <OpsStickyActionBar
            sx={{
              position: "fixed",
              left: 0,
              right: 0,
              bottom: 0,
              px: 2,
              maxWidth: 420,
              mx: "auto",
              borderTop: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
            }}
          >
            <Button
              fullWidth
              variant="contained"
              disabled={submitting || !canSubmit}
              onClick={handleSubmit}
              sx={{
                minHeight: 56,
                textTransform: "none",
                fontWeight: 900,
                fontSize: "1.05rem",
                borderRadius: `${OPS_MOBILE.radius.button}px`,
                bgcolor: OPS_MOBILE.cobalt,
              }}
            >
              {submitting ? "Submitting…" : "Submit Checklist"}
            </Button>
          </OpsStickyActionBar>
        ) : null}
      </OpsMobileShell>
    );
  }

  // ——— Direct PIN entry ———
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
            End-of-Day Checklist
          </Typography>

          {!routeSlug ? (
            orgsLoading ? (
              <CircularProgress size={24} />
            ) : (
              <FormControl fullWidth size="small">
                <InputLabel id="mtl-org">{t("attendance.selectCompany")}</InputLabel>
                <Select
                  labelId="mtl-org"
                  label={t("attendance.selectCompany")}
                  value={selectedSlug || ""}
                  onChange={(e) => {
                    const s = sanitizeSlug(e.target.value);
                    setSelectedSlug(s);
                    if (s) {
                      navigate(`/attendance/maintenance/${encodeURIComponent(s)}`, { replace: true });
                    }
                  }}
                >
                  {orgs.map((o) => (
                    <MenuItem key={o.slug} value={o.slug}>
                      {o.display_name || o.slug}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            )
          ) : null}

          {error ? (
            <Alert severity="error" sx={{ width: "100%" }} onClose={() => setError("")}>
              {error}
            </Alert>
          ) : null}

          <Stack direction="row" spacing={1.25}>
            {Array.from({ length: PIN_LEN }).map((_, i) => (
              <Box
                key={i}
                sx={{
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  bgcolor: i < pinClean.length ? OPS_MOBILE.blue : alpha(OPS_MOBILE.navy, 0.15),
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
                  <Button
                    key={key}
                    disabled={loading || !pinClean}
                    onClick={() => {
                      setPin("");
                      prevPinLenRef.current = 0;
                    }}
                    sx={digitKeySx()}
                  >
                    C
                  </Button>
                );
              }
              if (key === "⌫") {
                return (
                  <IconButton
                    key={key}
                    disabled={loading || !pinClean}
                    onClick={() => setPin((p) => String(p || "").slice(0, -1))}
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
                  onClick={() =>
                    setPin((p) => `${String(p || "").replace(/\D/g, "")}${key}`.slice(0, PIN_LEN))
                  }
                  sx={digitKeySx()}
                >
                  {key}
                </Button>
              );
            })}
          </Box>
          {loading ? <CircularProgress size={28} /> : null}
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
