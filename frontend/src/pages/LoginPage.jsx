import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link as MuiLink,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  authLogin,
  getPublicOrgBranding,
  getWashproApiBase,
  postPasswordResetComplete,
  postPasswordResetRequest,
  postPublicChangePassword,
  setAuthSession,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import TenantLogo from "../components/TenantLogo";
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

function LoginPage({ onLoggedIn }) {
  const { t } = useI18n();
  const { orgSlug: orgSlugParam } = useParams();
  const slugFromRoute = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [organizationSlug, setOrganizationSlug] = useState(
    () => localStorage.getItem("washpro_org_slug") || "",
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);

  const [changeOpen, setChangeOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [cpUser, setCpUser] = useState("");
  const [cpSlug, setCpSlug] = useState("");
  const [cpCurrent, setCpCurrent] = useState("");
  const [cpNew, setCpNew] = useState("");
  const [cpConfirm, setCpConfirm] = useState("");
  const [cpBusy, setCpBusy] = useState(false);
  const [cpErr, setCpErr] = useState("");

  const [rsUser, setRsUser] = useState("");
  const [rsSlug, setRsSlug] = useState("");
  const [rsToken, setRsToken] = useState("");
  const [rsNew, setRsNew] = useState("");
  const [rsBusy, setRsBusy] = useState(false);
  const [rsErr, setRsErr] = useState("");
  const [rsMsg, setRsMsg] = useState("");
  const [rsDevToken, setRsDevToken] = useState("");

  useEffect(() => {
    if (slugFromRoute) {
      setOrganizationSlug(slugFromRoute);
      localStorage.setItem("washpro_org_slug", slugFromRoute);
    }
  }, [slugFromRoute]);

  /** Bookmark URL `/login/:slug` — tenant logo + name without debounce. */
  useEffect(() => {
    if (!slugFromRoute) return undefined;
    if (slugFromRoute === "platform") {
      setBranding({ display_name: "Platform", logo_url: null, slug: "platform" });
      return undefined;
    }
    let cancelled = false;
    getPublicOrgBranding(slugFromRoute)
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
  }, [slugFromRoute]);

  /** Plain `/login` — show last-used tenant branding immediately when slug is in storage. */
  useEffect(() => {
    if (slugFromRoute) return undefined;
    let slug = "";
    try {
      slug = (localStorage.getItem("washpro_org_slug") || "").trim().toLowerCase();
    } catch {
      slug = "";
    }
    if (!slug || slug === "platform") return undefined;
    let cancelled = false;
    getPublicOrgBranding(slug)
      .then((res) => {
        if (cancelled) return;
        if (res.status === 200 && res.data && !res.data.error) setBranding(res.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [slugFromRoute]);

  useEffect(() => {
    const slug = organizationSlug.trim().toLowerCase();
    if (!slug) {
      setBranding(null);
      return;
    }
    if (slug === "platform") {
      setBranding({ display_name: "Platform", logo_url: null, slug: "platform" });
      return;
    }
    let cancelled = false;
    const debounceMs = 380;
    const t = window.setTimeout(() => {
      getPublicOrgBranding(slug)
        .then((res) => {
          if (cancelled) return;
          if (res.status === 200 && res.data && !res.data.error) setBranding(res.data);
          else setBranding(null);
        })
        .catch(() => {
          if (!cancelled) setBranding(null);
        });
    }, debounceMs);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [organizationSlug]);

  useEffect(() => {
    if (changeOpen) {
      setCpUser(username.trim());
      setCpSlug((slugFromRoute || organizationSlug || "").trim().toLowerCase());
      setCpErr("");
    }
  }, [changeOpen, username, slugFromRoute, organizationSlug]);

  useEffect(() => {
    if (resetOpen) {
      setRsUser(username.trim());
      setRsSlug((slugFromRoute || organizationSlug || "").trim().toLowerCase());
      setRsErr("");
      setRsMsg("");
      setRsToken("");
      setRsNew("");
      setRsDevToken("");
    }
  }, [resetOpen, username, slugFromRoute, organizationSlug]);

  const submit = async () => {
    try {
      setLoading(true);
      setError("");
      const slug = organizationSlug.trim();
      if (slug) localStorage.setItem("washpro_org_slug", slug.toLowerCase());
      const res = await authLogin(username.trim(), password, slug || null);
      const payload = res?.data || {};
      if (!payload?.token || !payload?.user) {
        throw new Error("Invalid login response.");
      }
      setAuthSession(payload);
      onLoggedIn?.(payload.user);
    } catch (e) {
      console.error(e);
      const data = e?.response?.data;
      let msg =
        (data && typeof data === "object" && (data.error || data.message)) ||
        (typeof data === "string" ? data : null);
      if (!msg && e?.response?.status === 401) {
        msg = "Invalid credentials.";
      }
      if (!msg && e?.message === "Invalid login response.") {
        msg = "Invalid login response.";
      }
      if (!msg && e?.response) {
        const st = e.response.status;
        const d = data && typeof data === "object" ? data : null;
        if (d?.detail != null) {
          msg = String(d.detail);
        } else if (st >= 500) {
          msg = `Server error (${st}). Check the backend terminal and MySQL; see Network tab for the response body.`;
        } else {
          msg = `Login failed (HTTP ${st}).`;
        }
      }
      if (!msg && !e?.response) {
        const aborted =
          e?.code === "ECONNABORTED" ||
          String(e?.message || "")
            .toLowerCase()
            .includes("timeout");
        if (aborted) {
          msg =
            "Login request timed out. The API may be cold-starting, blocked by a firewall, or the wrong URL is set (check VITE_API_BASE for production).";
        }
        const net =
          e?.code === "ERR_NETWORK" ||
          String(e?.message || "")
            .toLowerCase()
            .includes("network");
        if (!msg && net) {
          const base = getWashproApiBase();
          msg =
            base && /^https?:\/\//i.test(base)
              ? `Cannot reach the API (${base}). The site may still be starting after a deploy/restart — wait 1–2 minutes and retry, or check Azure → laundryops-api → Log stream.`
              : "Cannot reach the server. For local dev, start the API and use the Vite proxy (see vite.config.js).";
        }
        if (!msg) msg = e?.message || "Login failed.";
      }
      setError(msg || "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  async function submitChangePassword() {
    setCpErr("");
    if (cpNew !== cpConfirm) {
      setCpErr(t("account.passwordMismatch"));
      return;
    }
    if (cpNew.length < 8) {
      setCpErr(t("account.passwordMin"));
      return;
    }
    setCpBusy(true);
    try {
      await postPublicChangePassword({
        username: cpUser.trim(),
        organization_slug: cpSlug.trim() || undefined,
        current_password: cpCurrent,
        new_password: cpNew,
      });
      setChangeOpen(false);
      setCpCurrent("");
      setCpNew("");
      setCpConfirm("");
    } catch (e) {
      setCpErr(e?.response?.data?.error || e?.message || "Failed");
    } finally {
      setCpBusy(false);
    }
  }

  async function submitResetRequest() {
    setRsErr("");
    setRsMsg("");
    setRsDevToken("");
    setRsBusy(true);
    try {
      const res = await postPasswordResetRequest({
        username: rsUser.trim(),
        organization_slug: rsSlug.trim() || undefined,
      });
      setRsMsg(res.data?.message || "");
      if (res.data?.dev_reset_token) {
        setRsDevToken(res.data.dev_reset_token);
        setRsToken(res.data.dev_reset_token);
      }
    } catch (e) {
      setRsErr(e?.response?.data?.error || e?.message || "Failed");
    } finally {
      setRsBusy(false);
    }
  }

  async function submitResetComplete() {
    setRsErr("");
    if (rsNew.length < 8) {
      setRsErr(t("account.passwordMin"));
      return;
    }
    setRsBusy(true);
    try {
      await postPasswordResetComplete({ token: rsToken.trim(), new_password: rsNew });
      setResetOpen(false);
      setRsToken("");
      setRsNew("");
    } catch (e) {
      setRsErr(e?.response?.data?.error || e?.message || "Failed");
    } finally {
      setRsBusy(false);
    }
  }

  const showOrgField = !slugFromRoute;

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "linear-gradient(160deg, #f1f5f9 0%, #e8eef7 50%, #f0fdfa 100%)",
        p: 2,
      }}
    >
      <Paper
        elevation={0}
        sx={{
          width: "100%",
          maxWidth: 400,
          p: 3,
          borderRadius: 2,
          border: "1px solid",
          borderColor: "divider",
        }}
      >
        <Stack spacing={2}>
          <Box sx={{ minHeight: 44, display: "flex", alignItems: "center", gap: 1.25 }}>
            <TenantLogo logoUrl={branding?.logo_url} size={40} />
            <Typography sx={{ fontSize: 22, fontWeight: 700, color: "text.primary" }}>
              {branding?.display_name || t("common.appName")}
            </Typography>
          </Box>

          {error ? <Alert severity="warning">{error}</Alert> : null}

          <TextField
            label={t("people.colUsername")}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            size="small"
            fullWidth
          />
          <TextField
            label={t("login.password")}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            size="small"
            fullWidth
          />

          {showOrgField ? (
            <TextField
              label={t("profile.organization")}
              placeholder={t("login.orgSlugPlaceholder")}
              value={organizationSlug}
              onChange={(e) => setOrganizationSlug(e.target.value)}
              autoComplete="organization"
              size="small"
              fullWidth
            />
          ) : null}

          <Button
            variant="contained"
            disabled={loading || !username || !password}
            onClick={submit}
            fullWidth
            sx={{ py: 1 }}
          >
            {loading ? t("login.signingIn") : t("login.signIn")}
          </Button>

          <Stack direction="row" spacing={2} justifyContent="center" flexWrap="wrap" useFlexGap>
            <MuiLink
              component="button"
              type="button"
              variant="body2"
              onClick={() => setChangeOpen(true)}
              sx={{ cursor: "pointer", color: "primary.main" }}
            >
              {t("login.changePasswordLink")}
            </MuiLink>
            <MuiLink
              component="button"
              type="button"
              variant="body2"
              onClick={() => setResetOpen(true)}
              sx={{ cursor: "pointer", color: "primary.main" }}
            >
              {t("login.resetPasswordLink")}
            </MuiLink>
          </Stack>

          {slugFromRoute ? (
            <Typography variant="caption" color="text.secondary" textAlign="center">
              <Link to="/login" style={{ color: "inherit" }}>
                {t("common.cancel")}
              </Link>
            </Typography>
          ) : null}
        </Stack>
      </Paper>

      <Dialog open={changeOpen} onClose={() => !cpBusy && setChangeOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>{t("login.changePasswordTitle")}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            {cpErr ? <Alert severity="warning">{cpErr}</Alert> : null}
            <TextField label={t("people.colUsername")} value={cpUser} onChange={(e) => setCpUser(e.target.value)} size="small" fullWidth />
            <TextField
              label={t("profile.organization")}
              value={cpSlug}
              onChange={(e) => setCpSlug(e.target.value)}
              size="small"
              fullWidth
              placeholder="slug"
            />
            <TextField
              label={t("account.currentPassword")}
              type="password"
              value={cpCurrent}
              onChange={(e) => setCpCurrent(e.target.value)}
              size="small"
              fullWidth
            />
            <TextField
              label={t("account.newPassword")}
              type="password"
              value={cpNew}
              onChange={(e) => setCpNew(e.target.value)}
              size="small"
              fullWidth
              helperText={t("account.passwordMin")}
            />
            <TextField
              label={t("account.confirmPassword")}
              type="password"
              value={cpConfirm}
              onChange={(e) => setCpConfirm(e.target.value)}
              size="small"
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setChangeOpen(false)} disabled={cpBusy}>
            {t("common.cancel")}
          </Button>
          <Button variant="contained" onClick={submitChangePassword} disabled={cpBusy}>
            {t("common.save")}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={resetOpen} onClose={() => !rsBusy && setResetOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>{t("login.resetPasswordTitle")}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            {rsErr ? <Alert severity="warning">{rsErr}</Alert> : null}
            {rsMsg ? <Alert severity="info">{rsMsg}</Alert> : null}
            <Typography variant="body2" color="text.secondary">
              {t("login.resetRequestExplain")}
            </Typography>
            <TextField label={t("people.colUsername")} value={rsUser} onChange={(e) => setRsUser(e.target.value)} size="small" fullWidth />
            <TextField
              label={t("profile.organization")}
              value={rsSlug}
              onChange={(e) => setRsSlug(e.target.value)}
              size="small"
              fullWidth
            />
            <Button variant="outlined" onClick={submitResetRequest} disabled={rsBusy || !rsUser.trim()}>
              {t("login.submitResetRequest")}
            </Button>
            {rsDevToken ? (
              <Alert severity="info" variant="outlined">
                Dev token (paste below if not auto-filled)
              </Alert>
            ) : null}
            <TextField
              label={t("login.resetTokenLabel")}
              value={rsToken}
              onChange={(e) => setRsToken(e.target.value)}
              size="small"
              fullWidth
            />
            <TextField
              label={t("login.newPasswordReset")}
              type="password"
              value={rsNew}
              onChange={(e) => setRsNew(e.target.value)}
              size="small"
              fullWidth
            />
            <Button variant="contained" onClick={submitResetComplete} disabled={rsBusy || !rsToken.trim() || rsNew.length < 8}>
              {t("login.completePasswordReset")}
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetOpen(false)} disabled={rsBusy}>
            {t("common.cancel")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default LoginPage;
