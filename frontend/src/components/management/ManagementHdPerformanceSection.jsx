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
import PerformanceDetailDrawer, {
  PerformanceSortSelect,
} from "./performance/PerformanceDetailDrawer";
import { fmtCount } from "./performance/performanceFormat";
import { PERF_TYPE, PERF_UI, PerfSeparator, perfKpiStripSx, perfRowSx } from "./performance/performanceTokens";

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
  if (emp.first_wash_at) {
    const start = fmtTimeShort(emp.first_wash_at);
    const end = fmtTimeShort(emp.last_wash_at || emp.first_wash_at);
    if (start && end && start !== end) return `${start} – ${end}`;
    if (start) return start;
  }
  if (emp.first_fold_at && (emp.fold_count || 0) > 0) {
    const start = fmtTimeShort(emp.first_fold_at);
    const end = fmtTimeShort(emp.last_fold_at || emp.first_fold_at);
    if (start && end && start !== end) return `${start} – ${end}`;
    if (start) return start;
  }
  return null;
}

function OpBadge({ kind, count }) {
  const isWash = kind === "wash";
  return (
    <Box
      component="span"
      sx={{
        display: "inline-flex",
        alignItems: "center",
        px: 0.55,
        py: 0.1,
        borderRadius: 999,
        fontSize: 10.5,
        fontWeight: 400,
        bgcolor: isWash ? "rgba(0, 168, 150, 0.12)" : "rgba(0, 151, 178, 0.1)",
        color: isWash ? PERF_UI.hdTeal : PERF_UI.tealDark,
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
    <Box sx={perfRowSx()}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        alignItems={{ xs: "flex-start", md: "center" }}
        spacing={{ xs: 0.25, md: 0.5 }}
        useFlexGap
        flexWrap="wrap"
      >
        <Typography sx={{ ...PERF_TYPE.name, minWidth: 0 }} noWrap>
          {employee.display_name}
        </Typography>
        <Stack direction="row" spacing={0.5} sx={{ flexShrink: 0 }}>
          <OpBadge kind="wash" count={employee.wash_count ?? 0} />
          <OpBadge kind="fold" count={employee.fold_count ?? 0} />
        </Stack>
        {timeRange ? (
          <Typography component="span" sx={{ ...PERF_TYPE.meta, display: { xs: "block", md: "inline" } }}>
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
              gap: 0.1,
              m: 0,
              p: 0,
              border: "none",
              bgcolor: "transparent",
              cursor: "pointer",
              fontFamily: "inherit",
              ...PERF_TYPE.link,
              color: PERF_UI.hdTeal,
              minHeight: { xs: 36, md: 28 },
              ml: { md: "auto" },
              WebkitTapHighlightColor: "transparent",
              "&:hover": { textDecoration: "underline" },
            }}
          >
            View orders
            <ChevronRightIcon sx={{ fontSize: 14 }} />
          </Box>
        ) : null}
      </Stack>
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
          <CircularProgress size={22} sx={{ color: PERF_UI.hdTeal }} />
        </Box>
      ) : null}
      {error ? <Alert severity="error">{error}</Alert> : null}
      {!loading && !error ? (
        <Stack spacing={1.25}>
          <Box>
            <Typography sx={{ ...PERF_TYPE.meta, letterSpacing: 0.5, mb: 0.5, textTransform: "uppercase" }}>
              Wash
            </Typography>
            {(emp?.wash_bags || []).length === 0 ? (
              <Typography sx={PERF_TYPE.body}>No wash credit</Typography>
            ) : (
              (emp?.wash_bags || []).map((row) => (
                <Box key={`w-${row.bag_id}`} sx={{ py: 0.65, borderBottom: `1px solid ${PERF_UI.rowBorder}` }}>
                  <Typography sx={{ ...PERF_TYPE.name, fontSize: 13 }}>
                    {row.customer_name || "Customer unavailable"}
                  </Typography>
                  <Typography sx={{ mt: 0.1, fontSize: 13, color: PERF_UI.secondary, fontWeight: 400 }}>
                    {row.bag_id}
                  </Typography>
                  <Typography sx={{ mt: 0.08, fontSize: 12, color: PERF_UI.muted, fontWeight: 400 }}>
                    Wash · {fmtTimeShort(row.washed_at) || "—"}
                  </Typography>
                </Box>
              ))
            )}
          </Box>
          <Box>
            <Typography sx={{ ...PERF_TYPE.meta, letterSpacing: 0.5, mb: 0.5, textTransform: "uppercase" }}>
              Fold
            </Typography>
            {(emp?.fold_bags || []).length === 0 ? (
              <Typography sx={PERF_TYPE.body}>No fold credit</Typography>
            ) : (
              (emp?.fold_bags || []).map((row) => (
                <Box key={`f-${row.bag_id}`} sx={{ py: 0.65, borderBottom: `1px solid ${PERF_UI.rowBorder}` }}>
                  <Typography sx={{ ...PERF_TYPE.name, fontSize: 13 }}>
                    {row.customer_name || "Customer unavailable"}
                  </Typography>
                  <Typography sx={{ mt: 0.1, fontSize: 13, color: PERF_UI.secondary, fontWeight: 400 }}>
                    {row.bag_id}
                  </Typography>
                  <Typography sx={{ mt: 0.08, fontSize: 12, color: PERF_UI.muted, fontWeight: 400 }}>
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

  return (
    <Box sx={{ minWidth: 0, width: "100%" }}>
      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 0.65 }}>
        <PerformanceSortSelect
          value={sortBy}
          options={HD_SORT_OPTIONS}
          onChange={setSortBy}
          aria-label="Sort employees"
        />
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Box sx={{ py: 5, textAlign: "center" }}>
          <CircularProgress size={28} sx={{ color: PERF_UI.hdTeal }} />
        </Box>
      ) : (
        <>
          <Box sx={perfKpiStripSx()}>
            <Typography sx={PERF_TYPE.kpi}>
              <Box component="span" sx={PERF_TYPE.kpiValue}>
                {fmtCount(summary.bags_washed)} Washed
              </Box>
              <PerfSeparator />
              <Box component="span" sx={PERF_TYPE.kpiValue}>
                {fmtCount(summary.bags_folded)} Folded
              </Box>
              <PerfSeparator />
              <Box component="span" sx={PERF_TYPE.kpiValue}>
                {fmtCount(summary.wash_employees)} Washers
              </Box>
              <PerfSeparator />
              <Box component="span" sx={PERF_TYPE.kpiValue}>
                {fmtCount(summary.fold_employees)} Folders
              </Box>
            </Typography>
          </Box>

          {employees.length === 0 ? (
            <Typography sx={{ py: 2, ...PERF_TYPE.body, textAlign: "center" }}>
              No Hang Dry wash/fold credit for this day.
            </Typography>
          ) : (
            <Stack spacing={0.3}>
              {employees.map((emp) => (
                <HdEmployeeCard key={emp.user_id} employee={emp} onViewOrders={setDetailEmployee} />
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
