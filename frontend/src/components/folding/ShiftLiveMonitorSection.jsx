import {
  Chip,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { formatCount } from "../../utils/foldingFormat";

const SEV_COLOR = {
  critical: "#dc2626",
  warning: "#d97706",
  info: "#0284c7",
};

function fmtSec(sec) {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function ShiftLiveMonitorSection({ liveMonitor, onAlertDrill, onStepDrill }) {
  const alerts = liveMonitor?.alerts || [];
  const steps = liveMonitor?.step_metrics || [];

  return (
    <Stack spacing={2}>
      <Typography variant="subtitle1" fontWeight={700}>Needs Attention Now</Typography>
      {!alerts.length ? (
        <Typography variant="body2" color="text.secondary">No active alerts for the current evaluation window.</Typography>
      ) : (
        <Stack spacing={1}>
          {alerts.map((a) => (
            <Paper
              key={a.type}
              variant="outlined"
              sx={{
                p: 1.25,
                borderLeft: `4px solid ${SEV_COLOR[a.severity] || "#64748b"}`,
                cursor: a.record_count > 0 ? "pointer" : "default",
                "&:hover": a.record_count > 0 ? { bgcolor: "grey.50" } : undefined,
              }}
              onClick={() => a.record_count > 0 && onAlertDrill?.(a)}
            >
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Chip size="small" label={a.severity} sx={{ textTransform: "capitalize", fontWeight: 600 }} color={a.severity === "critical" ? "error" : a.severity === "warning" ? "warning" : "info"} />
                <Typography variant="body2" fontWeight={600}>{a.label}</Typography>
                {a.avg_delay_minutes != null ? (
                  <Typography variant="caption" color="text.secondary">Avg delay {a.avg_delay_minutes} min</Typography>
                ) : null}
                {a.longest_delay_minutes != null ? (
                  <Typography variant="caption" color="text.secondary">Longest {a.longest_delay_minutes} min</Typography>
                ) : null}
              </Stack>
            </Paper>
          ))}
        </Stack>
      )}

      <Typography variant="subtitle1" fontWeight={700} sx={{ mt: 1 }}>Step averages</Typography>
      <Paper variant="outlined" sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Step</TableCell>
              <TableCell align="right">Avg</TableCell>
              <TableCell align="right">Median</TableCell>
              <TableCell align="right">Longest</TableCell>
              <TableCell align="right">Bags</TableCell>
              <TableCell align="right">Over limit</TableCell>
              <TableCell align="right">Drilldown</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {steps.map((s) => (
              <TableRow key={s.step} hover>
                <TableCell>{s.label}</TableCell>
                <TableCell align="right">{fmtSec(s.avg_seconds)}</TableCell>
                <TableCell align="right">{fmtSec(s.median_seconds)}</TableCell>
                <TableCell align="right">{fmtSec(s.longest_seconds)}</TableCell>
                <TableCell align="right">{formatCount(s.bag_count)}</TableCell>
                <TableCell align="right">
                  {s.over_limit_count > 0 ? (
                    <Link component="button" variant="body2" onClick={() => onStepDrill?.(s)}>
                      {s.over_limit_count}
                    </Link>
                  ) : (
                    s.over_limit_count ?? 0
                  )}
                </TableCell>
                <TableCell align="right">
                  {s.bag_count > 0 ? (
                    <Link component="button" variant="body2" onClick={() => onStepDrill?.(s)}>View</Link>
                  ) : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}
