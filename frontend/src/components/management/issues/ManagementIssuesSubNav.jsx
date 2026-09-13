import { Box, Button, Stack, Typography } from "@mui/material";
import { Link as RouterLink, useLocation } from "react-router-dom";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";

const LINKS = [
  { to: "/management/issues", label: "Issues", exact: true },
  { to: "/management/issues/dashboard", label: "Dashboard" },
];

export default function ManagementIssuesSubNav() {
  const loc = useLocation();
  return (
    <Stack
      direction="row"
      spacing={1}
      alignItems="center"
      sx={{ mb: 1.5, flexWrap: "wrap", gap: 1 }}
    >
      {LINKS.map((l) => {
        const selected = l.exact
          ? loc.pathname === l.to
          : loc.pathname.startsWith(l.to);
        return (
          <Box
            key={l.to}
            component={RouterLink}
            to={l.to}
            sx={{
              px: 1.5,
              py: 0.85,
              minHeight: 40,
              borderRadius: 999,
              fontSize: 13,
              fontWeight: selected ? 800 : 600,
              textDecoration: "none",
              border: "1px solid",
              borderColor: selected
                ? VEEWASH_DASHBOARD.primaryBlue
                : "#e5e7eb",
              color: selected
                ? VEEWASH_DASHBOARD.primaryBlueDark
                : "#334155",
              bgcolor: selected
                ? VEEWASH_DASHBOARD.primaryBlueLight
                : "#fff",
              display: "inline-flex",
              alignItems: "center",
            }}
          >
            {l.label}
          </Box>
        );
      })}
      <Box sx={{ flex: 1 }} />
      <Button
        component={RouterLink}
        to="/management/issues/new"
        variant="contained"
        sx={{
          textTransform: "none",
          fontWeight: 800,
          minHeight: 44,
          px: 2,
          bgcolor: VEEWASH_DASHBOARD.primaryBlue,
          "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
        }}
      >
        + New Issue
      </Button>
    </Stack>
  );
}

export function IssuesPageShell({ title, children, showSubNav = true }) {
  return (
    <Box
      sx={{
        maxWidth: 960,
        mx: "auto",
        px: { xs: 1.5, sm: 2 },
        py: 1.5,
        pb: 4,
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <Typography
        sx={{
          fontWeight: 900,
          fontSize: { xs: 22, sm: 26 },
          color: VEEWASH_DASHBOARD.wfCharcoal,
          letterSpacing: -0.3,
          mb: 0.5,
        }}
      >
        {title}
      </Typography>
      {showSubNav ? <ManagementIssuesSubNav /> : null}
      {children}
    </Box>
  );
}
