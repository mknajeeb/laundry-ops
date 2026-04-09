import { Box, Button, Chip, Divider, Drawer, List, ListItemButton, ListItemText, Typography } from "@mui/material";
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
  const { t } = useI18n();
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
      PaperProps={{ sx: { display: "flex", flexDirection: "column", maxHeight: "100%" } }}
    >
      <Box
        sx={{
          width: 280,
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          pt: "env(safe-area-inset-top, 12px)",
          px: 1.5,
        }}
      >
        <Typography sx={{ fontWeight: 700, fontSize: 18, px: 1, py: 1 }}>
          {user?.organization_name || "Menu"}
        </Typography>
        <Typography sx={{ fontSize: 13, color: "text.secondary", px: 1, pb: 1 }}>
          {user?.display_name || user?.username}
        </Typography>
        {activeBatch && (
          <Chip
            size="small"
            label={`Batch #${activeBatch.id} ${String(activeBatch.state || "").toUpperCase()}`}
            sx={{ ml: 1, mb: 1 }}
          />
        )}
        <Divider sx={{ my: 1 }} />
        <List dense disablePadding sx={{ flex: 1, overflow: "auto" }}>
          {TENANT_NAV_ITEMS.filter(allow).map((item) => (
            <ListItemButton
              key={item.to}
              selected={pathname === item.to || (item.to !== "/" && pathname.startsWith(item.to))}
              onClick={() => go(item.to)}
            >
              <ListItemText primary={t(item.labelKey)} primaryTypographyProps={{ fontSize: 16 }} />
            </ListItemButton>
          ))}
        </List>
        <Divider sx={{ mt: 1 }} />
        <Box sx={{ py: 2, pb: "calc(16px + env(safe-area-inset-bottom, 0px))" }}>
          <Button fullWidth variant="outlined" color="inherit" onClick={handleLogout}>
            {t("nav.logout")}
          </Button>
        </Box>
      </Box>
    </Drawer>
  );
}
