import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Box, Button, Chip, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { getClockPayrollUiSettings } from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { TENANT_NAV_ITEMS, tenantNavItemVisible } from "../constants/tenantNav";
import TenantLogo from "./TenantLogo";

function Sidebar({ activeBatch, user, onLogout }) {
  const { locale, setLocale, t } = useI18n();
  const { loading: authLoading, hasPerm } = useAuth();
  const [payrollNavVisible, setPayrollNavVisible] = useState(true);
  const roles = (user?.roles || []).map((r) => String(r).toUpperCase());

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
      <Box sx={{ mb: 1, minHeight: 44, flexShrink: 0, display: "flex", alignItems: "center" }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.2, minWidth: 0 }}>
          <TenantLogo logoUrl={user?.organization_logo_url} size={40} />
          <Typography sx={{ fontSize: 22, lineHeight: 1.15, color: "#ffffff", fontWeight: 700 }} noWrap>
            {user?.organization_name || "Washpro"}
          </Typography>
        </Box>
      </Box>
      <Typography sx={{ fontSize: 13, color: "#94a3b8", flexShrink: 0 }}>
        {user?.display_name || user?.username}
      </Typography>
      <Stack direction="row" spacing={0.6} sx={{ mt: 0.6, mb: 1.2, flexWrap: "wrap", flexShrink: 0 }}>
        {roles.map((r) => <Chip key={r} label={r} size="small" sx={{ bgcolor: "#1e293b", color: "#cbd5e1" }} />)}
      </Stack>

      <Typography sx={{ fontSize: 11, color: "#94a3b8", mb: 0.5, flexShrink: 0 }}>{t("lang.label")}</Typography>
      <ToggleButtonGroup
        size="small"
        exclusive
        value={locale}
        onChange={(_, v) => {
          if (v !== null) setLocale(v);
        }}
        sx={{ mb: 1.2, flexShrink: 0, "& .MuiToggleButton-root": { py: 0.25, px: 1, fontSize: 12, color: "#e2e8f0", borderColor: "#334155" } }}
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
                fontSize: 16,
              })}
            >
              {t(item.labelKey)}
            </NavLink>
          ))}
        </Stack>
      </Box>

      <Button
        fullWidth
        sx={{ mt: 1.5, flexShrink: 0 }}
        variant="outlined"
        color="inherit"
        onClick={onLogout}
      >
        {t("nav.logout")}
      </Button>
    </Box>
  );
}

export default Sidebar;
