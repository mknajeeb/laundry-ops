import { Box, Button, Divider, Drawer, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import { LanguageToggle, SidebarHeader } from "./Sidebar";
import { useNavigate, useLocation } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";
import { useAuth } from "../context/AuthContext";
import { tenantNavItemVisible, TENANT_NAV_ITEMS } from "../constants/tenantNav";
import { isRinseScheduleOnlyUser } from "../utils/platformAccess";

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

  const go = (to) => {
    navigate(to);
    onClose();
  };

  const handleLogout = () => {
    onClose();
    onLogout?.();
  };

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
          <Typography sx={{ fontSize: 13, color: "#94a3b8", px: 0.25, py: 1 }} noWrap>
            {user?.display_name || user?.username}
          </Typography>
          <Typography
            sx={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "#94a3b8",
              mb: 0.5,
              px: 0.25,
            }}
          >
            {t("lang.label")}
          </Typography>
          <LanguageToggle locale={locale} setLocale={setLocale} t={t} />

          {activeBatch && !rinseOnly ? (
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
            {TENANT_NAV_ITEMS.filter(allow).map((item) => (
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
          <Box sx={{ py: 2 }}>
            <Button
              fullWidth
              variant="outlined"
              onClick={handleLogout}
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
