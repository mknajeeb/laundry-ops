import { useCallback, useEffect, useMemo, useState } from "react";
import {
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
import DownloadIcon from "@mui/icons-material/Download";
import { getEmployeePaystubArchiveHtml, getPaystubArchiveMeta } from "../api";
import { downloadEmployeeRecentPaystubsPdf } from "../payroll/downloadEmployeePaystubArchive";
import {
  downloadPdfFromFetch,
  paystubArchiveDownloadFilename,
} from "../payroll/paystubDownload";
import {
  DEFAULT_RECENT_PAYSTUB_BATCHES,
  recentBatchIds,
} from "../payroll/paystubArchive";

const WORKER_CATEGORIES = [
  { value: "all", label: "All worker types" },
  { value: "w2", label: "W-2 employees" },
  { value: "temp", label: "Temp workers" },
  { value: "contractor_1099", label: "1099 contractors" },
];

function categoryLabel(value) {
  return WORKER_CATEGORIES.find((c) => c.value === value)?.label || "Employee";
}

export default function EmployeePaystubArchivePanel({
  onError,
  initialUserId = "",
  initialWorkerName = "",
}) {
  const [workerCategory, setWorkerCategory] = useState("w2");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [userId, setUserId] = useState(String(initialUserId || ""));
  const [copyMode, setCopyMode] = useState("employee");
  const [meta, setMeta] = useState({ batches: [], employees: [] });
  const [selectedBatchIds, setSelectedBatchIds] = useState([]);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (initialUserId) {
      setUserId(String(initialUserId));
    }
  }, [initialUserId]);

  const archiveParams = useMemo(
    () => ({
      worker_category: workerCategory,
      ...(periodStart ? { pay_period_start: periodStart } : {}),
      ...(periodEnd ? { pay_period_end: periodEnd } : {}),
      ...(selectedBatchIds.length
        ? { batch_ids: selectedBatchIds.join(",") }
        : {}),
    }),
    [workerCategory, periodStart, periodEnd, selectedBatchIds],
  );

  const loadMeta = useCallback(async () => {
    setLoadingMeta(true);
    try {
      const res = await getPaystubArchiveMeta({
        worker_category: workerCategory,
        ...(periodStart ? { pay_period_start: periodStart } : {}),
        ...(periodEnd ? { pay_period_end: periodEnd } : {}),
      });
      const batches = res.data?.batches || [];
      setMeta({
        batches,
        employees: res.data?.employees || [],
      });
      setSelectedBatchIds((prev) => {
        if (!prev.length) return recentBatchIds(batches);
        const allowed = new Set(batches.map((b) => b.id));
        const kept = prev.filter((id) => allowed.has(id));
        return kept.length ? kept : recentBatchIds(batches);
      });
    } catch (e) {
      setMeta({ batches: [], employees: [] });
      setSelectedBatchIds([]);
      onError?.(e.response?.data?.error || e.message || "Archive load failed");
    } finally {
      setLoadingMeta(false);
    }
  }, [workerCategory, periodStart, periodEnd, onError]);

  useEffect(() => {
    loadMeta();
  }, [loadMeta]);

  const selectedEmployeeName = useMemo(() => {
    if (!userId) return initialWorkerName || "";
    const match = meta.employees.find((e) => String(e.user_id) === String(userId));
    return match?.worker_name || initialWorkerName || "";
  }, [userId, meta.employees, initialWorkerName]);

  const displayBatches = useMemo(
    () => [...meta.batches].reverse(),
    [meta.batches],
  );

  const toggleBatch = (batchId) => {
    setSelectedBatchIds((prev) => {
      if (prev.includes(batchId)) {
        return prev.filter((id) => id !== batchId);
      }
      return [...prev, batchId];
    });
  };

  const selectRecentBatches = (count) => {
    setSelectedBatchIds(recentBatchIds(meta.batches, count));
  };

  const downloadArchive = async () => {
    if (!userId) {
      onError?.("Select an employee first");
      return;
    }
    if (!selectedBatchIds.length) {
      onError?.("Select at least one pay period");
      return;
    }
    setDownloading(true);
    try {
      const params = {
        ...archiveParams,
        copy: copyMode,
        user_id: userId,
      };
      const selectedBatches = meta.batches.filter((b) => selectedBatchIds.includes(b.id));
      const filename = paystubArchiveDownloadFilename({
        workerName: selectedEmployeeName,
        payPeriodStart: periodStart || selectedBatches[0]?.pay_period_start,
        payPeriodEnd:
          periodEnd || selectedBatches[selectedBatches.length - 1]?.pay_period_end,
      });
      await downloadPdfFromFetch(
        () => getEmployeePaystubArchiveHtml(params),
        filename,
      );
    } catch (e) {
      onError?.(e.response?.data?.error || e.message || "Archive PDF download failed");
    } finally {
      setDownloading(false);
    }
  };

  const downloadRecentForEmployee = async (count = DEFAULT_RECENT_PAYSTUB_BATCHES) => {
    if (!userId) {
      onError?.("Select an employee first");
      return;
    }
    setDownloading(true);
    try {
      await downloadEmployeeRecentPaystubsPdf({
        userId,
        workerName: selectedEmployeeName,
        workerCategory: workerCategory,
        copy: copyMode,
        recentCount: count,
      });
    } catch (e) {
      onError?.(e.response?.data?.error || e.message || "Paystub PDF download failed");
    } finally {
      setDownloading(false);
    }
  };

  const selectedCount = selectedBatchIds.length;

  return (
    <Stack spacing={1.5}>
      <Typography variant="body2" color="text.secondary">
        Pick an employee, then download one PDF with their paystubs from the last few pay
        periods (default: last {DEFAULT_RECENT_PAYSTUB_BATCHES}). Toggle chips to include
        or exclude specific batches.
      </Typography>

      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <FormControl size="small" required sx={{ minWidth: 220 }}>
          <InputLabel>Employee</InputLabel>
          <Select
            label="Employee"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          >
            <MenuItem value="" disabled>Select employee…</MenuItem>
            {meta.employees.map((emp) => (
              <MenuItem key={emp.user_id} value={String(emp.user_id)}>
                {emp.worker_name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Worker type</InputLabel>
          <Select
            label="Worker type"
            value={workerCategory}
            onChange={(e) => setWorkerCategory(e.target.value)}
          >
            {WORKER_CATEGORIES.map((c) => (
              <MenuItem key={c.value} value={c.value}>{c.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          size="small"
          label="Pay period from"
          type="date"
          value={periodStart}
          onChange={(e) => setPeriodStart(e.target.value)}
          InputLabelProps={{ shrink: true }}
          sx={{ width: 160 }}
        />
        <TextField
          size="small"
          label="Pay period through"
          type="date"
          value={periodEnd}
          onChange={(e) => setPeriodEnd(e.target.value)}
          InputLabelProps={{ shrink: true }}
          sx={{ width: 160 }}
        />
        <FormControl size="small" sx={{ minWidth: 170 }}>
          <InputLabel>Copy type</InputLabel>
          <Select
            label="Copy type"
            value={copyMode}
            onChange={(e) => setCopyMode(e.target.value)}
          >
            <MenuItem value="employee">Employee copy</MenuItem>
            <MenuItem value="employer">Employer copy</MenuItem>
          </Select>
        </FormControl>
      </Stack>

      <Box>
        <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 0.5 }}>
          <Typography variant="caption" color="text.secondary">
            Pay periods ({selectedCount} selected)
          </Typography>
          <Button size="small" onClick={() => selectRecentBatches(5)} disabled={!meta.batches.length}>
            Last 5
          </Button>
          <Button size="small" onClick={() => selectRecentBatches(6)} disabled={!meta.batches.length}>
            Last 6
          </Button>
          <Button
            size="small"
            onClick={() => setSelectedBatchIds(meta.batches.map((b) => b.id))}
            disabled={!meta.batches.length}
          >
            All
          </Button>
        </Stack>
        {loadingMeta ? (
          <Typography variant="body2" color="text.secondary">Loading…</Typography>
        ) : meta.batches.length ? (
          <Stack direction="row" flexWrap="wrap" gap={0.5}>
            {displayBatches.map((b) => {
              const selected = selectedBatchIds.includes(b.id);
              return (
                <Chip
                  key={b.id}
                  size="small"
                  label={`${b.batch_name} · ${b.pay_period_start} – ${b.pay_period_end}`}
                  color={selected ? "primary" : "default"}
                  variant={selected ? "filled" : "outlined"}
                  onClick={() => toggleBatch(b.id)}
                  sx={{ cursor: "pointer" }}
                />
              );
            })}
          </Stack>
        ) : (
          <Alert severity="info" sx={{ py: 0 }}>
            No finalized pay periods match these filters.
          </Alert>
        )}
      </Box>

      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Button
          size="small"
          variant="contained"
          startIcon={<DownloadIcon />}
          disabled={downloading || !userId || !selectedBatchIds.length}
          onClick={downloadArchive}
        >
          {downloading ? "Generating PDF…" : "Download employee PDF"}
        </Button>
        <Button
          size="small"
          variant="outlined"
          startIcon={<DownloadIcon />}
          disabled={downloading || !userId}
          onClick={() => downloadRecentForEmployee(DEFAULT_RECENT_PAYSTUB_BATCHES)}
        >
          Quick: last {DEFAULT_RECENT_PAYSTUB_BATCHES} periods
        </Button>
        {userId && selectedCount ? (
          <Typography variant="caption" color="text.secondary">
            {selectedEmployeeName} · {selectedCount} pay period(s)
          </Typography>
        ) : null}
      </Stack>
    </Stack>
  );
}
