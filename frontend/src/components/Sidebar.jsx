import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Box, Button, Stack, Typography } from "@mui/material";
import { getClockPayrollUiSettings } from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { TENANT_NAV_ITEMS, tenantNavItemVisible } from "../constants/tenantNav";
import { isRinseScheduleOnlyUser } from "../utils/platformAccess";
import TenantLogo from "./TenantLogo";

function LanguageToggle({ locale, setLocale, t }) {
  const options = [
    { value: "en", label: t("lang.en") },
    { value: "es", label: t("lang.es") },
  ];

  return (
    <Stack direction="row" spacing={0.75} sx={{ mb: 1.2, flexShrink: 0 }}>
      {options.map((opt) => {
        const selected = locale === opt.value;
        return (
          <Button
            key={opt.value}
            size="small"
            fullWidth
            variant={selected ? "contained" : "outlined"}
            onClick={() => setLocale(opt.value)}
            sx={{
              py: 0.65,
              fontSize: 12,
              fontWeight: 700,
              textTransform: "none",
              borderRadius: 1.5,
              boxShadow: "none",
              ...(selected
                ? {
                    bgcolor: "#ffffff",
                    color: "#0f172a",
                    borderColor: "#ffffff",
                    "&:hover": { bgcolor: "#f8fafc", boxShadow: "none" },
                  }
                : {
                    bgcolor: "transparent",
                    color: "#e2e8f0",
                    borderColor: "#64748b",
                    "&:hover": {
                      bgcolor: "rgba(255,255,255,0.08)",
                      borderColor: "#94a3b8",
                      color: "#ffffff",
                    },
                  }),
            }}
          >
            {opt.label}
          </Button>
        );
      })}
    </Stack>
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
  const showLock = showKioskLock && !rinseOnly;
  const showBatch = activeBatch && !rinseOnly;

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

        <Typography
          sx={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "#94a3b8",
            mb: 0.5,
            flexShrink: 0,
          }}
        >
          {t("lang.label")}
        </Typography>
        <LanguageToggle locale={locale} setLocale={setLocale} t={t} />

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
    </Box>
  );
}

export default Sidebar;
export { SidebarHeader, LanguageToggle };
