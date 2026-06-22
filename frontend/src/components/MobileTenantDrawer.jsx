import { Box, Button, Divider, Drawer, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import { CompactLanguageToggle, SidebarHeader } from "./Sidebar";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { useNavigate, useLocation } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";
import { useAuth } from "../context/AuthContext";
import { tenantNavItemVisible, TENANT_NAV_ITEMS } from "../constants/tenantNav";
import { isRinseScheduleOnlyUser } from "../utils/platformAccess";
import TenantLogo from "./TenantLogo";

export default function MobileTenantDrawer({
  open,
  onClose,
  user,
  payrollNavVisible = true,
  activeBatch,
  onLogout,
}) {
  const { t, locale, setLocale } = useI18n();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { hasPerm } = useAuth();
  const rinseOnly = isRinseScheduleOnlyUser(user);

  const allow = (item) => tenantNavItemVisible(user, item, payrollNavVisible, hasPerm);
  const navItems = TENANT_NAV_ITEMS.filter(allow);

  const go = (to) => {
    navigate(to);
    onClose();
  };

  const handleLogout = () => {
    onClose();
    onLogout?.();
  };

  if (rinseOnly) {
    return (
      <Drawer anchor="left" open={open} onClose={onClose} PaperProps={{ sx: { bgcolor: VEEWASH_DASHBOARD.pageBackground } }}>
        <Box sx={{ width: 280, minHeight: "100%", display: "flex", flexDirection: "column" }}>
          <Box sx={{ px: 2, py: 2, borderBottom: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`, textAlign: "center", bgcolor: "#fff" }}>
            <TenantLogo logoUrl={user?.organization_logo_url} size={48} />
            <Typography sx={{ mt: 1, fontWeight: 800, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
              {user?.organization_name || t("common.appName")}
            </Typography>
          </Box>
          <List dense disablePadding sx={{ flex: 1, px: 1.5, py: 1.5 }}>
            {navItems.map((item) => (
              <ListItemButton
                key={item.to}
                selected={pathname === item.to || pathname.startsWith(`${item.to}/`)}
                onClick={() => go(item.to)}
                sx={{
                  borderRadius: 2,
                  mb: 0.5,
                  border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                  "&.Mui-selected": {
                    bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                    color: "#fff",
                    borderColor: VEEWASH_DASHBOARD.primaryBlue,
                    "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
                  },
                }}
              >
                <ListItemText primary={t(item.labelKey)} primaryTypographyProps={{ fontWeight: 600 }} />
              </ListItemButton>
            ))}
          </List>
          <Box
            sx={{
              px: 1.5,
              py: 1.5,
              borderTop: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              bgcolor: "#fff",
            }}
          >
            <CompactLanguageToggle locale={locale} setLocale={setLocale} tone="light" />
            <Button size="small" startIcon={<LogoutOutlinedIcon />} onClick={handleLogout} sx={{ color: "#64748b" }}>
              {t("nav.logout")}
            </Button>
          </Box>
        </Box>
      </Drawer>
    );
  }

  return (
    <Drawer
      anchor="left"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          display: "flex",
          flexDirection: "column",
          maxHeight: "100%",
          bgcolor: "#0f172a",
          color: "#e2e8f0",
        },
      }}
    >
      <Box
        sx={{
          width: 280,
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          pt: "env(safe-area-inset-top, 0px)",
          pb: "calc(12px + env(safe-area-inset-bottom, 0px))",
        }}
      >
        <SidebarHeader user={user} t={t} />

        <Box sx={{ px: 1.5, flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {activeBatch ? (
            <Box
              sx={{
                mb: 1,
                px: 1,
                py: 0.5,
                borderRadius: 999,
                bgcolor: "#0b3b77",
                color: "#dbeafe",
                fontSize: 11,
                fontWeight: 700,
                alignSelf: "flex-start",
              }}
            >
              Batch #{activeBatch.id} {String(activeBatch.state || "").toUpperCase()}
            </Box>
          ) : null}

          <Divider sx={{ my: 1, borderColor: "#1f2937" }} />
          <List dense disablePadding sx={{ flex: 1, overflow: "auto" }}>
            {navItems.map((item) => (
              <ListItemButton
                key={item.to}
                selected={pathname === item.to || (item.to !== "/" && pathname.startsWith(item.to))}
                onClick={() => go(item.to)}
                sx={{
                  borderRadius: 1.25,
                  mb: 0.5,
                  color: "#e2e8f0",
                  "&.Mui-selected": {
                    bgcolor: "#f8fafc",
                    color: "#0f172a",
                    fontWeight: 700,
                    "&:hover": { bgcolor: "#f1f5f9" },
                  },
                  "&:hover": { bgcolor: "#1e293b" },
                }}
              >
                <ListItemText primary={t(item.labelKey)} primaryTypographyProps={{ fontSize: 15, fontWeight: 500 }} />
              </ListItemButton>
            ))}
          </List>
          <Divider sx={{ mt: 1, borderColor: "#1f2937" }} />
          <Box
            sx={{
              py: 2,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 1,
            }}
          >
            <CompactLanguageToggle locale={locale} setLocale={setLocale} />
            <Button
              size="small"
              variant="outlined"
              onClick={handleLogout}
              startIcon={<LogoutOutlinedIcon sx={{ fontSize: 16 }} />}
              sx={{
                borderColor: "#475569",
                color: "#e2e8f0",
                fontWeight: 600,
                "&:hover": { borderColor: "#94a3b8", bgcolor: "rgba(255,255,255,0.06)" },
              }}
            >
              {t("nav.logout")}
            </Button>
          </Box>
        </Box>
      </Box>
    </Drawer>
  );
}
