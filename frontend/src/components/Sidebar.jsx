import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Box, Button, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import { getClockPayrollUiSettings } from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { TENANT_NAV_ITEMS, tenantNavItemVisible } from "../constants/tenantNav";
import { isRinseScheduleOnlyUser } from "../utils/platformAccess";
import TenantLogo from "./TenantLogo";

function CompactLanguageToggle({ locale, setLocale }) {
  return (
    <Stack direction="row" spacing={0.5} alignItems="center">
      {["en", "es"].map((code) => {
        const selected = locale === code;
        return (
          <Button
            key={code}
            size="small"
            onClick={() => setLocale(code)}
            sx={{
              minWidth: 34,
              px: 1,
              py: 0.35,
              fontSize: 11,
              fontWeight: 700,
              lineHeight: 1.2,
              borderRadius: 1,
              textTransform: "uppercase",
              boxShadow: "none",
              ...(selected
                ? { bgcolor: "#0f172a", color: "#fff", "&:hover": { bgcolor: "#1e293b" } }
                : {
                    bgcolor: "transparent",
                    color: "#64748b",
                    "&:hover": { bgcolor: "#f1f5f9", color: "#334155" },
                  }),
            }}
          >
            {code}
          </Button>
        );
      })}
    </Stack>
  );
}

function RinseClientSidebar({ user, onLogout, locale, setLocale, t, navItems }) {
  return (
    <Box
      className="no-print app-shell-sidebar rinse-client-sidebar"
      sx={{
        width: 220,
        minHeight: "100vh",
        height: "100%",
        maxHeight: "100vh",
        bgcolor: "#ffffff",
        borderRight: "1px solid #e2e8f0",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <Box
        sx={{
          px: 2,
          py: 2.25,
          borderBottom: "1px solid #e2e8f0",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 1,
          flexShrink: 0,
        }}
      >
        <TenantLogo logoUrl={user?.organization_logo_url} size={52} />
        <Typography
          sx={{
            fontSize: 15,
            fontWeight: 800,
            color: "#0f172a",
            letterSpacing: "-0.02em",
            textAlign: "center",
          }}
          noWrap
        >
          {user?.organization_name || t("common.appName")}
        </Typography>
      </Box>

      <Box sx={{ flex: 1, px: 1.5, py: 2, minHeight: 0 }}>
        <Stack spacing={0.75}>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              style={({ isActive }) => ({
                display: "block",
                textDecoration: "none",
                padding: "11px 14px",
                borderRadius: "10px",
                color: isActive ? "#ffffff" : "#334155",
                background: isActive ? "#0f766e" : "#f8fafc",
                border: isActive ? "1px solid #0f766e" : "1px solid #e2e8f0",
                fontSize: 14,
                fontWeight: isActive ? 700 : 600,
              })}
            >
              {t(item.labelKey)}
            </NavLink>
          ))}
        </Stack>
      </Box>

      <Box
        sx={{
          px: 1.5,
          py: 1.25,
          borderTop: "1px solid #e2e8f0",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1,
          flexShrink: 0,
        }}
      >
        <CompactLanguageToggle locale={locale} setLocale={setLocale} />
        <Tooltip title={t("nav.logout")}>
          <IconButton
            size="small"
            onClick={onLogout}
            aria-label={t("nav.logout")}
            sx={{ color: "#64748b", "&:hover": { color: "#0f172a", bgcolor: "#f1f5f9" } }}
          >
            <LogoutOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  );
}

function SidebarHeader({ user, t }) {
  return (
    <Box
      sx={{
        px: 1.5,
        py: 2,
        bgcolor: "#ffffff",
        borderBottom: "1px solid #e2e8f0",
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
  const rinseOnly = isRinseScheduleOnlyUser(user);

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
  const navItems = TENANT_NAV_ITEMS.filter(allow);

  if (rinseOnly) {
    return (
      <RinseClientSidebar
        user={user}
        onLogout={onLogout}
        locale={locale}
        setLocale={setLocale}
        t={t}
        navItems={navItems}
      />
    );
  }

  const showLock = showKioskLock;
  const showBatch = Boolean(activeBatch);

  return (
    <Box
      className="no-print app-shell-sidebar"
      sx={{
        width: 240,
        minHeight: "100vh",
        height: "100%",
        maxHeight: "100vh",
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

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          p: 1.5,
          pb: "calc(12px + env(safe-area-inset-bottom, 0px))",
        }}
      >
        {showLock ? (
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

        {showBatch ? (
          <Box
            sx={{
              mb: 1.2,
              px: 1,
              py: 0.5,
              borderRadius: 999,
              bgcolor: "#0b3b77",
              color: "#dbeafe",
              fontSize: 11,
              fontWeight: 700,
              alignSelf: "flex-start",
              flexShrink: 0,
            }}
          >
            Batch #{activeBatch.id} {String(activeBatch.state || "").toUpperCase()}
          </Box>
        ) : null}

        <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", pr: 0.5, WebkitOverflowScrolling: "touch" }}>
          <Stack spacing={0.8}>
            {navItems.map((item) => (
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

        <Box
          sx={{
            mt: 1.5,
            pt: 1.25,
            borderTop: "1px solid #334155",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1,
          }}
        >
          <CompactLanguageToggle locale={locale} setLocale={setLocale} />
          <Button
            size="small"
            variant="text"
            onClick={onLogout}
            startIcon={<LogoutOutlinedIcon sx={{ fontSize: 16 }} />}
            sx={{
              color: "#94a3b8",
              fontWeight: 600,
              textTransform: "none",
              "&:hover": { color: "#f8fafc", bgcolor: "rgba(255,255,255,0.06)" },
            }}
          >
            {t("nav.logout")}
          </Button>
        </Box>
      </Box>
    </Box>
  );
}

export default Sidebar;
export { SidebarHeader, CompactLanguageToggle, RinseClientSidebar };
