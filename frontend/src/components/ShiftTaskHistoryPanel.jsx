import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { getTaskTrackingCategories, getTaskTrackingReports, getTaskTrackingRoles, getTaUsers } from "../api";
import { formatEasternTimeShort } from "../utils/datetimeFormat";
import { PayrollDateField } from "./PayrollDateTimeField";

function formatTaskDuration(sec) {
  const s = Math.max(0, Number(sec) || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0 && m > 0) return `${h} hr ${m} min`;
  if (h > 0) return `${h} hr`;
  return `${m} min`;
}

function formatShiftTotal(sec) {
  return formatTaskDuration(sec);
}

function formatTimeOnly(val) {
  if (!val) return "—";
  const s = String(val).trim().replace(" ", "T");
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return formatEasternTimeShort(val) || "—";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function ShiftTimeline({ timeline }) {
  const items = Array.isArray(timeline) ? timeline : [];
  if (!items.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        No timeline recorded for this shift.
      </Typography>
    );
  }

  return (
    <Stack spacing={1.25}>
      {items.map((item, idx) => {
        if (item.type === "check_in" || item.type === "check_out" || item.type === "force_check_out") {
          return (
            <Typography key={`${item.type}-${idx}`} variant="body2" fontWeight={600}>
              {formatTimeOnly(item.at)} — {item.label}
            </Typography>
          );
        }
        if (item.type === "task") {
          const start = formatTimeOnly(item.started_at);
          const end = item.ended_at ? formatTimeOnly(item.ended_at) : "now";
          return (
            <Box key={`task-${idx}`}>
              <Typography variant="body2" color="text.secondary">
                {start} – {end}
              </Typography>
              <Typography variant="body2" fontWeight={600}>
                {item.task_name || "Task"}
              </Typography>
            </Box>
          );
        }
        return null;
      })}
    </Stack>
  );
}

export default function ShiftTaskHistoryPanel() {
  const [fromDate, setFromDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  });
  const [toDate, setToDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [userId, setUserId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [roleId, setRoleId] = useState("");
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [categories, setCategories] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      getTaUsers(),
      getTaskTrackingCategories({ include_inactive: "1" }),
      getTaskTrackingRoles({ include_inactive: "1" }),
    ])
      .then(([uRes, cRes, rRes]) => {
        setUsers(uRes.data?.users || uRes.data?.items || uRes.data || []);
        setCategories(Array.isArray(cRes.data) ? cRes.data : []);
        setRoles(Array.isArray(rRes.data) ? rRes.data : []);
      })
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = { from_date: fromDate, to_date: toDate };
      if (userId) params.user_id = userId;
      if (categoryId) params.category_id = categoryId;
      if (roleId) params.role_id = roleId;
      const res = await getTaskTrackingReports(params);
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load shift history");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, userId, categoryId, roleId]);

  useEffect(() => {
    load();
  }, [load]);

  const userOptions = useMemo(
    () =>
      (Array.isArray(users) ? users : []).map((u) => ({
        id: u.id || u.user_id,
        label: [u.first_name, u.last_name].filter(Boolean).join(" ") || u.email || `#${u.id}`,
      })),
    [users],
  );

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Chronological category and role history for each shift — source of truth for the future performance dashboard.
      </Typography>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
        <PayrollDateField label="From" value={fromDate} onChange={setFromDate} />
        <PayrollDateField label="To" value={toDate} onChange={setToDate} />
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Employee</InputLabel>
          <Select label="Employee" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            {userOptions.map((u) => (
              <MenuItem key={u.id} value={String(u.id)}>
                {u.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Category</InputLabel>
          <Select label="Category" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            {categories.map((c) => (
              <MenuItem key={c.id} value={String(c.id)}>
                {c.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Role</InputLabel>
          <Select label="Role" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            {roles.map((r) => (
              <MenuItem key={r.id} value={String(r.id)}>
                {r.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

      <Stack spacing={2}>
        {loading ? (
          <Typography color="text.secondary">Loading…</Typography>
        ) : rows.length === 0 ? (
          <Typography color="text.secondary">No shifts in range.</Typography>
        ) : (
          rows.map((row) => {
            const name = [row.first_name, row.last_name].filter(Boolean).join(" ") || row.email;
            return (
              <Paper key={row.id} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                <Typography fontWeight={800}>{name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  Shift date: {row.shift_date || "—"}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Check-in: {formatEasternTimeShort(row.clock_in_at) || "—"}
                  {" · "}
                  Check-out: {formatEasternTimeShort(row.clock_out_at) || "—"}
                </Typography>
                <Typography variant="body2" sx={{ mt: 0.5, fontWeight: 600 }}>
                  Total shift time: {formatShiftTotal(row.total_shift_seconds)}
                </Typography>

                <Divider sx={{ my: 1.5 }} />
                <Typography variant="overline" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  Shift timeline
                </Typography>
                <ShiftTimeline timeline={row.shift_timeline} />

                {(row.task_breakdown || []).length > 0 ? (
                  <>
                    <Divider sx={{ my: 1.5 }} />
                    <Typography variant="overline" color="text.secondary" display="block" sx={{ mb: 1 }}>
                      Time by task
                    </Typography>
                    <Stack spacing={0.5}>
                      {                    row.task_breakdown.map((t) => (
                      <Typography key={`${t.category_id}-${t.role_id}`} variant="body2">
                        {t.display_label || t.task_name} — {formatTaskDuration(t.duration_seconds)}
                      </Typography>
                    ))}
                    </Stack>
                  </>
                ) : null}
              </Paper>
            );
          })
        )}
      </Stack>
    </Box>
  );
}
