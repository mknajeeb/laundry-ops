import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import {
  getManagementRinseHdPerformance,
  getManagementRinseHdPerformanceEmployee,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import PerformanceDetailDrawer, {
  PerformanceSortSelect,
} from "./performance/PerformanceDetailDrawer";
import { fmtCount } from "./performance/performanceFormat";

const HD_SORT_OPTIONS = [
  { value: "output", label: "Most output" },
  { value: "wash", label: "Most wash" },
  { value: "fold", label: "Most fold" },
  { value: "name", label: "Name A–Z" },
];

function fmtTimeShort(v) {
  if (!v) return null;
  const full = formatFriendlyEtWall(v) || String(v);
  const m = full.match(/(\d{1,2}:\d{2}\s*[AP]M)/i);
  return m ? m[1] : full;
}

function hdActivityRange(emp) {
  const parts = [];
  if (emp.first_wash_at) {
    const start = fmtTimeShort(emp.first_wash_at);
    const end = fmtTimeShort(emp.last_wash_at || emp.first_wash_at);
    if (start && end && start !== end) parts.push(`${start} – ${end}`);
    else if (start) parts.push(start);
  }
  if (emp.first_fold_at && (emp.fold_count || 0) > 0) {
    const start = fmtTimeShort(emp.first_fold_at);
    const end = fmtTimeShort(emp.last_fold_at || emp.first_fold_at);
    if (start && end && start !== end && !parts.length) parts.push(`${start} – ${end}`);
    else if (start && !parts.length) parts.push(start);
  }
  return parts[0] || null;
}

function OpBadge({ kind, count }) {
  const isWash = kind === "wash";
  return (
    <Box
      sx={{
        display: "inline-flex",
        alignItems: "center",
        gap: 0.35,
        px: 0.75,
        py: 0.25,
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 800,
        letterSpacing: 0.2,
        bgcolor: isWash ? "#dff5f1" : "#e8f3f6",
        color: isWash ? VEEWASH_DASHBOARD.hdTeal : VEEWASH_DASHBOARD.primaryBlueDark,
      }}
    >
      {isWash ? "Wash" : "Fold"} {count ?? 0}
    </Box>
  );
}

function HdEmployeeCard({ employee, onViewOrders }) {
  const timeRange = hdActivityRange(employee);
  const hasOrders = (employee.wash_count || 0) + (employee.fold_count || 0) > 0;

  return (
    <Box
      sx={{
        px: { xs: 1.25, sm: 1.5 },
        py: { xs: 1.15, sm: 1.35 },
        borderRadius: 2.5,
        bgcolor: "#fff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Typography
        sx={{
          fontSize: { xs: 16, sm: 17 },
          fontWeight: 800,
          lineHeight: 1.2,
          color: "#0f172a",
        }}
        noWrap
      >
        {employee.display_name}
      </Typography>

      <Stack direction="row" spacing={0.75} sx={{ mt: 0.65, flexWrap: "wrap" }}>
        <OpBadge kind="wash" count={employee.wash_count ?? 0} />
        <OpBadge kind="fold" count={employee.fold_count ?? 0} />
      </Stack>

      {timeRange ? (
        <Typography sx={{ mt: 0.65, fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>
          {timeRange}
        </Typography>
      ) : null}

      {hasOrders ? (
        <Box
          component="button"
          type="button"
          onClick={() => onViewOrders(employee)}
          sx={{
            display: "inline-flex",
            alignItems: "center",
            gap: 0.15,
            mt: 0.85,
            m: 0,
            p: 0,
            border: "none",
            bgcolor: "transparent",
            cursor: "pointer",
            fontFamily: "inherit",
            color: VEEWASH_DASHBOARD.hdTeal,
            fontWeight: 800,
            fontSize: 13,
            WebkitTapHighlightColor: "transparent",
            "&:hover": { textDecoration: "underline" },
          }}
        >
          View orders
          <ChevronRightIcon sx={{ fontSize: 16 }} />
        </Box>
      ) : null}
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
    <PerformanceDetailDrawer
      open={open}
      onClose={onClose}
      title={emp?.display_name || "Employee"}
      subtitle={`Wash ${emp?.wash_count ?? 0} · Fold ${emp?.fold_count ?? 0}`}
    >
      {loading ? (
        <Box sx={{ py: 4, textAlign: "center" }}>
          <CircularProgress size={22} sx={{ color: VEEWASH_DASHBOARD.hdTeal }} />
        </Box>
      ) : null}
      {error ? <Alert severity="error">{error}</Alert> : null}
      {!loading && !error ? (
        <Stack spacing={1.75}>
          <Box>
            <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#94a3b8", letterSpacing: 0.6, mb: 0.75 }}>
              WASH
            </Typography>
            {(emp?.wash_bags || []).length === 0 ? (
              <Typography sx={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>No wash credit</Typography>
            ) : (
              (emp?.wash_bags || []).map((row) => (
                <Box key={`w-${row.bag_id}`} sx={{ py: 1, borderBottom: "1px solid #f1f5f9" }}>
                  <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
                    {row.customer_name || "Customer unavailable"}
                  </Typography>
                  <Typography sx={{ mt: 0.15, fontSize: 13, color: "#475569", fontWeight: 600 }}>
                    {row.bag_id}
                  </Typography>
                  <Typography sx={{ mt: 0.1, fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>
                    Wash · {fmtTimeShort(row.washed_at) || "—"}
                  </Typography>
                </Box>
              ))
            )}
          </Box>
          <Box>
            <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#94a3b8", letterSpacing: 0.6, mb: 0.75 }}>
              FOLD
            </Typography>
            {(emp?.fold_bags || []).length === 0 ? (
              <Typography sx={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>No fold credit</Typography>
            ) : (
              (emp?.fold_bags || []).map((row) => (
                <Box key={`f-${row.bag_id}`} sx={{ py: 1, borderBottom: "1px solid #f1f5f9" }}>
                  <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
                    {row.customer_name || "Customer unavailable"}
                  </Typography>
                  <Typography sx={{ mt: 0.15, fontSize: 13, color: "#475569", fontWeight: 600 }}>
                    {row.bag_id}
                  </Typography>
                  <Typography sx={{ mt: 0.1, fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>
                    Fold · {fmtTimeShort(row.folded_at) || "—"}
                  </Typography>
                </Box>
              ))
            )}
          </Box>
        </Stack>
      ) : null}
    </PerformanceDetailDrawer>
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
      rows.sort(
        (a, b) =>
          (b.wash_count || 0) - (a.wash_count || 0)
          || String(a.display_name).localeCompare(String(b.display_name)),
      );
    } else if (sortBy === "fold") {
      rows.sort(
        (a, b) =>
          (b.fold_count || 0) - (a.fold_count || 0)
          || String(a.display_name).localeCompare(String(b.display_name)),
      );
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

  const kpiLine = (
    <>
      <Typography component="span" sx={{ fontWeight: 700, color: "#334155" }}>
        {fmtCount(summary.bags_washed)} Washed
      </Typography>
      <Typography component="span" sx={{ mx: 0.75, color: "#cbd5e1" }}>
        ·
      </Typography>
      <Typography component="span" sx={{ fontWeight: 700, color: "#334155" }}>
        {fmtCount(summary.bags_folded)} Folded
      </Typography>
      <Typography component="span" sx={{ mx: 0.75, color: "#cbd5e1" }}>
        ·
      </Typography>
      <Typography component="span" sx={{ fontWeight: 700, color: "#334155" }}>
        {fmtCount(summary.wash_employees)} Washers
      </Typography>
      <Typography component="span" sx={{ mx: 0.75, color: "#cbd5e1" }}>
        ·
      </Typography>
      <Typography component="span" sx={{ fontWeight: 700, color: "#334155" }}>
        {fmtCount(summary.fold_employees)} Folders
      </Typography>
    </>
  );

  return (
    <Box sx={{ minWidth: 0, maxWidth: { md: 720 }, mx: { md: "auto" } }}>
      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1.25 }}>
        <PerformanceSortSelect
          value={sortBy}
          options={HD_SORT_OPTIONS}
          onChange={setSortBy}
          aria-label="Sort employees"
        />
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.25 }}>
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Box sx={{ py: 5, textAlign: "center" }}>
          <CircularProgress size={28} sx={{ color: VEEWASH_DASHBOARD.hdTeal }} />
        </Box>
      ) : (
        <>
          <Box
            sx={{
              mb: 1.5,
              px: { xs: 1.25, sm: 1.5 },
              py: { xs: 1, sm: 1.15 },
              borderRadius: 2.5,
              bgcolor: "#fff",
              boxShadow: VEEWASH_DASHBOARD.cardShadow,
              fontSize: { xs: 13, sm: 14 },
              lineHeight: 1.5,
            }}
          >
            {kpiLine}
          </Box>

          {employees.length === 0 ? (
            <Typography sx={{ py: 2, fontSize: 14, color: "#94a3b8", fontWeight: 600, textAlign: "center" }}>
              No Hang Dry wash/fold credit for this day.
            </Typography>
          ) : (
            <Stack spacing={1}>
              {employees.map((emp) => (
                <HdEmployeeCard
                  key={emp.user_id}
                  employee={emp}
                  onViewOrders={setDetailEmployee}
                />
              ))}
            </Stack>
          )}
        </>
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
