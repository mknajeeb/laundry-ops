import { useState } from "react";
import { NavLink } from "react-router-dom";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  TextField,
  Typography,
} from "@mui/material";
import { useI18n } from "../i18n/I18nContext";
import { putAuthPassword } from "../api";

export default function PlatformSidebar({ user, onLogout, showTenantEntry = false }) {
  const { t } = useI18n();
  const [pwdOpen, setPwdOpen] = useState(false);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwdErr, setPwdErr] = useState("");
  const [pwdSaving, setPwdSaving] = useState(false);

  const tenantLine =
    user?.organization_name ||
    (user?.organization_slug ? String(user.organization_slug).toUpperCase() : "") ||
    t("platform.sidebarPlatformContext");
  const userLine = user?.display_name || user?.username || "";

  async function submitPassword() {
    setPwdErr("");
    if (newPw.length < 8) {
      setPwdErr(t("account.passwordMin"));
      return;
    }
    if (newPw !== confirmPw) {
      setPwdErr(t("account.passwordMismatch"));
      return;
    }
    setPwdSaving(true);
    try {
      await putAuthPassword({ current_password: currentPw, new_password: newPw });
      setPwdOpen(false);
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (e) {
      setPwdErr(e?.response?.data?.error || e?.message || "Failed");
    } finally {
      setPwdSaving(false);
    }
  }

  return (
    <Box
      sx={{
        width: 260,
        minHeight: "100vh",
        p: 2,
        background: "linear-gradient(165deg, #0f172a 0%, #1e1b4b 42%, #312e81 100%)",
        color: "#e0e7ff",
        borderRight: "1px solid rgba(255,255,255,0.08)",
        display: "flex",
        flexDirection: "column",
        boxSizing: "border-box",
      }}
    >
      <Box
        sx={{
          borderRadius: 2,
          p: 1.5,
          mb: 2,
          background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(255,255,255,0.1)",
        }}
      >
        <Typography sx={{ fontSize: 11, letterSpacing: 1.2, color: "#a5b4fc", fontWeight: 600, mb: 0.5 }}>
          {t("platform.consoleLabel")}
        </Typography>
        <Typography sx={{ fontSize: 22, fontWeight: 800, color: "#fff", lineHeight: 1.15 }}>
          {t("platform.productName")}
        </Typography>
        <Divider sx={{ borderColor: "rgba(255,255,255,0.12)", my: 1.25 }} />
        <Typography sx={{ fontSize: 12, color: "#c7d2fe", fontWeight: 600, mb: 0.25 }}>
          {t("platform.sidebarTenant")}
        </Typography>
        <Typography sx={{ fontSize: 15, color: "#fff", fontWeight: 500, mb: 1 }}>
          {tenantLine}
        </Typography>
        <Typography sx={{ fontSize: 12, color: "#c7d2fe", fontWeight: 600, mb: 0.25 }}>
          {t("platform.sidebarSignedInAs")}
        </Typography>
        <Typography sx={{ fontSize: 14, color: "#e0e7ff" }}>{userLine}</Typography>
      </Box>

      <NavLink
        to="/platform"
        end
        style={({ isActive }) => ({
          display: "block",
          textDecoration: "none",
          padding: "12px 14px",
          borderRadius: "10px",
          color: isActive ? "#1e1b4b" : "#e0e7ff",
          background: isActive ? "#eef2ff" : "rgba(255,255,255,0.08)",
          fontSize: 15,
          fontWeight: 600,
          marginBottom: 8,
        })}
      >
        {t("platform.tenantsNav")}
      </NavLink>
      {showTenantEntry ? (
        <NavLink
          to="/"
          style={({ isActive }) => ({
            display: "block",
            textDecoration: "none",
            padding: "12px 14px",
            borderRadius: "10px",
            color: isActive ? "#1e1b4b" : "#e0e7ff",
            background: isActive ? "#eef2ff" : "rgba(255,255,255,0.06)",
            fontSize: 14,
            marginBottom: 8,
            border: "1px solid rgba(255,255,255,0.12)",
          })}
        >
          {t("platform.backToTenant")}
        </NavLink>
      ) : null}

      <Box sx={{ flex: 1 }} />

      <Button
        fullWidth
        variant="text"
        onClick={() => setPwdOpen(true)}
        sx={{ color: "#c7d2fe", mb: 1, textTransform: "none", justifyContent: "flex-start" }}
      >
        {t("platform.changePassword")}
      </Button>
      <Button
        variant="outlined"
        color="inherit"
        fullWidth
        onClick={onLogout}
        sx={{ borderColor: "rgba(255,255,255,0.35)", color: "#fff" }}
      >
        {t("nav.logout")}
      </Button>

      <Dialog open={pwdOpen} onClose={() => !pwdSaving && setPwdOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t("platform.changePassword")}</DialogTitle>
        <DialogContent>
          {pwdErr ? (
            <Typography color="error" variant="body2" sx={{ mb: 1 }}>
              {pwdErr}
            </Typography>
          ) : null}
          <TextField
            margin="dense"
            label={t("account.currentPassword")}
            type="password"
            fullWidth
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
          />
          <TextField
            margin="dense"
            label={t("account.newPassword")}
            type="password"
            fullWidth
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            helperText={t("account.passwordMin")}
          />
          <TextField
            margin="dense"
            label={t("account.confirmPassword")}
            type="password"
            fullWidth
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPwdOpen(false)} disabled={pwdSaving}>
            {t("common.cancel")}
          </Button>
          <Button variant="contained" onClick={submitPassword} disabled={pwdSaving || !currentPw || !newPw}>
            {pwdSaving ? t("common.saving") : t("common.save")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
