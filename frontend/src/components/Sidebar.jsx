import { NavLink } from "react-router-dom";
import { Box, Button, Chip, Stack, Typography } from "@mui/material";

const NAV_ITEMS = [
  { to: "/", label: "Home", roles: [] },
  { to: "/dashboard", label: "Dashboard", roles: [] },
  { to: "/orders", label: "Orders", roles: [] },
  { to: "/checkout", label: "Checkout", roles: [] },
  { to: "/upload", label: "Upload", roles: ["ADMIN", "OPS"] },
  { to: "/discrepancies", label: "Discrepancies", roles: ["ADMIN", "OPS"] },
  { to: "/inventory", label: "Inventory", roles: ["ADMIN", "OPS", "FRONT_DESK"] },
  { to: "/clock", label: "Clock", roles: [] },
  { to: "/issues", label: "Issues", roles: [] },
  { to: "/production", label: "Production", roles: [] },
  { to: "/scoreboard", label: "Scoreboard", roles: [] },
  { to: "/maintenance", label: "Maintenance", roles: [] },
  { to: "/employees", label: "Users", roles: ["ADMIN"] },
  { to: "/time-clock", label: "Time clock", roles: [] },
  { to: "/payroll-monitor", label: "Payroll monitor", roles: ["ADMIN", "OPS"] },
  { to: "/attendance-setup", label: "Attendance setup", roles: ["ADMIN"] },
  { to: "/ta-employees", label: "TA users", roles: ["ADMIN"] },
  { to: "/ta-login", label: "TA sign-in", roles: [] },
];

function Sidebar({ activeBatch, user, onLogout }) {
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
            {item.label}
          </NavLink>
        ))}
      </Stack>

      <Button sx={{ mt: 1.5 }} variant="outlined" color="inherit" onClick={onLogout}>Logout</Button>
    </Box>
  );
}

export default Sidebar;
