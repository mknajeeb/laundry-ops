import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Box, Button, Chip, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { getClockPayrollUiSettings } from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { TENANT_NAV_ITEMS, tenantNavItemVisible } from "../constants/tenantNav";
import TenantLogo from "./TenantLogo";

const langToggleSx = {
  flexShrink: 0,
  width: "100%",
  "& .MuiToggleButtonGroup-grouped": {
    flex: 1,
    borderColor: "#475569",
  },
  "& .MuiToggleButton-root": {
    py: 0.6,
    px: 1,
    fontSize: 12,
    fontWeight: 600,
    letterSpacing: "0.02em",
    textTransform: "none",
    color: "#cbd5e1",
    bgcolor: "rgba(15, 23, 42, 0.45)",
    borderColor: "#475569",
    "&:hover": {
      bgcolor: "rgba(30, 41, 59, 0.85)",
      color: "#f8fafc",
    },
    "&.Mui-selected": {
      bgcolor: "#ffffff",
      color: "#0f172a",
      fontWeight: 700,
      borderColor: "#e2e8f0",
      "&:hover": {
        bgcolor: "#f8fafc",
        color: "#0f172a",
      },
    },
  },
};

function SidebarHeader({ user, t }) {
  return (
    <Box
      sx={{
        mx: -1.5,
        mt: -1.5,
        mb: 1.25,
        px: 1.5,
        py: 2,
        bgcolor: "#ffffff",
        borderBottom: "1px solid #e2e8f0",
        boxShadow: "0 1px 0 rgba(15, 23, 42, 0.04)",
        flexShrink: 0,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, minWidth: 0 }}>
        <TenantLogo logoUrl={user?.organization_logo_url} size={44} />
        <Typography
          sx={{
            fontSize: 17,
            lineHeight: 1.25,
            color: "#0f172a",
            fontWeight: 700,
            letterSpacing: "-0.01em",
          }}
          noWrap
        >
          {user?.organization_name || t("common.appName")}
        </Typography>
      </Box>
    </Box>
  );
}

function Sidebar({ activeBatch, user, onLogout, showKioskLock, onKioskLock }) {
  const { locale, setLocale, t } = useI18n();
  const { loading: authLoading, hasPerm } = useAuth();
  const [payrollNavVisible, setPayrollNavVisible] = useState(true);

  useEffect(() => {
    if (authLoading || !user?.id) return;
    getClockPayrollUiSettings()
      .then((res) => {
        const v = res.data?.payroll?.nav_payroll_visible;
        setPayrollNavVisible(v !== false);
      })
      .catch(() => setPayrollNavVisible(true));
  }, [authLoading, user?.id]);

  const allow = (item) => tenantNavItemVisible(user, item, payrollNavVisible, hasPerm);

  return (
    <Box
      className="no-print app-shell-sidebar"
      sx={{
        width: 240,
        minHeight: "100vh",
        height: "100%",
        maxHeight: "100vh",
        p: 1.5,
        pb: "calc(12px + env(safe-area-inset-bottom, 0px))",
        background: "linear-gradient(180deg, #0f172a 0%, #111827 100%)",
        color: "#e2e8f0",
        borderRight: "1px solid #1f2937",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        boxSizing: "border-box",
      }}
    >
      <SidebarHeader user={user} t={t} />

      <Typography
        sx={{
          fontSize: 13,
          color: "#94a3b8",
          flexShrink: 0,
          px: 0.25,
          mb: 1,
        }}
        noWrap
      >
        {user?.display_name || user?.username}
      </Typography>

      {showKioskLock ? (
        <Button
          fullWidth
          size="small"
          variant="outlined"
          sx={{ mb: 1.2, flexShrink: 0, borderColor: "#475569", color: "#e2e8f0", py: 0.75 }}
          onClick={onKioskLock}
        >
          {t("nav.lockTablet")}
        </Button>
      ) : null}

      <Typography
        sx={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "#64748b",
          mb: 0.5,
          flexShrink: 0,
        }}
      >
        {t("lang.label")}
      </Typography>
      <ToggleButtonGroup
        size="small"
        exclusive
        fullWidth
        value={locale}
        onChange={(_, v) => {
          if (v !== null) setLocale(v);
        }}
        sx={{ ...langToggleSx, mb: 1.2 }}
      >
        <ToggleButton value="en">{t("lang.en")}</ToggleButton>
        <ToggleButton value="es">{t("lang.es")}</ToggleButton>
      </ToggleButtonGroup>

      {activeBatch && (
        <Chip
          label={`Batch #${activeBatch.id} ${String(activeBatch.state || "").toUpperCase()}`}
          size="small"
          sx={{ mb: 1.2, bgcolor: "#0b3b77", color: "#dbeafe", flexShrink: 0, alignSelf: "flex-start" }}
        />
      )}

      <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", pr: 0.5, WebkitOverflowScrolling: "touch" }}>
        <Stack spacing={0.8}>
          {TENANT_NAV_ITEMS.filter(allow).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              style={({ isActive }) => ({
                display: "block",
                textDecoration: "none",
                padding: "12px 14px",
                borderRadius: "10px",
                color: isActive ? "#0f172a" : "#e2e8f0",
                background: isActive ? "#f8fafc" : "#1e293b",
                fontSize: 15,
                fontWeight: isActive ? 700 : 500,
                transition: "background 0.15s ease, color 0.15s ease",
              })}
            >
              {t(item.labelKey)}
            </NavLink>
          ))}
        </Stack>
      </Box>

      <Button
        fullWidth
        sx={{
          mt: 1.5,
          flexShrink: 0,
          borderColor: "#475569",
          color: "#e2e8f0",
          py: 0.85,
          fontWeight: 600,
          "&:hover": {
            borderColor: "#94a3b8",
            bgcolor: "rgba(255,255,255,0.06)",
          },
        }}
        variant="outlined"
        onClick={onLogout}
      >
        {t("nav.logout")}
      </Button>
    </Box>
  );
}

export default Sidebar;
export { SidebarHeader, langToggleSx };
