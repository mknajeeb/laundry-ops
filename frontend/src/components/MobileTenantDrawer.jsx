import { Box, Button, Chip, Divider, Drawer, List, ListItemButton, ListItemText, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { SidebarHeader, langToggleSx } from "./Sidebar";
import { useNavigate, useLocation } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";
import { useAuth } from "../context/AuthContext";
import { tenantNavItemVisible, TENANT_NAV_ITEMS } from "../constants/tenantNav";

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
          px: 1.5,
          pb: "calc(12px + env(safe-area-inset-bottom, 0px))",
        }}
      >
        <SidebarHeader user={user} t={t} />
        <Typography sx={{ fontSize: 13, color: "#94a3b8", px: 0.25, pb: 1 }} noWrap>
          {user?.display_name || user?.username}
        </Typography>
        <Typography
          sx={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "#64748b",
            mb: 0.5,
            px: 0.25,
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
          sx={{ ...langToggleSx, mb: 1.25, px: 0.25 }}
        >
          <ToggleButton value="en">{t("lang.en")}</ToggleButton>
          <ToggleButton value="es">{t("lang.es")}</ToggleButton>
        </ToggleButtonGroup>
        {activeBatch && (
          <Chip
            size="small"
            label={`Batch #${activeBatch.id} ${String(activeBatch.state || "").toUpperCase()}`}
            sx={{ ml: 1, mb: 1 }}
          />
        )}
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
    </Drawer>
  );
}
