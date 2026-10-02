import { Box, Paper, Stack, Typography } from "@mui/material";
import { formatRoleHoursLabel, ROLE_HOURS_EXPLANATION, roleStyle } from "./weeklyScheduleRoles";

function hoursText(hours) {
  return formatRoleHoursLabel(hours);
}

function SummaryCard({ title, children }) {
  return (
    <Paper
      elevation={0}
      sx={{ border: "1px solid #e2e8f0", borderRadius: 2, p: 1.25, flex: 1, minWidth: 0, bgcolor: "#fff" }}
    >
      <Typography variant="overline" sx={{ fontWeight: 800, letterSpacing: "0.08em", lineHeight: 1.6 }}>
        {title}
      </Typography>
      {children}
    </Paper>
  );
}

function Row({ label, value, sub, accent, bold = false }) {
  return (
    <Stack
      direction="row"
      alignItems="center"
      spacing={1}
      sx={{ py: 0.35, borderBottom: "1px solid #f1f5f9", "&:last-of-type": { borderBottom: "none" } }}
    >
      {accent ? <Box sx={{ width: 4, alignSelf: "stretch", borderRadius: 1, bgcolor: accent, flexShrink: 0 }} /> : null}
      <Typography variant="body2" sx={{ flex: 1, minWidth: 0, fontWeight: bold ? 800 : 600 }} noWrap>
        {label}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "nowrap" }}>
          {sub}
        </Typography>
      ) : null}
      <Typography variant="body2" sx={{ fontWeight: 800, minWidth: 48, textAlign: "right" }}>
        {value}
      </Typography>
    </Stack>
  );
}

export default function WeeklyScheduleHoursSummary({ summary, scopeLabel = "" }) {
  if (!summary) return null;
  const { employees, totalHours, roles, roleTotal, unassignedHours } = summary;
  return (
    <Box className="no-print" sx={{ mb: 1.25 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.25}>
        <SummaryCard title={`Employee hours${scopeLabel ? ` · ${scopeLabel}` : ""}`}>
          <Box sx={{ maxHeight: 220, overflow: "auto" }}>
            {employees.length ? (
              employees.map((row) => <Row key={row.user_id} label={row.name} value={hoursText(row.hours)} />)
            ) : (
              <Typography variant="body2" color="text.secondary">
                No scheduled hours.
              </Typography>
            )}
          </Box>
          <Row
            label={`Total · ${employees.length} employee${employees.length === 1 ? "" : "s"}`}
            value={hoursText(totalHours)}
            bold
          />
        </SummaryCard>
        <SummaryCard title="Role hours & resources">
          <Box sx={{ maxHeight: 220, overflow: "auto" }}>
            {roles.length ? (
              roles.map((row) => (
                <Row
                  key={row.role}
                  label={row.label}
                  sub={`${row.employees} employee${row.employees === 1 ? "" : "s"}`}
                  value={hoursText(row.hours)}
                  accent={roleStyle(row.role).accent}
                />
              ))
            ) : (
              <Typography variant="body2" color="text.secondary">
                No roles scheduled.
              </Typography>
            )}
            {unassignedHours > 0 ? (
              <Row label="Shift time without a role" value={hoursText(unassignedHours)} />
            ) : null}
          </Box>
          <Row label="Total role hours" value={hoursText(roleTotal)} bold />
        </SummaryCard>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75, px: 0.25 }}>
        {ROLE_HOURS_EXPLANATION}
      </Typography>
    </Box>
  );
}
