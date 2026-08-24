import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import {
  getManagementRinseHdPerformance,
  getManagementRinseHdPerformanceEmployee,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const SORT_OPTIONS = [
  { id: "output", label: "Most output" },
  { id: "wash", label: "Most washes" },
  { id: "fold", label: "Most folds" },
  { id: "name", label: "Name" },
];

function fmtTime(v) {
  if (!v) return "—";
  return formatFriendlyEtWall(v) || String(v);
}

function KpiCard({ label, value }) {
  return (
    <Box
      sx={{
        px: 1,
        py: 0.85,
        borderRadius: 1.5,
        border: "1px solid #e5e7eb",
        bgcolor: "#fff",
        minWidth: 0,
      }}
    >
      <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1.05 }}>{value}</Typography>
      <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
        {label}
      </Typography>
    </Box>
  );
}

function HdEmployeeDetailDrawer({ open, onClose, employee, dateEt }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || !employee?.user_id) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setDetail(null);
    (async () => {
      try {
        const res = await getManagementRinseHdPerformanceEmployee(employee.user_id, dateEt);
        if (!cancelled) setDetail(res.data?.employee || null);
      } catch (err) {
        if (!cancelled) {
          setError(err?.response?.data?.error || err?.message || "Unable to load employee detail");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, employee?.user_id, dateEt]);

  const emp = detail || employee;

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ fontWeight: 800, pb: 1 }}>
        {emp?.display_name || "Employee"}
        <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
          Wash {emp?.wash_count ?? 0} · Fold {emp?.fold_count ?? 0}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {loading ? (
          <Box sx={{ py: 3, textAlign: "center" }}>
            <CircularProgress size={22} />
          </Box>
        ) : null}
        {error ? <Alert severity="error">{error}</Alert> : null}
        {!loading && !error ? (
          <Stack spacing={1.5}>
            <Box>
              <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#64748b", mb: 0.5 }}>
                Wash
              </Typography>
              {(emp?.wash_bags || []).length === 0 ? (
                <Typography sx={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>No wash credit</Typography>
              ) : (
                (emp?.wash_bags || []).map((row) => (
                  <Typography key={`w-${row.bag_id}`} sx={{ fontSize: 13, fontWeight: 600, color: "#334155" }}>
                    {row.bag_id} · {row.customer_name || "Customer unavailable"} · {fmtTime(row.washed_at)}
                  </Typography>
                ))
              )}
            </Box>
            <Box>
              <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#64748b", mb: 0.5 }}>
                Fold
              </Typography>
              {(emp?.fold_bags || []).length === 0 ? (
                <Typography sx={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>No fold credit</Typography>
              ) : (
                (emp?.fold_bags || []).map((row) => (
                  <Typography key={`f-${row.bag_id}`} sx={{ fontSize: 13, fontWeight: 600, color: "#334155" }}>
                    {row.bag_id} · {row.customer_name || "Customer unavailable"} · {fmtTime(row.folded_at)}
                  </Typography>
                ))
              )}
            </Box>
          </Stack>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export default function ManagementHdPerformanceSection({ dateEt }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sortBy, setSortBy] = useState("output");
  const [detailEmployee, setDetailEmployee] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRinseHdPerformance(dateEt, { summary: 1 });
      setData(res.data || null);
    } catch (err) {
      setData(null);
      setError(err?.response?.data?.error || err?.message || "Unable to load HD performance");
    } finally {
      setLoading(false);
    }
  }, [dateEt]);

  useEffect(() => {
    load();
  }, [load]);

  const employees = useMemo(() => {
    const rows = [...(data?.employees || [])];
    if (sortBy === "wash") {
      rows.sort((a, b) => (b.wash_count || 0) - (a.wash_count || 0) || String(a.display_name).localeCompare(String(b.display_name)));
    } else if (sortBy === "fold") {
      rows.sort((a, b) => (b.fold_count || 0) - (a.fold_count || 0) || String(a.display_name).localeCompare(String(b.display_name)));
    } else if (sortBy === "name") {
      rows.sort((a, b) => String(a.display_name || "").localeCompare(String(b.display_name || "")));
    } else {
      rows.sort(
        (a, b) =>
          (b.wash_count || 0) + (b.fold_count || 0) - ((a.wash_count || 0) + (a.fold_count || 0))
          || String(a.display_name || "").localeCompare(String(b.display_name || "")),
      );
    }
    return rows;
  }, [data?.employees, sortBy]);

  const summary = data?.summary || {};

  return (
    <Box sx={{ minWidth: 0 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Box>
          <Typography sx={{ fontSize: 18, fontWeight: 800 }}>Rinse HD</Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            Wash/fold credit by operation timestamp (ET)
          </Typography>
        </Box>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel id="hd-sort-label">Sort</InputLabel>
          <Select
            labelId="hd-sort-label"
            label="Sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
          >
            {SORT_OPTIONS.map((opt) => (
              <MenuItem key={opt.id} value={opt.id}>
                {opt.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 0.75,
          mb: 1.25,
        }}
      >
        <KpiCard label="Bags Washed" value={summary.bags_washed ?? 0} />
        <KpiCard label="Bags Folded" value={summary.bags_folded ?? 0} />
        <KpiCard label="Wash Employees" value={summary.wash_employees ?? 0} />
        <KpiCard label="Fold Employees" value={summary.fold_employees ?? 0} />
      </Box>

      {error ? (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <Box sx={{ py: 2, textAlign: "center" }}>
          <CircularProgress size={20} />
        </Box>
      ) : employees.length === 0 ? (
        <Typography sx={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>
          No HD wash/fold attribution for this day.
        </Typography>
      ) : (
        <Box sx={{ border: "1px solid #e5e7eb", borderRadius: 2, overflow: "hidden", bgcolor: "#fff" }}>
          <Box
            sx={{
              display: { xs: "none", md: "grid" },
              gridTemplateColumns: "1.4fr 0.7fr 0.7fr 0.9fr 0.8fr",
              gap: 1,
              px: 1.25,
              py: 0.75,
              bgcolor: "#f8fafc",
              borderBottom: "1px solid #e5e7eb",
            }}
          >
            {["Employee", "Wash", "Fold", "First/Last Wash", "Actions"].map((h) => (
              <Typography key={h} sx={{ fontSize: 11, fontWeight: 800, color: "#64748b", textTransform: "uppercase" }}>
                {h}
              </Typography>
            ))}
          </Box>
          {employees.map((emp) => (
            <Box
              key={emp.user_id}
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr", md: "1.4fr 0.7fr 0.7fr 0.9fr 0.8fr" },
                gap: 1,
                px: 1.25,
                py: 1,
                borderBottom: "1px solid #f1f5f9",
                alignItems: "center",
              }}
            >
              <Typography sx={{ fontWeight: 800, fontSize: 15 }}>{emp.display_name}</Typography>
              <Typography sx={{ fontWeight: 700, fontSize: 14, color: VEEWASH_DASHBOARD.hdTeal }}>
                Wash {emp.wash_count ?? 0}
              </Typography>
              <Typography sx={{ fontWeight: 700, fontSize: 14, color: VEEWASH_DASHBOARD.hdTeal }}>
                Fold {emp.fold_count ?? 0}
              </Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                {emp.first_wash_at ? fmtTime(emp.first_wash_at) : "—"}
                {emp.last_wash_at && emp.last_wash_at !== emp.first_wash_at
                  ? ` → ${fmtTime(emp.last_wash_at)}`
                  : ""}
              </Typography>
              <Button
                size="small"
                variant="outlined"
                onClick={() => setDetailEmployee(emp)}
                sx={{ justifySelf: { md: "start" }, textTransform: "none", fontWeight: 700 }}
              >
                View Orders
              </Button>
            </Box>
          ))}
        </Box>
      )}

      <HdEmployeeDetailDrawer
        open={Boolean(detailEmployee)}
        onClose={() => setDetailEmployee(null)}
        employee={detailEmployee}
        dateEt={dateEt}
      />
    </Box>
  );
}
