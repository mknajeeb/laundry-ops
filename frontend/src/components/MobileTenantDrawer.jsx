import { Box, Chip, Divider, Drawer, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import { useNavigate, useLocation } from "react-router-dom";
import { TENANT_NAV_ITEMS } from "../constants/tenantNav";
import { useI18n } from "../i18n/I18nContext";
import { hasPlatformAdminRole, isTenantModuleEnabled, userSatisfiesRoleGate } from "../utils/platformAccess";

export default function MobileTenantDrawer({
  open,
  onClose,
  user,
  payrollNavVisible = true,
  activeBatch,
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const allow = (item) => {
    const roleOk = !item.roles.length || userSatisfiesRoleGate(user, item.roles);
    if (!roleOk) return false;
    if (item.skipModuleCheck) {
      return hasPlatformAdminRole(user);
    }
    return isTenantModuleEnabled(user, item.moduleKey || "home");
  };

  const navFilter = (item) => {
    if (item.to === "/payroll" && !payrollNavVisible) return false;
    return true;
  };

  const go = (to) => {
    navigate(to);
    onClose();
  };

  return (
    <Drawer anchor="left" open={open} onClose={onClose}>
      <Box sx={{ width: 280, pt: "env(safe-area-inset-top, 12px)", px: 1.5, pb: 2 }}>
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
        <List dense disablePadding>
          {TENANT_NAV_ITEMS.filter(allow).filter(navFilter).map((item) => (
            <ListItemButton
              key={item.to}
              selected={pathname === item.to || (item.to !== "/" && pathname.startsWith(item.to))}
              onClick={() => go(item.to)}
            >
              <ListItemText primary={t(item.labelKey)} primaryTypographyProps={{ fontSize: 16 }} />
            </ListItemButton>
          ))}
        </List>
      </Box>
    </Drawer>
  );
}
