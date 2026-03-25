import { NavLink } from "react-router-dom";
import { Box, Button, Chip, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { useI18n } from "../i18n/I18nContext";

const NAV_ITEMS = [
  { to: "/", labelKey: "nav.home", roles: [] },
  { to: "/dashboard", labelKey: "nav.dashboard", roles: [] },
  { to: "/orders", labelKey: "nav.orders", roles: [] },
  { to: "/checkout", labelKey: "nav.checkout", roles: [] },
  { to: "/upload", labelKey: "nav.upload", roles: ["ADMIN", "OPS"] },
  { to: "/discrepancies", labelKey: "nav.discrepancies", roles: ["ADMIN", "OPS"] },
  { to: "/inventory", labelKey: "nav.inventory", roles: ["ADMIN", "OPS", "FRONT_DESK"] },
  { to: "/clock", labelKey: "nav.clock", roles: [] },
  { to: "/issues", labelKey: "nav.issues", roles: [] },
  { to: "/production", labelKey: "nav.production", roles: [] },
  { to: "/scoreboard", labelKey: "nav.scoreboard", roles: [] },
  { to: "/maintenance", labelKey: "nav.maintenance", roles: [] },
  { to: "/employees", labelKey: "nav.people", roles: ["ADMIN"] },
  { to: "/payroll-monitor", labelKey: "nav.payrollMonitor", roles: ["ADMIN", "OPS"] },
  { to: "/attendance-setup", labelKey: "nav.attendance", roles: ["ADMIN"] },
  { to: "/permissions", labelKey: "nav.permissions", roles: ["ADMIN"] },
];

function Sidebar({ activeBatch, user, onLogout }) {
  const { locale, setLocale, t } = useI18n();
  const roles = (user?.roles || []).map((r) => String(r).toUpperCase());
  const allow = (item) => !item.roles.length || item.roles.some((r) => roles.includes(r));

  return (
    <Box
      sx={{
        width: 240,
        minHeight: "100vh",
        p: 1.5,
        background: "linear-gradient(180deg, #0f172a 0%, #111827 100%)",
        color: "#e2e8f0",
        borderRight: "1px solid #1f2937",
      }}
    >
      <Typography sx={{ fontSize: 40, lineHeight: 1, color: "#ffffff", mb: 0.5 }}>Washpro</Typography>
      <Typography sx={{ fontSize: 13, color: "#94a3b8" }}>
        {user?.display_name || user?.username}
      </Typography>
      <Stack direction="row" spacing={0.6} sx={{ mt: 0.6, mb: 1.2, flexWrap: "wrap" }}>
        {roles.map((r) => <Chip key={r} label={r} size="small" sx={{ bgcolor: "#1e293b", color: "#cbd5e1" }} />)}
      </Stack>

      <Typography sx={{ fontSize: 11, color: "#94a3b8", mb: 0.5 }}>{t("lang.label")}</Typography>
      <ToggleButtonGroup
        size="small"
        exclusive
        value={locale}
        onChange={(_, v) => v && setLocale(v)}
        sx={{ mb: 1.2, "& .MuiToggleButton-root": { py: 0.25, px: 1, fontSize: 12, color: "#e2e8f0", borderColor: "#334155" } }}
      >
        <ToggleButton value="en">{t("lang.en")}</ToggleButton>
        <ToggleButton value="es">{t("lang.es")}</ToggleButton>
      </ToggleButtonGroup>

      {activeBatch && (
        <Chip
          label={`Batch #${activeBatch.id} ${String(activeBatch.state || "").toUpperCase()}`}
          size="small"
          sx={{ mb: 1.2, bgcolor: "#0b3b77", color: "#dbeafe" }}
        />
      )}

      <Stack spacing={0.8}>
        {NAV_ITEMS.filter(allow).map((item) => (
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

      <Button sx={{ mt: 1.5 }} variant="outlined" color="inherit" onClick={onLogout}>{t("nav.logout")}</Button>
    </Box>
  );
}

export default Sidebar;
