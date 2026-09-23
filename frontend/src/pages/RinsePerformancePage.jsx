import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Box, CircularProgress, Stack } from "@mui/material";
import {
  getRinseDashboardDaily,
  getRinseDashboardEmployeeRole,
  getRinseDashboardOverview,
  getRinseDashboardRoles,
} from "../api";
import { VEEWASH_BRAND } from "../theme/veewashBrand";
import RinsePerfByEmployeeView from "../components/rinse-performance/RinsePerfByEmployeeView";
import RinsePerfByRoleView from "../components/rinse-performance/RinsePerfByRoleView";
import RinsePerfDailyView from "../components/rinse-performance/RinsePerfDailyView";
import RinsePerfFilterBar from "../components/rinse-performance/RinsePerfFilterBar";
import RinsePerfOverviewView from "../components/rinse-performance/RinsePerfOverviewView";
import { METRICS, etTodayYmd } from "../components/rinse-performance/rinsePerfFormat";

function readParam(params, key, fallback) {
  const v = params.get(key);
  return v != null && v !== "" ? v : fallback;
}

export default function RinsePerformancePage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const view = readParam(searchParams, "view", "overview");
  const period = readParam(searchParams, "period", "this_week");
  const compare = readParam(searchParams, "compare", "previous_period");
  const metricKey = readParam(searchParams, "metric", "lbs_hr");
  const roleKey = readParam(searchParams, "role", "FOLDER");
  const employeeId = searchParams.get("employee") || null;
  const customStart = searchParams.get("start") || "";
  const customEnd = searchParams.get("end") || "";
  const dailyDate = readParam(searchParams, "date", etTodayYmd());

  const patchParams = useCallback(
    (patch) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          Object.entries(patch).forEach(([k, v]) => {
            if (v == null || v === "") next.delete(k);
            else next.set(k, String(v));
          });
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  const [overview, setOverview] = useState(null);
  const [rolesData, setRolesData] = useState(null);
  const [employeeList, setEmployeeList] = useState([]);
  const [employeeHistory, setEmployeeHistory] = useState(null);
  const [dailyData, setDailyData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const metricMeta = useMemo(
    () => METRICS.find((m) => m.key === metricKey) || METRICS[0],
    [metricKey]
  );

  const periodParams = useMemo(() => {
    const p = {
      period,
      compare: compare === "none" ? "none" : compare,
      metric: metricKey,
      role_key: roleKey,
    };
    if (period === "custom") {
      p.start = customStart;
      p.end = customEnd;
    }
    return p;
  }, [period, compare, metricKey, roleKey, customStart, customEnd]);

  const resolvedLabel = useMemo(() => {
    const src = overview || rolesData || employeeHistory;
    if (!src?.period) {
      if (view === "daily") return `Business date ${dailyDate}`;
      return null;
    }
    const p = src.period;
    let label = `${p.label || period}: ${p.start_et} → ${p.end_et}`;
    if (src.compare) {
      label += ` · vs ${src.compare.label} (${src.compare.start_et} → ${src.compare.end_et})`;
    }
    return label;
  }, [overview, rolesData, employeeHistory, view, dailyDate, period]);

  const load = useCallback(async () => {
    if (period === "custom" && (!customStart || !customEnd) && view !== "daily") {
      setLoading(false);
      setError("Select custom start and end dates.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (view === "overview") {
        const res = await getRinseDashboardOverview(periodParams);
        setOverview(res.data);
        setRolesData(null);
        setDailyData(null);
        setEmployeeHistory(null);
      } else if (view === "role") {
        const res = await getRinseDashboardRoles(periodParams);
        setRolesData(res.data);
        setOverview(null);
        setDailyData(null);
      } else if (view === "employee") {
        const ov = await getRinseDashboardOverview(periodParams);
        const emps = ov.data?.employee_snapshot || [];
        setEmployeeList(emps);
        setOverview(null);
        if (employeeId) {
          const hist = await getRinseDashboardEmployeeRole(employeeId, roleKey, periodParams);
          setEmployeeHistory(hist.data);
        } else {
          setEmployeeHistory(null);
        }
        setRolesData(null);
        setDailyData(null);
      } else if (view === "daily") {
        const res = await getRinseDashboardDaily({
          date: dailyDate,
          metric: metricKey,
          role_key: roleKey,
        });
        setDailyData(res.data);
        setOverview(null);
        setRolesData(null);
        setEmployeeHistory(null);
      }
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Unable to load performance");
    } finally {
      setLoading(false);
    }
  }, [
    view,
    periodParams,
    period,
    customStart,
    customEnd,
    employeeId,
    roleKey,
    dailyDate,
    metricKey,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  const unit =
    overview?.unit || rolesData?.unit || employeeHistory?.unit || dailyData?.unit || metricMeta.unit;

  return (
    <Box sx={{ minHeight: "100%", bgcolor: VEEWASH_BRAND.pageBg, pb: 4 }}>
      <RinsePerfFilterBar
        view={view}
        onView={(v) => patchParams({ view: v })}
        period={period}
        onPeriod={(v) => patchParams({ period: v })}
        compare={compare}
        onCompare={(v) => patchParams({ compare: v })}
        metric={metricKey}
        onMetric={(v) => patchParams({ metric: v })}
        customStart={customStart}
        customEnd={customEnd}
        onCustomStart={(v) => patchParams({ start: v, period: "custom" })}
        onCustomEnd={(v) => patchParams({ end: v, period: "custom" })}
        resolvedLabel={resolvedLabel}
        showRole={view === "overview" || view === "daily" || view === "employee"}
        roleKey={roleKey}
        onRole={(v) => patchParams({ role: v })}
        showEmployee={view === "employee"}
        employees={employeeList}
        employeeId={employeeId}
        onEmployee={(v) => patchParams({ employee: v })}
        showDate={view === "daily"}
        dailyDate={dailyDate}
        onDailyDate={(v) => patchParams({ date: v })}
      />

      <Box sx={{ px: { xs: 1.5, md: 2 } }}>
        {error ? (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        ) : null}
        {loading ? (
          <Stack alignItems="center" py={6}>
            <CircularProgress size={28} sx={{ color: VEEWASH_BRAND.primary }} />
          </Stack>
        ) : null}
        {!loading && view === "overview" ? (
          <RinsePerfOverviewView data={overview} metricKey={metricKey} unit={unit} />
        ) : null}
        {!loading && view === "role" ? (
          <RinsePerfByRoleView
            data={rolesData}
            metricKey={metricKey}
            unit={unit}
            onSelectRole={(rk) => patchParams({ role: rk, view: "employee" })}
          />
        ) : null}
        {!loading && view === "employee" ? (
          <RinsePerfByEmployeeView data={employeeHistory} metricKey={metricKey} unit={unit} />
        ) : null}
        {!loading && view === "daily" ? (
          <RinsePerfDailyView data={dailyData} metricKey={metricKey} unit={unit} />
        ) : null}
      </Box>
    </Box>
  );
}
