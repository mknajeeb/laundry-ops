import { Box, Paper, Stack, Typography } from "@mui/material";
import {
  formatHours,
  formatRoleHoursValue,
  ROLE_HOURS_EXPLANATION,
  roleStyle,
  UNALLOCATED_BREAK_NOTE,
} from "./weeklyScheduleRoles";

function hoursText(hours) {
  return `${formatHours(hours)}h`;
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

export default function WeeklyScheduleHoursSummary({ summary, scopeLabel = "", showBreaks = true }) {
  if (!summary) return null;
  const { employees, totalHours, roles } = summary;
  const unscheduledBreak = Number(summary.unscheduledBreakHours || 0);
  const pending = Number(summary.unallocatedBreakHours || 0) > 0.0001;
  const roleUnallocated = Number(summary.roleUnallocatedBreakHours || 0);
  const people = summary.distinctEmployees ?? employees.length;
  return (
    <Box className="no-print" sx={{ mb: 1.25 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.25}>
        <SummaryCard title={`Employee hours${scopeLabel ? ` · ${scopeLabel}` : ""}`}>
          <Box sx={{ maxHeight: 220, overflow: "auto" }}>
            {employees.length ? (
              employees.map((row) => (
                <Row
                  key={row.user_id}
                  label={row.name}
                  sub={
                    row.unallocatedBreakHours > 0
                      ? `gross of ${showBreaks ? `${hoursText(row.unallocatedBreakHours)} ` : ""}unallocated break`
                      : showBreaks && row.breakHours > 0
                        ? `${hoursText(row.grossHours)} − ${hoursText(row.breakHours)} break`
                        : ""
                  }
                  value={hoursText(row.hours)}
                />
              ))
            ) : (
              <Typography variant="body2" color="text.secondary">
                No scheduled hours.
              </Typography>
            )}
          </Box>
          {showBreaks ? (
            <>
              <Row label="Gross scheduled hours" value={hoursText(summary.grossHours)} />
              <Row
                label="Break hours"
                sub={unscheduledBreak > 0 ? `${hoursText(unscheduledBreak)} not scheduled` : ""}
                value={`−${hoursText(summary.breakHours)}`}
              />
            </>
          ) : null}
          <Row
            label={`${pending ? "Gross of unallocated break" : showBreaks ? "Net" : "Total"} · ${employees.length} ${employees.length === 1 ? "person" : "people"}`}
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
                  sub={`${row.employees} ${row.employees === 1 ? "person" : "people"}`}
                  value={`${formatRoleHoursValue(row.hours, row.unallocatedBreakHours)}h`}
                  accent={roleStyle(row.role).accent}
                />
              ))
            ) : (
              <Typography variant="body2" color="text.secondary">
                No roles scheduled.
              </Typography>
            )}
            {summary.unassignedHours > 0 ? (
              <Row label={summary.unassignedLabel || "Shift time without a role"} value={hoursText(summary.unassignedHours)} />
            ) : null}
            {roleUnallocated > 0 ? (
              <Row
                label="Breaks without a time not allocated to a role"
                value={showBreaks ? `−${hoursText(roleUnallocated)}` : "—"}
              />
            ) : null}
          </Box>
          <Row
            label={
              summary.roleFilter
                ? `Total · selected roles (${pending ? "gross of unallocated break" : "net"})`
                : "Total net hours"
            }
            sub={`${people} ${people === 1 ? "person" : "people"}`}
            value={hoursText(totalHours)}
            bold
          />
          {roleUnallocated > 0 ? (
            <Typography variant="caption" data-role-hours-unresolved sx={{ display: "block", mt: 0.25, color: "#9a3412", fontWeight: 700 }}>
              Role hours marked gross include breaks without a time on shifts with several roles. {UNALLOCATED_BREAK_NOTE}.
            </Typography>
          ) : null}
          {showBreaks && unscheduledBreak > 0 ? (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.25 }}>
              Net hours include {hoursText(unscheduledBreak)} of breaks without a time.
            </Typography>
          ) : null}
        </SummaryCard>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75, px: 0.25 }}>
        {ROLE_HOURS_EXPLANATION}
      </Typography>
    </Box>
  );
}
