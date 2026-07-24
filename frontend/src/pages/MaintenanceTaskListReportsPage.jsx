import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  getMaintenanceTaskListDetail,
  getMaintenanceTaskListMeta,
  getMaintenanceTaskListReports,
} from "../api";
import {
  formatDateWeekdayShort,
  formatTimeEt,
  groupTasksByCategory,
  isCompletedStatus,
  statusLabel,
} from "../utils/maintenanceTaskListHelpers";

function StatusChip({ status }) {
  const color = isCompletedStatus(status)
    ? "success"
    : status === "in_progress"
      ? "warning"
      : "default";
  return <Chip size="small" color={color} label={statusLabel(status)} />;
}

export default function MaintenanceTaskListReportsPage() {
  const [searchParams] = useSearchParams();
  const [taskDate, setTaskDate] = useState(searchParams.get("task_date") || "");
  const [employeeId, setEmployeeId] = useState("");
  const [status, setStatus] = useState("");
  const [completed, setCompleted] = useState("");
  const [rows, setRows] = useState([]);
  const [dateDisplay, setDateDisplay] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [detailById, setDetailById] = useState({});
  const deepLinkListId = searchParams.get("list_id");

  useEffect(() => {
    (async () => {
      if (searchParams.get("task_date")) return;
      try {
        const meta = await getMaintenanceTaskListMeta();
        setTaskDate(meta.data?.today || "");
        setDateDisplay(meta.data?.today_display || "");
      } catch {
        /* ignore */
      }
    })();
  }, [searchParams]);

  const load = useCallback(async () => {
    if (!taskDate) return;
    setLoading(true);
    setError("");
    try {
      const res = await getMaintenanceTaskListReports({
        task_date: taskDate,
        ...(employeeId ? { employee_id: employeeId } : {}),
        ...(status ? { status } : {}),
        ...(completed ? { completed } : {}),
      });
      setRows(res.data?.rows || []);
      setDateDisplay(res.data?.task_date_display || dateDisplay);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load reports");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [taskDate, employeeId, status, completed, dateDisplay]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!deepLinkListId || !rows.length) return;
    const row = rows.find((r) => String(r.id) === String(deepLinkListId));
    if (!row?.id) return;
    const key = row.id;
    setExpandedId(key);
    if (detailById[row.id]) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getMaintenanceTaskListDetail(row.id);
        if (!cancelled) {
          setDetailById((prev) => ({ ...prev, [row.id]: res.data?.list || null }));
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
    // Intentional: expand once when deep-linked list appears in rows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkListId, rows]);

  const employees = useMemo(() => {
    const map = new Map();
    rows.forEach((r) => {
      if (r.employee_id != null) map.set(r.employee_id, r.employee_name);
    });
    return [...map.entries()].map(([id, name]) => ({ id, name }));
  }, [rows]);

  const onExpand = async (row, isExpanding) => {
    if (!isExpanding) {
      setExpandedId(null);
      return;
    }
    const key = row.id || `ns-${row.employee_id}`;
    setExpandedId(key);
    if (!row?.id) return;
    if (detailById[row.id]) return;
    try {
      const res = await getMaintenanceTaskListDetail(row.id);
      setDetailById((prev) => ({ ...prev, [row.id]: res.data?.list || null }));
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load detail");
    }
  };

  return (
    <Box sx={{ p: { xs: 1.5, md: 2 }, maxWidth: 960, mx: "auto", width: "100%", overflowX: "hidden" }}>
      <Typography variant="h5" fontWeight={800} sx={{ mb: 0.5 }}>
        Maintenance submissions
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {dateDisplay || "Review submitted daily checklists"}
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 2, flexWrap: "wrap" }}>
        <TextField
          type="date"
          label="Date"
          size="small"
          InputLabelProps={{ shrink: true }}
          value={taskDate}
          onChange={(e) => setTaskDate(e.target.value)}
          sx={{ minWidth: 160 }}
        />
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Employee</InputLabel>
          <Select label="Employee" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            {employees.map((e) => (
              <MenuItem key={e.id} value={String(e.id)}>
                {e.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Status</InputLabel>
          <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="completed">Submitted</MenuItem>
            <MenuItem value="in_progress">In Progress</MenuItem>
            <MenuItem value="not_started">Missing</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Completed</InputLabel>
          <Select label="Completed" value={completed} onChange={(e) => setCompleted(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="complete">Complete</MenuItem>
            <MenuItem value="incomplete">Incomplete</MenuItem>
          </Select>
        </FormControl>
        <Button variant="outlined" onClick={load} disabled={loading} sx={{ textTransform: "none" }}>
          Refresh
        </Button>
      </Stack>

      <Stack spacing={1}>
        {rows.map((row) => {
          const key = row.id || `ns-${row.employee_id}`;
          const detail = row.id ? detailById[row.id] : null;
          const groups = groupTasksByCategory(detail?.items || []);
          return (
            <Accordion
              key={key}
              expanded={expandedId === key}
              onChange={(_, exp) => onExpand(row, exp)}
              disableGutters
              sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, "&:before": { display: "none" } }}
            >
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  spacing={{ xs: 0.5, sm: 2 }}
                  alignItems={{ sm: "center" }}
                  sx={{ width: "100%", pr: 1 }}
                >
                  <Typography fontWeight={800} sx={{ minWidth: 140 }}>
                    {row.employee_name || "—"}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ minWidth: 130 }}>
                    {formatDateWeekdayShort(row.task_date)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ minWidth: 80 }}>
                    {isCompletedStatus(row.status) ? formatTimeEt(row.submitted_at) : "—"}
                  </Typography>
                  <StatusChip status={row.status} />
                </Stack>
              </AccordionSummary>
              <AccordionDetails>
                {!row.id ? (
                  <Typography color="text.secondary">No checklist started for this date.</Typography>
                ) : !detail ? (
                  <Typography color="text.secondary">Loading…</Typography>
                ) : (
                  <Stack spacing={1.25}>
                    {groups.map((group) => (
                      <Box key={group.category}>
                        <Typography
                          variant="caption"
                          fontWeight={800}
                          color="text.secondary"
                          sx={{ display: "block", mb: 0.5 }}
                        >
                          {group.category}
                        </Typography>
                        <Stack spacing={0.75}>
                          {group.items.map((item) => (
                            <Box
                              key={item.id}
                              sx={{ p: 1, borderRadius: 1.5, bgcolor: "action.hover" }}
                            >
                              <Typography fontWeight={700}>{item.task_name_snapshot}</Typography>
                              {item.task_description_snapshot ? (
                                <Typography variant="body2" color="text.secondary">
                                  {item.task_description_snapshot}
                                </Typography>
                              ) : null}
                              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.35 }}>
                                {item.completed ? "Completed" : "Incomplete"}
                                {item.completed && item.completed_at
                                  ? ` · ${formatTimeEt(item.completed_at)}`
                                  : ""}
                              </Typography>
                            </Box>
                          ))}
                        </Stack>
                      </Box>
                    ))}
                  </Stack>
                )}
              </AccordionDetails>
            </Accordion>
          );
        })}
        {!rows.length && !loading ? (
          <Typography color="text.secondary">No rows for this filter.</Typography>
        ) : null}
      </Stack>
    </Box>
  );
}
