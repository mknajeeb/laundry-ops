import { useMemo, useState } from "react";
import {
  Chip,
  Link,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { formatCount, formatDateTime, formatFoldingDuration, formatLbs } from "../../utils/foldingFormat";
import { formatExceptionList, lifecycleStatusLabel } from "../../utils/shiftAnalysisLabels";

function fmtRate(v) {
  if (v == null) return "—";
  return Number(v).toFixed(2);
}

export default function ShiftStaffPerformanceSection({
  staffPerformance,
  lifecycleStatusLabels,
  onTaskDrill,
  onEmployeeDrill,
  onRecordDrill,
}) {
  const [view, setView] = useState("processing");
  const [detailTab, setDetailTab] = useState("all");
  const [selected, setSelected] = useState(null);

  const tasks = staffPerformance?.tasks || [];
  const employees = staffPerformance?.employees || [];
  const records = staffPerformance?.records || [];

  const filteredRecords = useMemo(() => {
    if (!selected) return [];
    let rows = records.filter(
      (r) => r.employee_name === selected.employee_name && (!selected.task || r.task === selected.task)
    );
    if (detailTab === "scoring") rows = rows.filter((r) => r.in_scoring);
    else if (detailTab === "not_scoring") rows = rows.filter((r) => r.in_scoring === false);
    else if (detailTab === "review") rows = rows.filter((r) => r.needs_review || (r.exception_flags || []).length);
    return rows;
  }, [records, selected, detailTab]);

  const displayTasks = view === "folding"
    ? tasks.filter((t) => t.task === "folding")
    : view === "combined"
      ? tasks
      : tasks.filter((t) => t.task !== "folding");

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }} gap={1}>
        <Typography variant="subtitle1" fontWeight={700}>Staff performance</Typography>
        <ToggleButtonGroup size="small" value={view} exclusive onChange={(_, v) => v && setView(v)}>
          <ToggleButton value="processing">Processing</ToggleButton>
          <ToggleButton value="folding">Folding</ToggleButton>
          <ToggleButton value="combined">Combined</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      <Paper variant="outlined" sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Employee</TableCell>
              <TableCell>Task</TableCell>
              <TableCell align="right">Bags</TableCell>
              <TableCell align="right">Lbs</TableCell>
              <TableCell align="right">Avg / bag</TableCell>
              <TableCell align="right">Bags/hr</TableCell>
              <TableCell align="right">Shift avg</TableCell>
              <TableCell align="right">vs avg</TableCell>
              <TableCell align="right">Rank</TableCell>
              <TableCell>Label</TableCell>
              <TableCell align="right">Scoring</TableCell>
              <TableCell align="right">Excluded</TableCell>
              <TableCell align="right">Review</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {displayTasks.map((t) => (
              <TableRow
                key={`${t.employee_name}-${t.task}`}
                hover
                selected={selected?.employee_name === t.employee_name && selected?.task === t.task}
                sx={{ cursor: "pointer" }}
                onClick={() => {
                  setSelected({ employee_name: t.employee_name, task: t.task });
                  onTaskDrill?.(t);
                }}
              >
                <TableCell>
                  <Link component="button" variant="body2" onClick={(e) => { e.stopPropagation(); onEmployeeDrill?.(t); }}>
                    {t.employee_name}
                  </Link>
                </TableCell>
                <TableCell>{t.task_label || t.task}</TableCell>
                <TableCell align="right">{formatCount(t.bag_count)}</TableCell>
                <TableCell align="right">{formatLbs(t.lbs)}</TableCell>
                <TableCell align="right">{formatFoldingDuration(t.avg_seconds_per_bag)}</TableCell>
                <TableCell align="right">{fmtRate(t.bags_per_hour)}</TableCell>
                <TableCell align="right">{formatFoldingDuration(t.shift_avg_seconds_per_bag)}</TableCell>
                <TableCell align="right">
                  {t.difference_percent != null ? `${t.difference_percent > 0 ? "+" : ""}${t.difference_percent}%` : "—"}
                </TableCell>
                <TableCell align="right">{t.rank ?? "—"}</TableCell>
                <TableCell>
                  {t.performance_label ? (
                    <Chip size="small" label={t.performance_label} variant="outlined" />
                  ) : "—"}
                </TableCell>
                <TableCell align="right">{formatCount(t.scoring_bags)}</TableCell>
                <TableCell align="right">{formatCount(t.not_scoring_bags)}</TableCell>
                <TableCell align="right">{formatCount(t.needs_review_count)}</TableCell>
              </TableRow>
            ))}
            {!displayTasks.length ? (
              <TableRow><TableCell colSpan={13} align="center">No staff task data for active bags</TableCell></TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Paper>

      {selected ? (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle2" fontWeight={700} gutterBottom>
            {selected.employee_name} — {selected.task}
          </Typography>
          <Tabs value={detailTab} onChange={(_, v) => setDetailTab(v)} sx={{ mb: 1, minHeight: 36 }}>
            <Tab value="all" label="All records" sx={{ minHeight: 36 }} />
            <Tab value="scoring" label="Scoring" sx={{ minHeight: 36 }} />
            <Tab value="not_scoring" label="Not scoring" sx={{ minHeight: 36 }} />
            <Tab value="review" label="Exceptions / Review" sx={{ minHeight: 36 }} />
          </Tabs>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Bag</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell>Rush</TableCell>
                <TableCell>Lifecycle</TableCell>
                <TableCell>Start</TableCell>
                <TableCell>End</TableCell>
                <TableCell>Duration</TableCell>
                <TableCell>Weight</TableCell>
                <TableCell>Scoring</TableCell>
                <TableCell>Reason</TableCell>
                <TableCell>Exceptions</TableCell>
                <TableCell align="right">Timeline</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredRecords.map((r) => (
                <TableRow key={`${r.bag_id}-${r.task}`} hover>
                  <TableCell>{r.bag_id}</TableCell>
                  <TableCell>{r.customer || "—"}</TableCell>
                  <TableCell>{r.rush_label || "—"}</TableCell>
                  <TableCell>{lifecycleStatusLabel(r.lifecycle_status, lifecycleStatusLabels)}</TableCell>
                  <TableCell>{formatDateTime(r.start_time)}</TableCell>
                  <TableCell>{formatDateTime(r.end_time)}</TableCell>
                  <TableCell>{formatFoldingDuration(r.duration_seconds)}</TableCell>
                  <TableCell>{formatLbs(r.weight_lbs)}</TableCell>
                  <TableCell>{r.in_scoring == null ? "—" : r.in_scoring ? "Yes" : "No"}</TableCell>
                  <TableCell>{r.reason_not_scoring || "—"}</TableCell>
                  <TableCell>{formatExceptionList(r.exception_flags)}</TableCell>
                  <TableCell align="right">
                    <Link component="button" variant="body2" onClick={() => onRecordDrill?.(r)}>Open</Link>
                  </TableCell>
                </TableRow>
              ))}
              {!filteredRecords.length ? (
                <TableRow><TableCell colSpan={12} align="center">No records for this filter</TableCell></TableRow>
              ) : null}
            </TableBody>
          </Table>
        </Paper>
      ) : null}

      {employees.length ? (
        <Typography variant="caption" color="text.secondary">
          {employees.length} employee(s) with task activity on active portal bags.
        </Typography>
      ) : null}
    </Stack>
  );
}
