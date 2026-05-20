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
import { Backspace, CheckCircle } from "@mui/icons-material";
import {
  attendancePinPunch,
  getPublicOrgBranding,
  getPublicOrganizationsForAttendance,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
import { applyAppIconFromOrganizationLogo } from "../utils/appIcon";

const PIN_LEN = 4;
const SUCCESS_RESET_MS = 4000;
const STORAGE_KEY = "washpro_attendance_org_slug";

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
    "&.Mui-disabled": {
      opacity: 0.45,
    },
  };
}

function utilityKeySx() {
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(null);
  const [branding, setBranding] = useState(null);

  const prevPinLenRef = useRef(0);
  const resetTimerRef = useRef(null);

  const localeTag = locale === "es" ? "es-US" : "en-US";

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
    async (digits) => {
      if (!slug || String(digits || "").replace(/\D/g, "").length !== PIN_LEN) return;
      const clean = String(digits).replace(/\D/g, "");
      setError("");
      try {
        setLoading(true);
        const res = await attendancePinPunch(slug, clean);
        const data = res?.data || {};
        if (!data?.ok) {
          throw new Error(data?.error || t("attendance.invalidPin"));
        }
        setSuccess(data);
        setPin("");
        prevPinLenRef.current = 0;
        scheduleReset();
      } catch (e) {
        console.error(e);
        const data = e?.response?.data;
        let msg =
          (data && typeof data === "object" && (data.error || data.message)) ||
          (typeof data === "string" ? data : null);
        if (!msg && e?.response?.status === 401) {
          msg = t("attendance.invalidPin");
        }
        if (!msg) msg = e?.message || t("attendance.punchFailed");
        setError(typeof msg === "string" ? msg : t("attendance.punchFailed"));
        setPin("");
        prevPinLenRef.current = 0;
      } finally {
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

  const tenantTitle = branding?.display_name || slug || t("attendance.title");

  return (
    <Box
      sx={{
        minHeight: "100dvh",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        px: 2,
        py: 3,
        background: "linear-gradient(180deg, #fafbfd 0%, #f3f6fa 50%, #eef2f8 100%)",
      }}
    >
      <Paper
        elevation={0}
        sx={{
          width: "100%",
          maxWidth: 420,
          p: { xs: 2.5, sm: 3 },
          borderRadius: 3,
          border: "1px solid",
          borderColor: alpha("#2d3d9c", 0.12),
          boxShadow: "0 24px 60px -28px rgba(45, 61, 156, 0.28)",
        }}
      >
        <Stack spacing={2.5} alignItems="center">
          <TenantLogo
            logoUrl={branding?.logo_url}
            alt={tenantTitle}
            sx={{ width: 72, height: 72 }}
          />
          <Typography variant="h5" fontWeight={700} textAlign="center" color="#152238">
            {tenantTitle}
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
              <Typography variant="h6" fontWeight={600} color="#334155">
                {t("attendance.enterPin")}
              </Typography>

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
                      bgcolor: i < pinDigits.length ? "#2d3d9c" : alpha("#2d3d9c", 0.15),
                      transition: "background-color 0.15s",
                    }}
                  />
                ))}
              </Box>

              {error ? (
                <Alert severity="error" sx={{ width: "100%" }}>
                  {error}
                </Alert>
              ) : null}

              {loading ? <CircularProgress size={32} /> : null}

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
                  <Button key={n} variant="outlined" onClick={() => appendDigit(n)} sx={digitKeySx()}>
                    {n}
                  </Button>
                ))}
                <Button variant="outlined" onClick={pinClear} sx={utilityKeySx()}>
                  {t("attendance.clearPin")}
                </Button>
                <Button variant="outlined" onClick={() => appendDigit(0)} sx={digitKeySx()}>
                  0
                </Button>
                <IconButton onClick={pinBackspace} sx={utilityKeySx()} aria-label={t("attendance.backspace")}>
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
            sx={{ color: "#64748b" }}
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
    </Box>
  );
}
