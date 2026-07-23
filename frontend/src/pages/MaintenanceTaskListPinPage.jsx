import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { Backspace, CheckCircle } from "@mui/icons-material";
import {
  attendancePinMaintenanceTasks,
  getPublicMaintenanceTaskListToday,
  getPublicOrgBranding,
  getPublicOrganizationsForAttendance,
  getWashproApiBase,
  patchPublicMaintenanceTaskItem,
  savePublicMaintenanceTaskList,
  submitPublicMaintenanceTaskList,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { applyAttendancePwaManifest } from "../utils/attendancePwaManifest";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";
import {
  clearMtlPinSession,
  allTasksChecked,
  isCompletedStatus,
  loadMtlPinSession,
  mtlEmployeePageSx,
  saveMtlPinSession,
  statusLabel,
} from "../utils/maintenanceTaskListHelpers";

const PIN_LEN = 4;
const STORAGE_KEY = "washpro_attendance_org_slug";
const VEEWASH_ATTENDANCE_LOGO = VEEWASH_LOGO_URL;

const VW = {
  navy: "#16192b",
  blue: "#2d3d9c",
  cobalt: "#4865ee",
  gold: "#9a7209",
  goldMid: "#d4a84b",
  cream: "#faf6e9",
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

/**
 * PIN employee Maintenance Task List — mobile-first checklist.
 * Route: /attendance/maintenance/:orgSlug
 */
export default function MaintenanceTaskListPinPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { orgSlug: orgSlugParam } = useParams();
  const routeSlug = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);

  const [selectedSlug, setSelectedSlug] = useState("");
  const [orgs, setOrgs] = useState([]);
  const [orgsLoading, setOrgsLoading] = useState(!routeSlug);
  const slug = routeSlug || selectedSlug;

  const [pin, setPin] = useState("");
  const [phase, setPhase] = useState("pin"); // pin | list | success
  const [session, setSession] = useState(null);
  const [list, setList] = useState(null);
  const [dateDisplay, setDateDisplay] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);
  const [successMessage, setSuccessMessage] = useState("");

  const punchInFlightRef = useRef(false);
  const prevPinLenRef = useRef(0);
  const saveTimerRef = useRef(null);

  const pinClean = useMemo(() => String(pin || "").replace(/\D/g, "").slice(0, PIN_LEN), [pin]);
  const logoSrc = attendanceLogoSrc(slug, branding?.logo_url);
  const isCompleted = isCompletedStatus(list?.status) || !!list?.read_only;
  const readOnly = isCompleted;
  const canSubmit = !readOnly && allTasksChecked(list);

  const goToSlugRoute = (s) => {
    const clean = sanitizeSlug(s);
    if (!clean) return;
    navigate(`/attendance/maintenance/${encodeURIComponent(clean)}`, { replace: true });
  };

  useLayoutEffect(() => {
    return applyAttendancePwaManifest(routeSlug || selectedSlug);
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
      setPhase("pin");
      setError("Session expired. Enter your PIN again.");
      return null;
    }
    if (!(res.status >= 200 && res.status < 300 && res.data?.ok)) {
      throw new Error(res.data?.error || "Could not load task list");
    }
    setList(res.data.list);
    setDateDisplay(res.data.task_date_display || "");
    setPhase("list");
    return res.data.list;
  }, []);

  useEffect(() => {
    const existing = loadMtlPinSession();
    if (!existing || !slug) return;
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
          setPhase("pin");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, loadTodayList]);

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
        setError(
          e?.code === "ECONNABORTED"
            ? t("attendance.timeout")
            : !e?.response
              ? t("attendance.networkError")
              : e?.response?.data?.error || t("attendance.invalidPin"),
        );
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

  const scheduleAutosave = useCallback(
    (nextList) => {
      if (!session?.token || !nextList?.id || isCompletedStatus(nextList.status) || nextList.read_only) {
        return;
      }
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(async () => {
        try {
          setSaving(true);
          const res = await savePublicMaintenanceTaskList(session.token, nextList.id, {
            items: (nextList.items || []).map((i) => ({
              id: i.id,
              completed: !!i.completed,
              note: i.note || "",
            })),
          });
          if (res.status >= 200 && res.status < 300 && res.data?.list) {
            setList(res.data.list);
          }
        } catch {
          /* keep local state */
        } finally {
          setSaving(false);
        }
      }, 450);
    },
    [session],
  );

  const toggleItem = async (item) => {
    if (readOnly || !session?.token || !list?.id) return;
    const completed = !item.completed;
    const nextItems = (list.items || []).map((i) =>
      i.id === item.id ? { ...i, completed } : i,
    );
    const nextList = { ...list, items: nextItems };
    setList(nextList);
    try {
      const res = await patchPublicMaintenanceTaskItem(session.token, list.id, item.id, {
        completed,
      });
      if (res.status >= 200 && res.status < 300 && res.data?.list) {
        setList(res.data.list);
      } else if (res.status === 409) {
        setError(res.data?.error || "List is submitted");
        await loadTodayList(session);
      }
    } catch {
      scheduleAutosave(nextList);
    }
  };

  const handleSaveProgress = async () => {
    if (!session?.token || !list?.id || readOnly) return;
    setSaving(true);
    setError("");
    try {
      const res = await savePublicMaintenanceTaskList(session.token, list.id, {
        items: (list.items || []).map((i) => ({
          id: i.id,
          completed: !!i.completed,
          note: i.note || "",
        })),
      });
      if (res.status >= 200 && res.status < 300 && res.data?.list) {
        setList(res.data.list);
      } else {
        setError(res.data?.error || "Could not save progress");
      }
    } catch (e) {
      setError(e?.response?.data?.error || "Could not save progress");
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = async () => {
    if (!session?.token || !list?.id || readOnly || !allTasksChecked(list)) return;
    setLoading(true);
    setError("");
    try {
      const res = await submitPublicMaintenanceTaskList(session.token, list.id, {});
      if (res.status >= 200 && res.status < 300 && res.data?.ok) {
        setList(res.data.list);
        setSuccessMessage(
          res.data.message || "Maintenance task list completed successfully.",
        );
        setPhase("success");
      } else {
        setError(res.data?.error || "Could not submit");
      }
    } catch (e) {
      setError(e?.response?.data?.error || "Could not submit");
    } finally {
      setLoading(false);
    }
  };

  const resetToPin = () => {
    clearMtlPinSession();
    setSession(null);
    setList(null);
    setPhase("pin");
    setSuccessMessage("");
    setError("");
    setPin("");
  };

  const employeeLabel =
    session?.employee_first_name ||
    (session?.employee_name || "").split(/\s+/)[0] ||
    "Employee";

  return (
    <Box sx={mtlEmployeePageSx()}>
      <Box sx={{ px: 2, pt: 2, pb: 1, maxWidth: 480, mx: "auto", width: "100%" }}>
        <Stack spacing={1.5} alignItems="center">
          {logoSrc ? (
            <Box
              component="img"
              src={logoSrc}
              alt=""
              sx={{ width: "min(160px, 48vw)", height: "auto", objectFit: "contain" }}
            />
          ) : (
            <TenantLogo logoUrl={branding?.logo_url} sx={{ width: 72, height: 72 }} />
          )}
          <Typography variant="h5" fontWeight={800} textAlign="center" color={VW.navy}>
            Maintenance Task List
          </Typography>
          {phase === "pin" ? (
            <Typography color="text.secondary" textAlign="center">
              Enter your PIN to continue
            </Typography>
          ) : null}
          <Button
            component={Link}
            to={slug ? `/attendance/role/${encodeURIComponent(slug)}` : "/attendance/role"}
            size="small"
            sx={{ textTransform: "none" }}
          >
            Switch Role
          </Button>
        </Stack>

        {error ? (
          <Alert severity="error" sx={{ mt: 2 }} onClose={() => setError("")}>
            {error}
          </Alert>
        ) : null}

        {phase === "pin" ? (
          <Stack spacing={2} alignItems="center" sx={{ mt: 2 }}>
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
                      setSelectedSlug(String(e.target.value));
                      goToSlugRoute(e.target.value);
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

            <Stack direction="row" spacing={1}>
              {Array.from({ length: PIN_LEN }).map((_, i) => (
                <Box
                  key={i}
                  sx={{
                    width: 14,
                    height: 14,
                    borderRadius: "50%",
                    bgcolor: i < pinClean.length ? VW.cobalt : alpha(VW.navy, 0.15),
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
                maxWidth: 320,
              }}
            >
              {["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "back"].map((key) => {
                if (key === "") return <Box key="spacer" />;
                if (key === "back") {
                  return (
                    <IconButton
                      key="back"
                      disabled={loading}
                      onClick={() => setPin((p) => p.slice(0, -1))}
                      sx={digitKeySx()}
                    >
                      <Backspace />
                    </IconButton>
                  );
                }
                return (
                  <Button
                    key={key}
                    disabled={loading || !slug}
                    onClick={() =>
                      setPin((p) => (p.replace(/\D/g, "").length >= PIN_LEN ? p : `${p}${key}`))
                    }
                    sx={digitKeySx()}
                  >
                    {key}
                  </Button>
                );
              })}
            </Box>
            {loading ? <CircularProgress size={28} /> : null}
          </Stack>
        ) : null}

        {phase === "success" ? (
          <Stack spacing={2} alignItems="center" sx={{ mt: 3, py: 2 }}>
            <CheckCircle sx={{ fontSize: 64, color: "#059669" }} />
            <Typography variant="h6" fontWeight={700} textAlign="center">
              {successMessage}
            </Typography>
            <Button variant="contained" onClick={() => setPhase("list")} sx={{ textTransform: "none" }}>
              View submitted list
            </Button>
            <Button onClick={resetToPin} sx={{ textTransform: "none" }}>
              Done
            </Button>
          </Stack>
        ) : null}

        {phase === "list" && list ? (
          <Box sx={{ mt: 2 }}>
            <Typography fontWeight={700} color="text.secondary">
              {dateDisplay || list.task_date}
            </Typography>
            <Typography sx={{ mb: 1 }}>
              Employee: <strong>{employeeLabel}</strong>
              {saving ? (
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  Saving…
                </Typography>
              ) : null}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Status: {statusLabel(list.status)}
            </Typography>

            <Stack spacing={1.25}>
              {(list.items || []).map((item) => (
                <Box
                  key={item.id}
                  sx={{
                    p: 1.25,
                    borderRadius: 2,
                    bgcolor: "#fff",
                    border: `1px solid ${alpha(VW.navy, 0.08)}`,
                  }}
                >
                  <FormControlLabel
                    sx={{
                      m: 0,
                      alignItems: "flex-start",
                      width: "100%",
                      "& .MuiFormControlLabel-label": {
                        fontSize: "1.05rem",
                        fontWeight: 600,
                        lineHeight: 1.35,
                        pt: 0.85,
                      },
                    }}
                    control={
                      <Checkbox
                        checked={!!item.completed}
                        disabled={readOnly || loading}
                        onChange={() => toggleItem(item)}
                        sx={{
                          p: 1,
                          "& .MuiSvgIcon-root": { fontSize: 32 },
                        }}
                      />
                    }
                    label={item.task_name_snapshot}
                  />
                </Box>
              ))}
            </Stack>
          </Box>
        ) : null}
      </Box>

      {phase === "list" && list && !readOnly ? (
        <Box
          sx={{
            position: "fixed",
            bottom: 0,
            left: 0,
            right: 0,
            zIndex: 1100,
            p: 2,
            pb: "calc(16px + env(safe-area-inset-bottom))",
            bgcolor: "#fff",
            borderTop: "1px solid",
            borderColor: "divider",
            boxShadow: "0 -4px 12px rgba(0,0,0,0.08)",
            maxWidth: "100vw",
            overflowX: "hidden",
          }}
        >
          <Stack direction="row" spacing={1.5} sx={{ maxWidth: 480, mx: "auto" }}>
            <Button
              fullWidth
              variant="outlined"
              disabled={loading || saving}
              onClick={handleSaveProgress}
              sx={{ textTransform: "none", fontWeight: 700, minHeight: 48 }}
            >
              Save Progress
            </Button>
            <Button
              fullWidth
              variant="contained"
              disabled={loading || saving || !canSubmit}
              onClick={handleSubmit}
              sx={{ textTransform: "none", fontWeight: 700, minHeight: 48 }}
            >
              Submit Checklist
            </Button>
          </Stack>
        </Box>
      ) : null}

      {phase === "list" && readOnly ? (
        <Box
          sx={{
            position: "fixed",
            bottom: 0,
            left: 0,
            right: 0,
            zIndex: 1100,
            p: 2,
            pb: "calc(16px + env(safe-area-inset-bottom))",
            bgcolor: "#fff",
            borderTop: "1px solid",
            borderColor: "divider",
          }}
        >
          <Button fullWidth variant="outlined" onClick={resetToPin} sx={{ textTransform: "none", minHeight: 48 }}>
            Done
          </Button>
        </Box>
      ) : null}
    </Box>
  );
}
