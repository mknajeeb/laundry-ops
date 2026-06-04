import { useMemo, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  Collapse,
  IconButton,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { SCHEDULE_THEME } from "../payroll/scheduleTheme";

function money(n) {
  return `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function ForecastMetric({ label, value, highlight }) {
  return (
    <Box
      sx={{
        flex: "1 1 100px",
        minWidth: 88,
        px: 1.25,
        py: 1,
        borderRadius: 2,
        bgcolor: highlight ? "warning.50" : SCHEDULE_THEME.accentSoft,
        border: "1px solid",
        borderColor: highlight ? "warning.light" : "transparent",
      }}
    >
      <Typography variant="caption" color="text.secondary" display="block">
        {label}
      </Typography>
      <Typography variant="subtitle1" fontWeight={800}>
        {value}
      </Typography>
    </Box>
  );
}

export default function PayrollFundingForecastPanel({ forecast, compact }) {
  const [expanded, setExpanded] = useState(!compact);
  const [showWorkers, setShowWorkers] = useState(false);

  const f = forecast;
  const cat = f?.category_breakdown || {};

  const topWorkers = useMemo(
    () => (f?.worker_breakdown || []).slice(0, compact ? 3 : 10),
    [f, compact],
  );

  if (!f) return null;

  return (
    <Card sx={{ ...SCHEDULE_THEME.card, mb: 2 }}>
      <CardContent sx={{ pb: expanded ? 2 : 1.5 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Estimated · not final payroll
            </Typography>
            <Typography variant="h6" fontWeight={800}>
              {f.card_title || "Payroll funding forecast"}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Work week {f.work_week_start} – {f.work_week_end}
              {f.payment_date ? ` · Pay ${f.payment_date}` : ""}
            </Typography>
          </Box>
          <IconButton size="small" onClick={() => setExpanded((v) => !v)} aria-label="Toggle forecast">
            {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </IconButton>
        </Stack>

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: expanded ? 2 : 0 }}>
          <ForecastMetric label="Total projected" value={money(f.total_projected_cost)} highlight />
          <ForecastMetric label="W-2" value={money(cat.w2?.cost)} />
          <ForecastMetric label="1099" value={money(cat.contractor_1099?.cost)} />
          <ForecastMetric label="Temp" value={money(cat.temp?.cost)} />
          <ForecastMetric label="Hours" value={Number(f.total_scheduled_hours || 0).toFixed(0)} />
          <ForecastMetric
            label="OT risk"
            value={f.overtime_risk_count ?? 0}
            highlight={(f.overtime_risk_count || 0) > 0}
          />
          <ForecastMetric label="Draft" value={money(f.draft_cost)} />
          <ForecastMetric label="Published" value={money(f.published_cost)} />
        </Stack>

        <Collapse in={expanded}>
          {(f.overtime_risk_count || 0) > 0 ? (
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1.5 }}>
              <WarningAmberIcon color="warning" fontSize="small" />
              <Typography variant="body2" color="warning.main">
                {f.overtime_risk_count} worker(s) projected over OT threshold ·{" "}
                {Number(f.projected_overtime_hours || 0).toFixed(1)} OT hours
              </Typography>
            </Stack>
          ) : null}

          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
            Daily breakdown
          </Typography>
          <Box className="table-wrapper" sx={{ mb: 2 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Day</TableCell>
                  <TableCell align="right">People</TableCell>
                  <TableCell align="right">Hours</TableCell>
                  <TableCell align="right">Est. cost</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(f.daily_breakdown || []).map((row) => (
                  <TableRow key={row.day}>
                    <TableCell>
                      {row.day}
                      <Typography variant="caption" color="text.secondary" display="block">
                        {row.date?.slice(5)}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">{row.people_count}</TableCell>
                    <TableCell align="right">{Number(row.hours || 0).toFixed(1)}</TableCell>
                    <TableCell align="right">{money(row.cost)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>

          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
            {[
              ["By shift", f.shift_breakdown],
              ["By stream", f.stream_breakdown],
              ["By role", f.role_breakdown],
            ].map(([title, rows]) => (
              <Box key={title} sx={{ flex: 1 }}>
                <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
                  {title}
                </Typography>
                {(rows || []).slice(0, 5).map((r) => (
                  <Stack key={r.name} direction="row" justifyContent="space-between" sx={{ py: 0.25 }}>
                    <Typography variant="body2">{r.name}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {money(r.cost)}
                    </Typography>
                  </Stack>
                ))}
              </Box>
            ))}
          </Stack>

          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2" fontWeight={700}>
              Worker breakdown
            </Typography>
            <IconButton size="small" onClick={() => setShowWorkers((v) => !v)}>
              {showWorkers ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
          </Stack>
          <Collapse in={showWorkers}>
            <Stack spacing={1}>
              {topWorkers.map((w) => (
                <Box
                  key={w.worker_profile_id}
                  sx={{ p: 1.25, borderRadius: 2, bgcolor: "action.hover" }}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography fontWeight={700}>{w.worker_name}</Typography>
                    <Typography fontWeight={700}>{money(w.projected_cost)}</Typography>
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    {w.worker_category_label} · {Number(w.scheduled_hours || 0).toFixed(1)}h · $
                    {Number(w.hourly_rate || 0).toFixed(2)}/hr
                  </Typography>
                  <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }} flexWrap="wrap" useFlexGap>
                    <Chip size="small" label={w.balance_label} color={w.overtime_risk ? "warning" : "default"} />
                    {(w.role_tags || []).map((t) => (
                      <Chip key={t} size="small" variant="outlined" label={t} />
                    ))}
                  </Stack>
                </Box>
              ))}
            </Stack>
          </Collapse>

          {(f.sick_hours || 0) > 0 ? (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              Sick shifts excluded from total: {Number(f.sick_hours).toFixed(1)}h ({money(f.sick_cost)})
            </Typography>
          ) : null}
        </Collapse>
      </CardContent>
    </Card>
  );
}
