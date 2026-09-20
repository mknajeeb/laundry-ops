import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import AddIcon from "@mui/icons-material/Add";
import AttachMoneyIcon from "@mui/icons-material/AttachMoney";
import CheckIcon from "@mui/icons-material/Check";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import {
  deletePayrollTimeRecord,
  deletePayrollTimeRecordBreak,
  deletePayrollTimeRecordSegment,
  getPayrollCalendarSettings,
  getPayrollScheduleSettings,
  getPayrollScheduleWorkers,
  getPayrollTimeRecords,
  getTaUsers,
  getTaskTrackingSelectionTree,
  patchPayrollTimeRecord,
  patchPayrollTimeRecordBreak,
  patchPayrollTimeRecordSegment,
  postApprovePayrollTimeRecord,
  postBulkApprovePayrollTimeRecords,
  postPayrollClassificationOverride,
  postPayrollTimeRecord,
  postPayrollTimeRecordBreak,
} from "../api";
import {
  formatEasternTimeShort,
  formatHoursDecimal,
} from "../utils/datetimeFormat";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";
import {
  buildWorkerRateMap,
  enrichTimeRecords,
  formatPayrollMoney,
  formatPayrollRate,
} from "../payroll/timeRecordPayroll";
import { displayRoleLabel } from "../opsMobile/switchRoleFlowHelpers";
import {
  CLASSIFICATION_OVERRIDE_OPTIONS,
  classificationSelectValue,
  formatRecordClassificationLabel,
} from "../payroll/payrollClassification";
import { PayrollDateField, PayrollDateTimeField } from "./PayrollDateTimeField";

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "completed", label: "Awaiting approval" },
  { value: "pending_approval", label: "Pending approval" },
  { value: "approved", label: "Approved" },
];

function statusLabel(st) {
  if (st === "pending_approval") return "Pending approval";
  if (st === "approved") return "Approved";
  if (st === "open") return "Open";
  if (st === "completed") return "Awaiting approval";
  return st || "—";
}

function statusColor(st) {
  if (st === "open") return "info";
  if (st === "approved") return "success";
  if (st === "pending_approval" || st === "completed") return "warning";
  return "default";
}

function canApproveRecord(row) {
  if (row?.has_open_break) return false;
  return (
    row?.status === "pending_approval" ||
    row?.status === "completed" ||
    (row?.status !== "approved" && row?.status !== "open" && !row?.payroll_hours_approved)
  );
}

function formatPayableComposition(row) {
  const pc = row?.payable_composition;
  if (!pc) return null;
  return `Payable ${formatHoursDecimal(pc.payable_hours)} = elapsed ${formatHoursDecimal(pc.elapsed_hours)} − breaks ${formatHoursDecimal(pc.break_hours)}`;
}

const emptyBreakForm = () => ({
  break_start_at: "",
  break_end_at: "",
});

function toDatetimeLocal(val) {
  if (!val) return "";
  const s = String(val).trim().replace(" ", "T");
  if (s.length >= 16) return s.slice(0, 16);
  return s;
}

function toApiDateTime(local) {
  if (!local) return "";
  return local.length === 16 ? `${local.replace("T", " ")}:00` : local;
}

/** Keep original seconds when the picker minute is unchanged (datetime-local is minute-only). */
function toApiDateTimePreservingSeconds(local, originalApiValue) {
  if (!local) return "";
  const localMinute = local.length >= 16 ? local.slice(0, 16) : local;
  if (originalApiValue && toDatetimeLocal(originalApiValue) === localMinute) {
    const raw = String(originalApiValue).trim();
    const m = raw.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/);
    if (m) return `${m[1]} ${m[2]}`;
  }
  return toApiDateTime(local);
}

const emptyForm = () => ({
  user_id: "",
  category_id: "",
  role_id: "",
  clock_in_at: "",
  clock_out_at: "",
  notes: "",
});

const emptySegmentForm = () => ({
  category_id: "",
  role_id: "",
  started_at: "",
  ended_at: "",
});

function hoursCellSx(level, theme) {
  if (level === "critical") {
    return {
      bgcolor: alpha(theme.palette.error.main, 0.14),
      color: theme.palette.error.dark,
      fontWeight: 700,
    };
  }
  if (level === "warning") {
    return {
      bgcolor: alpha(theme.palette.warning.main, 0.18),
      color: theme.palette.warning.dark,
      fontWeight: 600,
    };
  }
  return { fontVariantNumeric: "tabular-nums" };
}

function SummaryStat({ icon, label, value, valueSx, details = [], gradient }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.75,
        borderRadius: 2,
        border: "1px solid",
        borderColor: "divider",
        background: gradient,
      }}
    >
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <Box
          sx={{
            width: 40,
            height: 40,
            borderRadius: 1.5,
            display: "grid",
            placeItems: "center",
            bgcolor: "background.paper",
            boxShadow: 1,
            flexShrink: 0,
          }}
        >
          {icon}
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: 0.4 }}>
            {label}
          </Typography>
          <Typography variant="h6" sx={{ lineHeight: 1.2, fontWeight: 700, ...valueSx }}>
            {value}
          </Typography>
          {details.map((line) => (
            <Typography key={line} variant="caption" color="text.secondary" display="block">
              {line}
            </Typography>
          ))}
        </Box>
      </Stack>
    </Paper>
  );
}

export default function PayrollTimeRecordsPanel({
  payPeriodStart = "",
  payPeriodEnd = "",
  linkedCategory = "all",
  onPayPeriodChange,
}) {
  const theme = useTheme();
  const [fromDate, setFromDate] = useState(payPeriodStart || "");
  const [toDate, setToDate] = useState(payPeriodEnd || "");
  const [category, setCategory] = useState(linkedCategory || "all");
  const [status, setStatus] = useState("all");
  const [userId, setUserId] = useState("");
  const [users, setUsers] = useState([]);
  const [selectionTree, setSelectionTree] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [scheduleSettings, setScheduleSettings] = useState(null);
  const [calendarSettings, setCalendarSettings] = useState(null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [classNotice, setClassNotice] = useState("");
  const [classEdit, setClassEdit] = useState(null);
  const [classBusy, setClassBusy] = useState(false);
  const [editorError, setEditorError] = useState("");
  const [loading, setLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState("add");
  const [form, setForm] = useState(emptyForm);
  const [initialRoleKey, setInitialRoleKey] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editingSegmentCount, setEditingSegmentCount] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [segmentEditorOpen, setSegmentEditorOpen] = useState(false);
  const [segmentForm, setSegmentForm] = useState(emptySegmentForm);
  const [segmentTarget, setSegmentTarget] = useState(null);
  const [segmentEditorError, setSegmentEditorError] = useState("");
  const [segmentWarning, setSegmentWarning] = useState("");
  const [segmentDeleteTarget, setSegmentDeleteTarget] = useState(null);
  const [breakEditorOpen, setBreakEditorOpen] = useState(false);
  const [breakEditorMode, setBreakEditorMode] = useState("edit");
  const [breakForm, setBreakForm] = useState(emptyBreakForm);
  const [breakTarget, setBreakTarget] = useState(null);
  const [breakEditorError, setBreakEditorError] = useState("");
  const [breakDeleteTarget, setBreakDeleteTarget] = useState(null);
  const [breakConflict, setBreakConflict] = useState(null);
  const [saving, setSaving] = useState(false);
  const [bulkApproving, setBulkApproving] = useState(false);

  useEffect(() => {
    getTaUsers()
      .then((r) => setUsers(r.data?.users || r.data || []))
      .catch(() => {});
    getTaskTrackingSelectionTree()
      .then((r) => setSelectionTree(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
    getPayrollScheduleWorkers()
      .then((r) => setWorkers(r.data?.items || []))
      .catch(() => {});
    getPayrollScheduleSettings()
      .then((r) => setScheduleSettings(r.data || null))
      .catch(() => {});
    getPayrollCalendarSettings()
      .then((r) => setCalendarSettings(r.data || null))
      .catch(() => {});
  }, []);

  const rateMap = useMemo(
    () => buildWorkerRateMap(workers, scheduleSettings, calendarSettings, rows),
    [workers, scheduleSettings, calendarSettings, rows],
  );

  const {
    rows: displayRows,
    totalHours,
    totalCost,
    totalRegularCost,
    totalOtCost,
    summaryHoursLevel,
  } = useMemo(
    () => enrichTimeRecords(rows, rateMap, { userId }),
    [rows, rateMap, userId],
  );

  const summaryHoursSx = useMemo(() => {
    if (summaryHoursLevel === "critical") {
      return { color: theme.palette.error.dark };
    }
    if (summaryHoursLevel === "warning") {
      return { color: theme.palette.warning.dark };
    }
    return undefined;
  }, [summaryHoursLevel, theme]);

  const approvableRows = rows.filter(canApproveRecord);

  useEffect(() => {
    if (payPeriodStart) setFromDate(payPeriodStart);
  }, [payPeriodStart]);

  useEffect(() => {
    if (payPeriodEnd) setToDate(payPeriodEnd);
  }, [payPeriodEnd]);

  useEffect(() => {
    if (linkedCategory && linkedCategory !== "all") setCategory(linkedCategory);
  }, [linkedCategory]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate;
      if (category !== "all") params.worker_category = category;
      if (status !== "all") params.status = status;
      if (userId) params.user_id = userId;
      const res = await getPayrollTimeRecords(params);
      setRows(res.data?.items || []);
      setError("");
    } catch (e) {
      if (e.code === "ERR_NETWORK") {
        setError(
          "Could not reach the server. Check your connection or wait for the API deploy to finish.",
        );
      } else {
        setError(e.response?.data?.error || e.message || "Load failed");
      }
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, category, status, userId]);

  useEffect(() => {
    load();
  }, [load]);

  const openAdd = () => {
    setEditorMode("add");
    setEditingId(null);
    setEditingSegmentCount(0);
    setInitialRoleKey("");
    setEditorError("");
    setForm(emptyForm());
    setEditorOpen(true);
  };

  const openEdit = (row) => {
    setEditorMode("edit");
    setEditingId(row.id);
    setEditorError("");
    const segs = Array.isArray(row.role_segments) ? row.role_segments : [];
    setEditingSegmentCount(segs.length);
    const lastSeg = segs.length ? segs[segs.length - 1] : null;
    const categoryId = lastSeg?.category_id != null ? String(lastSeg.category_id) : "";
    const roleId = lastSeg?.role_id != null ? String(lastSeg.role_id) : "";
    setInitialRoleKey(`${categoryId}:${roleId}`);
    setForm({
      user_id: String(row.user_id || ""),
      category_id: categoryId,
      role_id: roleId,
      clock_in_at: toDatetimeLocal(row.clock_in_at),
      clock_out_at: toDatetimeLocal(row.clock_out_at) || toDatetimeLocal(lastSeg?.ended_at),
      notes: row.notes || "",
    });
    setEditorOpen(true);
  };

  const saveEditor = async () => {
    if (!form.user_id || !form.clock_in_at) {
      setEditorError("Worker and clock in are required.");
      return;
    }
    const clockOutApi = form.clock_out_at ? toApiDateTime(form.clock_out_at) : "";
    if (clockOutApi && form.clock_in_at && clockOutApi <= toApiDateTime(form.clock_in_at)) {
      setEditorError("Clock out must be after clock in.");
      return;
    }
    const multiRoleDay = editorMode === "edit" && editingSegmentCount > 1;
    const hasCategory = form.category_id !== "" && form.category_id != null;
    const hasRole = form.role_id !== "" && form.role_id != null;
    if (!multiRoleDay && hasCategory !== hasRole) {
      setEditorError("Select both category and role to tag a role, or leave both blank.");
      return;
    }
    if (!multiRoleDay && (hasCategory || hasRole) && !selectionTree.length) {
      setEditorError(
        "Category/role list failed to load. Refresh the page, or check that your account can view job tracking.",
      );
      return;
    }
    const roleKey = `${form.category_id || ""}:${form.role_id || ""}`;
    const roleChanged =
      !multiRoleDay && (editorMode === "add" || roleKey !== initialRoleKey);
    setSaving(true);
    setEditorError("");
    setError("");
    try {
      const remarks = (form.notes || "").trim() || "Payroll time record update";
      const payload = {
        clock_in_at: toApiDateTime(form.clock_in_at),
        clock_out_at: clockOutApi,
        remarks: editorMode === "add" ? remarks : form.notes || "",
      };
      if (roleChanged && hasCategory && hasRole) {
        payload.category_id = Number(form.category_id);
        payload.role_id = Number(form.role_id);
      }
      if (editorMode === "add") {
        await postPayrollTimeRecord({
          user_id: Number(form.user_id),
          ...payload,
        });
      } else if (editingId) {
        await patchPayrollTimeRecord(editingId, payload);
      }
      setEditorOpen(false);
      await load();
    } catch (e) {
      const msg = e.response?.data?.error
        ? e.response.data.error
        : e.code === "ERR_NETWORK"
          ? "Save blocked by browser (API CORS). Hard-refresh after deploy, or contact support if this persists."
          : e.message || "Save failed";
      setEditorError(msg);
    } finally {
      setSaving(false);
    }
  };

  const approveRecord = async (row) => {
    setError("");
    try {
      await postApprovePayrollTimeRecord(row.id);
      await load();
    } catch (e) {
      const data = e.response?.data || {};
      if (data.error === "open_break_blocks_approval" || data.open_breaks) {
        setError(
          data.message ||
            data.error ||
            "Resolve the open break before approving this time record.",
        );
      } else {
        setError(data.error || e.message || "Approve failed");
      }
    }
  };

  const bulkApproveVisible = async () => {
    if (!approvableRows.length) return;
    setBulkApproving(true);
    setError("");
    try {
      const res = await postBulkApprovePayrollTimeRecords({
        ids: approvableRows.map((r) => r.id),
      });
      const n = res.data?.approved || 0;
      const skipped = res.data?.skipped || 0;
      if (skipped) {
        setError(`Approved ${n} record(s). ${skipped} could not be approved.`);
      }
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Bulk approve failed");
    } finally {
      setBulkApproving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget?.id) return;
    setSaving(true);
    setError("");
    try {
      await deletePayrollTimeRecord(deleteTarget.id);
      setDeleteTarget(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete failed");
    } finally {
      setSaving(false);
    }
  };

  const openSegmentEdit = (row, seg) => {
    setSegmentTarget({ record: row, segment: seg });
    setSegmentEditorError("");
    setSegmentWarning("");
    setSegmentForm({
      category_id: seg?.category_id != null ? String(seg.category_id) : "",
      role_id: seg?.role_id != null ? String(seg.role_id) : "",
      started_at: toDatetimeLocal(seg?.started_at),
      ended_at: toDatetimeLocal(seg?.ended_at),
    });
    setSegmentEditorOpen(true);
  };

  const saveSegmentEditor = async (conflictResolution = null) => {
    if (!segmentTarget?.record?.id || !segmentTarget?.segment?.id) return;
    if (!segmentForm.started_at) {
      setSegmentEditorError("Start time is required.");
      return;
    }
    const hasCategory = segmentForm.category_id !== "" && segmentForm.category_id != null;
    const hasRole = segmentForm.role_id !== "" && segmentForm.role_id != null;
    if (!hasCategory || !hasRole) {
      setSegmentEditorError("Category and role are required for a role segment.");
      return;
    }
    if (!selectionTree.length) {
      setSegmentEditorError(
        "Category/role list failed to load. Refresh the page, or check that your account can view job tracking.",
      );
      return;
    }
    const endApi = segmentForm.ended_at
      ? toApiDateTimePreservingSeconds(segmentForm.ended_at, segmentTarget.segment?.ended_at)
      : "";
    const startApi = toApiDateTimePreservingSeconds(
      segmentForm.started_at,
      segmentTarget.segment?.started_at,
    );
    if (endApi && endApi <= startApi) {
      setSegmentEditorError("End time must be after start time.");
      return;
    }
    setSaving(true);
    setSegmentEditorError("");
    setSegmentWarning("");
    setError("");
    try {
      const payload = {
        category_id: Number(segmentForm.category_id),
        role_id: Number(segmentForm.role_id),
        started_at: startApi,
        ended_at: endApi,
      };
      if (conflictResolution) {
        payload.break_conflict_resolution = conflictResolution.key;
        if (conflictResolution.break_id != null) {
          payload.resolve_break_id = conflictResolution.break_id;
        }
      }
      const res = await patchPayrollTimeRecordSegment(
        segmentTarget.record.id,
        segmentTarget.segment.id,
        payload,
      );
      const warnings = Array.isArray(res.data?.warnings) ? res.data.warnings : [];
      setSegmentEditorOpen(false);
      setSegmentTarget(null);
      setBreakConflict(null);
      if (warnings.length) {
        setSegmentWarning(warnings.join(" "));
      }
      await load();
    } catch (e) {
      const data = e.response?.data || {};
      if (data.error === "segment_break_conflict" || Array.isArray(data.conflicts)) {
        setBreakConflict({
          recordId: segmentTarget.record.id,
          segmentId: segmentTarget.segment.id,
          payload: data,
        });
        setSegmentEditorError("");
      } else {
        setSegmentEditorError(data.error || e.message || "Role segment save failed");
      }
    } finally {
      setSaving(false);
    }
  };

  const openBreakEdit = (row, br) => {
    setBreakEditorMode(br?.status === "open" ? "close" : "edit");
    setBreakTarget({ record: row, breakRow: br });
    setBreakEditorError("");
    setBreakForm({
      break_start_at: toDatetimeLocal(br?.break_start_at),
      break_end_at: toDatetimeLocal(br?.break_end_at),
    });
    setBreakEditorOpen(true);
  };

  const openBreakAdd = (row) => {
    setBreakEditorMode("add");
    setBreakTarget({ record: row, breakRow: null });
    setBreakEditorError("");
    setBreakForm(emptyBreakForm());
    setBreakEditorOpen(true);
  };

  const saveBreakEditor = async () => {
    if (!breakTarget?.record?.id) return;
    if (breakEditorMode !== "close" && !breakForm.break_start_at) {
      setBreakEditorError("Break start is required.");
      return;
    }
    if (!breakForm.break_end_at) {
      setBreakEditorError(
        breakEditorMode === "close"
          ? "Enter the break end time to close this open break. The system will not guess it."
          : "Break end is required for a completed break.",
      );
      return;
    }
    const startApi =
      breakEditorMode === "close"
        ? null
        : toApiDateTimePreservingSeconds(
            breakForm.break_start_at,
            breakTarget.breakRow?.break_start_at,
          );
    const endApi = toApiDateTimePreservingSeconds(
      breakForm.break_end_at,
      breakTarget.breakRow?.break_end_at,
    );
    if (startApi && endApi && endApi <= startApi) {
      setBreakEditorError("Break end must be after break start.");
      return;
    }
    setSaving(true);
    setBreakEditorError("");
    setError("");
    try {
      if (breakEditorMode === "add") {
        await postPayrollTimeRecordBreak(breakTarget.record.id, {
          break_start_at: startApi,
          break_end_at: endApi,
        });
      } else if (breakEditorMode === "close") {
        await patchPayrollTimeRecordBreak(
          breakTarget.record.id,
          breakTarget.breakRow.id,
          { action: "close", break_end_at: endApi },
        );
      } else {
        await patchPayrollTimeRecordBreak(
          breakTarget.record.id,
          breakTarget.breakRow.id,
          { break_start_at: startApi, break_end_at: endApi },
        );
      }
      setBreakEditorOpen(false);
      setBreakTarget(null);
      await load();
    } catch (e) {
      setBreakEditorError(e.response?.data?.error || e.message || "Break save failed");
    } finally {
      setSaving(false);
    }
  };

  const confirmBreakDelete = async () => {
    if (!breakDeleteTarget?.record?.id || !breakDeleteTarget?.breakRow?.id) return;
    setSaving(true);
    setError("");
    try {
      await deletePayrollTimeRecordBreak(
        breakDeleteTarget.record.id,
        breakDeleteTarget.breakRow.id,
      );
      setBreakDeleteTarget(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Break delete failed");
    } finally {
      setSaving(false);
    }
  };

  const confirmSegmentDelete = async () => {
    if (!segmentDeleteTarget?.record?.id || !segmentDeleteTarget?.segment?.id) return;
    setSaving(true);
    setError("");
    setSegmentWarning("");
    try {
      const res = await deletePayrollTimeRecordSegment(
        segmentDeleteTarget.record.id,
        segmentDeleteTarget.segment.id,
      );
      const warnings = Array.isArray(res.data?.warnings) ? res.data.warnings : [];
      setSegmentDeleteTarget(null);
      if (warnings.length) {
        setSegmentWarning(warnings.join(" "));
      }
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Role segment delete failed");
    } finally {
      setSaving(false);
    }
  };

  const saveClassification = async () => {
    if (!classEdit?.row?.id) return;
    setClassBusy(true);
    try {
      const res = await postPayrollClassificationOverride(classEdit.row.id, {
        payroll_classification_override: classEdit.value || null,
        reason: classEdit.reason || "",
      });
      const warnings = res.data?.warnings || [];
      setClassNotice(
        warnings.length
          ? warnings.map((w) => w.message).filter(Boolean).join(" ")
          : "",
      );
      setClassEdit(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not update classification");
    } finally {
      setClassBusy(false);
    }
  };

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {classNotice ? (
        <Alert severity="warning" onClose={() => setClassNotice("")}>
          {classNotice}
        </Alert>
      ) : null}
      {segmentWarning ? (
        <Alert severity="warning" onClose={() => setSegmentWarning("")}>
          {segmentWarning}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
          sx={{ mb: 1 }}
        >
          <Typography variant="subtitle1">Time Records</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button
              variant="contained"
              size="small"
              color="success"
              startIcon={<CheckIcon />}
              onClick={bulkApproveVisible}
              disabled={bulkApproving || !approvableRows.length}
            >
              {bulkApproving
                ? "Approving…"
                : `Bulk approve (${approvableRows.length})`}
            </Button>
            <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={openAdd}>
              Add record
            </Button>
          </Stack>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Review clock-in/out, then click <strong>Approve</strong>. Approved hours in this date range
          sync into matching payout batches automatically.
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              sm: "repeat(2, 1fr)",
              md: "repeat(3, minmax(140px, 1fr)) auto",
            },
            gap: 1.5,
            alignItems: "end",
          }}
        >
          <FormControl size="small">
            <InputLabel>Worker category</InputLabel>
            <Select
              label="Worker category"
              value={category}
              onChange={(e) => {
                const v = e.target.value;
                setCategory(v);
                onPayPeriodChange?.({ start: fromDate, end: toDate, category: v });
              }}
            >
              {WORKER_CATEGORY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small">
            <InputLabel>Status</InputLabel>
            <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small">
            <InputLabel>Worker</InputLabel>
            <Select label="Worker" value={userId} onChange={(e) => setUserId(e.target.value)}>
              <MenuItem value="">All</MenuItem>
              {users.map((u) => (
                <MenuItem key={u.id} value={String(u.id)}>
                  {u.first_name} {u.last_name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button variant="outlined" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Apply filters"}
          </Button>
        </Box>
      </Paper>

      <Paper
        elevation={0}
        sx={{
          p: 2,
          borderRadius: 2,
          border: "1px solid",
          borderColor: "divider",
          background: `linear-gradient(135deg, ${alpha(theme.palette.primary.main, 0.04)} 0%, ${alpha(theme.palette.background.paper, 1)} 100%)`,
        }}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={2}
          sx={{ mb: 2 }}
        >
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              Period summary
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {fromDate && toDate ? `${fromDate} – ${toDate}` : "Set dates to see totals"}
              {userId ? " · filtered to one worker" : ""}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              variant="outlined"
              label=">35h orange"
              sx={{ borderColor: alpha(theme.palette.warning.main, 0.5) }}
            />
            <Chip
              size="small"
              variant="outlined"
              color="error"
              label="≥40h red"
            />
          </Stack>
        </Stack>

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
            gap: 1.5,
            mb: 2,
          }}
        >
          <SummaryStat
            icon={<AccessTimeIcon color="primary" fontSize="small" />}
            label="Total hours"
            value={formatHoursDecimal(totalHours)}
            valueSx={summaryHoursSx}
            details={[
              `${displayRows.length} record${displayRows.length === 1 ? "" : "s"}`,
              summaryHoursLevel === "critical"
                ? "At or above 40h — overtime"
                : summaryHoursLevel === "warning"
                  ? "Above 35h — approaching overtime"
                  : null,
            ].filter(Boolean)}
            gradient={
              summaryHoursLevel === "critical"
                ? `linear-gradient(135deg, ${alpha(theme.palette.error.main, 0.12)} 0%, ${alpha(theme.palette.error.main, 0.03)} 100%)`
                : summaryHoursLevel === "warning"
                  ? `linear-gradient(135deg, ${alpha(theme.palette.warning.main, 0.14)} 0%, ${alpha(theme.palette.warning.main, 0.03)} 100%)`
                  : `linear-gradient(135deg, ${alpha(theme.palette.primary.main, 0.08)} 0%, ${alpha(theme.palette.primary.main, 0.02)} 100%)`
            }
          />
          <SummaryStat
            icon={<AttachMoneyIcon color="success" fontSize="small" />}
            label="Total cost"
            value={formatPayrollMoney(totalCost, { allowZero: true })}
            details={[
              `Regular/Base ${formatPayrollMoney(totalRegularCost, { allowZero: true })}`,
              `OT Premium ${formatPayrollMoney(totalOtCost, { allowZero: true })}`,
              "Same rules for W-2, 1099, and temp",
            ]}
            gradient={`linear-gradient(135deg, ${alpha(theme.palette.success.main, 0.1)} 0%, ${alpha(theme.palette.success.main, 0.02)} 100%)`}
          />
        </Box>

      <TableContainer sx={{ width: "100%", overflowX: "auto", borderRadius: 1.5 }}>
        <Table size="small" sx={{ minWidth: 980 }}>
          <TableHead>
            <TableRow
              sx={{
                "& th": {
                  fontWeight: 700,
                  fontSize: "0.75rem",
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                  bgcolor: alpha(theme.palette.primary.main, 0.06),
                  borderBottom: `2px solid ${alpha(theme.palette.primary.main, 0.2)}`,
                  whiteSpace: "nowrap",
                },
              }}
            >
              <TableCell>Date</TableCell>
              <TableCell>Worker</TableCell>
              <TableCell>Cat.</TableCell>
              <TableCell>Role</TableCell>
              <TableCell>In</TableCell>
              <TableCell>Out</TableCell>
              <TableCell align="right">Hrs</TableCell>
              <TableCell align="right">Reg rate</TableCell>
              <TableCell align="right">OT rate</TableCell>
              <TableCell align="right">Total</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {displayRows.flatMap((r) => {
              const segs = Array.isArray(r.role_segments) ? r.role_segments : [];
              const multiRole = segs.length > 1;
              const parent = (
              <TableRow
                key={r.id}
                hover
                sx={{
                  "&:nth-of-type(even)": {
                    bgcolor: alpha(theme.palette.action.hover, 0.04),
                  },
                }}
              >
                <TableCell sx={{ whiteSpace: "nowrap" }}>{r.work_date}</TableCell>
                <TableCell
                  sx={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={r.worker_name}
                >
                  {r.worker_name}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap", minWidth: 168 }}>
                  <Typography variant="caption" sx={{ fontWeight: 700, display: "block" }}>
                    {formatRecordClassificationLabel(r)}
                  </Typography>
                  <Select
                    size="small"
                    variant="standard"
                    value={classificationSelectValue(r)}
                    onChange={(e) => {
                      const next = e.target.value;
                      if (next === classificationSelectValue(r)) return;
                      setClassEdit({ row: r, value: next, reason: "" });
                    }}
                    sx={{ fontSize: 12, maxWidth: 180 }}
                  >
                    {CLASSIFICATION_OVERRIDE_OPTIONS.map((opt) => (
                      <MenuItem key={opt.value || "default"} value={opt.value}>
                        {opt.label}
                      </MenuItem>
                    ))}
                  </Select>
                </TableCell>
                <TableCell
                  sx={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={r.role_label || undefined}
                >
                  {r.role_label || (segs.length === 1 ? segs[0].display_label : null) || "—"}
                  {multiRole ? (
                    <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>
                      ({segs.length})
                    </Typography>
                  ) : null}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{formatEasternTimeShort(r.clock_in_at)}</TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{formatEasternTimeShort(r.clock_out_at)}</TableCell>
                <TableCell
                  align="right"
                  sx={{
                    whiteSpace: "nowrap",
                    ...hoursCellSx(r.hours_level, theme),
                  }}
                  title={
                    r.hours_level !== "normal"
                      ? `${formatHoursDecimal(r.worker_period_hours)} total for ${r.worker_name} in this period`
                      : formatPayableComposition(r) || undefined
                  }
                >
                  {formatHoursDecimal(r.approved_hours)}
                  {formatPayableComposition(r) ? (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      display="block"
                      sx={{ fontWeight: 400, maxWidth: 160, whiteSpace: "normal" }}
                    >
                      {formatPayableComposition(r)}
                    </Typography>
                  ) : null}
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                  {formatPayrollRate(r.regular_rate)}
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                  {formatPayrollRate(r.ot_rate)}
                </TableCell>
                <TableCell
                  align="right"
                  sx={{
                    whiteSpace: "nowrap",
                    fontVariantNumeric: "tabular-nums",
                    fontWeight: 600,
                    ...hoursCellSx(r.hours_level, theme),
                  }}
                >
                  {formatPayrollMoney(r.row_total)}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  <Stack spacing={0.5} alignItems="flex-start">
                    <Chip size="small" label={statusLabel(r.status)} color={statusColor(r.status)} />
                    {r.has_open_break ? (
                      <Chip
                        size="small"
                        color="error"
                        variant="outlined"
                        label="Open break — not deducted"
                      />
                    ) : null}
                    {Array.isArray(r.segment_break_conflicts) && r.segment_break_conflicts.length ? (
                      <Chip
                        size="small"
                        color="warning"
                        variant="outlined"
                        label="Segment overlaps break"
                      />
                    ) : null}
                  </Stack>
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                  {canApproveRecord(r) ? (
                    <Tooltip title="Approve for payroll">
                      <IconButton
                        size="small"
                        color="success"
                        onClick={() => approveRecord(r)}
                        aria-label="Approve"
                      >
                        <CheckIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  ) : r.has_open_break && r.status !== "approved" && r.status !== "open" ? (
                    <Tooltip title="Close or remove the open break before approving">
                      <span>
                        <IconButton size="small" color="success" disabled aria-label="Approve blocked">
                          <CheckIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  ) : null}
                  <Tooltip title="Add completed break">
                    <IconButton
                      size="small"
                      onClick={() => openBreakAdd(r)}
                      aria-label="Add break"
                      disabled={r.status === "open" || !r.clock_out_at}
                    >
                      <AddIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Edit attendance day">
                    <IconButton size="small" onClick={() => openEdit(r)} aria-label="Edit">
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Delete attendance day">
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => setDeleteTarget(r)}
                      aria-label="Delete"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
              );
              const breaks = Array.isArray(r.breaks) ? r.breaks : [];
              const showChildRows = segs.length >= 1 || breaks.length >= 1;
              if (!showChildRows) return [parent];
              const segRows = segs.map((seg, idx) => (
                <TableRow
                  key={`${r.id}-seg-${seg.id || idx}`}
                  sx={{ bgcolor: alpha(theme.palette.info.main, 0.04) }}
                >
                  <TableCell />
                  <TableCell />
                  <TableCell />
                  <TableCell sx={{ pl: 2, whiteSpace: "nowrap", fontSize: "0.8125rem" }}>
                    <Typography variant="body2" component="span" sx={{ fontWeight: 600 }}>
                      {seg.display_label || "—"}
                    </Typography>
                    {seg.change_source ? (
                      <Typography variant="caption" color="text.secondary" display="block">
                        {String(seg.change_source).replace(/_/g, " ")}
                      </Typography>
                    ) : null}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap", fontSize: "0.8125rem" }}>
                    {formatEasternTimeShort(seg.started_at)}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap", fontSize: "0.8125rem" }}>
                    {seg.ended_at ? formatEasternTimeShort(seg.ended_at) : "Open"}
                  </TableCell>
                  <TableCell colSpan={5} />
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <Tooltip title="Edit role segment">
                      <IconButton
                        size="small"
                        onClick={() => openSegmentEdit(r, seg)}
                        aria-label="Edit role segment"
                        sx={{ opacity: 0.85 }}
                      >
                        <EditIcon sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete role segment">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => setSegmentDeleteTarget({ record: r, segment: seg })}
                        aria-label="Delete role segment"
                        sx={{ opacity: 0.85 }}
                      >
                        <DeleteIcon sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ));
              const breakRows = breaks.map((br, idx) => (
                <TableRow
                  key={`${r.id}-break-${br.id || idx}`}
                  sx={{ bgcolor: alpha(theme.palette.warning.main, br.status === "open" ? 0.12 : 0.05) }}
                >
                  <TableCell />
                  <TableCell />
                  <TableCell />
                  <TableCell sx={{ pl: 2, whiteSpace: "nowrap", fontSize: "0.8125rem" }}>
                    <Typography variant="body2" component="span" sx={{ fontWeight: 600 }}>
                      Break
                    </Typography>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {br.status === "open"
                        ? "Open — currently not deducted"
                        : br.deducted
                          ? "Completed — deducted from payable"
                          : br.status || "Break"}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap", fontSize: "0.8125rem" }}>
                    {formatEasternTimeShort(br.break_start_at)}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap", fontSize: "0.8125rem" }}>
                    {br.break_end_at ? formatEasternTimeShort(br.break_end_at) : "Open"}
                  </TableCell>
                  <TableCell
                    align="right"
                    sx={{ whiteSpace: "nowrap", fontSize: "0.8125rem", fontVariantNumeric: "tabular-nums" }}
                  >
                    {br.duration_seconds != null
                      ? formatHoursDecimal(br.duration_seconds / 3600)
                      : "—"}
                  </TableCell>
                  <TableCell colSpan={4} />
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <Tooltip title={br.status === "open" ? "Close open break" : "Edit break"}>
                      <IconButton
                        size="small"
                        onClick={() => openBreakEdit(r, br)}
                        aria-label="Edit break"
                        sx={{ opacity: 0.85 }}
                      >
                        <EditIcon sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete break">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => setBreakDeleteTarget({ record: r, breakRow: br })}
                        aria-label="Delete break"
                        sx={{ opacity: 0.85 }}
                      >
                        <DeleteIcon sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ));
              return [parent, ...segRows, ...breakRows];
            })}
            {!displayRows.length && !loading ? (
              <TableRow>
                <TableCell colSpan={12}>
                  <Typography color="text.secondary">No records for these filters.</Typography>
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>
      </Paper>

      <Dialog open={editorOpen} onClose={() => !saving && setEditorOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editorMode === "add" ? "Add time record" : "Edit time record"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {editorError ? (
              <Alert severity="error" onClose={() => setEditorError("")}>
                {editorError}
              </Alert>
            ) : null}
            <FormControl fullWidth size="small" disabled={editorMode === "edit"}>
              <InputLabel>Worker</InputLabel>
              <Select
                label="Worker"
                value={form.user_id}
                onChange={(e) => setForm((f) => ({ ...f, user_id: e.target.value }))}
              >
                {users.map((u) => (
                  <MenuItem key={u.id} value={String(u.id)}>
                    {u.first_name} {u.last_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {editorMode === "edit" && editingSegmentCount > 1 ? (
              <Alert severity="info">
                This day has {editingSegmentCount} role segments. Day-level category/role editing is
                disabled so multi-role history is preserved — use Edit on each role segment row
                instead. Clock in/out still adjusts only the first/last segment edges.
              </Alert>
            ) : (
              <>
                <FormControl fullWidth size="small">
                  <InputLabel>Category (optional)</InputLabel>
                  <Select
                    label="Category (optional)"
                    value={form.category_id}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        category_id: e.target.value,
                        role_id: "",
                      }))
                    }
                  >
                    <MenuItem value="">
                      <em>No role tag</em>
                    </MenuItem>
                    {selectionTree.map((cat) => (
                      <MenuItem key={cat.id} value={String(cat.id)}>
                        {cat.name || cat.category_name}
                      </MenuItem>
                    ))}
                    {form.category_id &&
                    !selectionTree.some((c) => String(c.id) === String(form.category_id)) ? (
                      <MenuItem value={String(form.category_id)}>
                        Current category (id {form.category_id})
                      </MenuItem>
                    ) : null}
                  </Select>
                </FormControl>
                <FormControl fullWidth size="small" disabled={!form.category_id}>
                  <InputLabel>Role (optional)</InputLabel>
                  <Select
                    label="Role (optional)"
                    value={form.role_id}
                    onChange={(e) => setForm((f) => ({ ...f, role_id: e.target.value }))}
                  >
                    <MenuItem value="">
                      <em>Select role</em>
                    </MenuItem>
                    {(
                      selectionTree.find((c) => String(c.id) === String(form.category_id))
                        ?.roles || []
                    ).map((role) => (
                      <MenuItem
                        key={role.role_id ?? role.id}
                        value={String(role.role_id ?? role.id)}
                      >
                        {displayRoleLabel(role)}
                      </MenuItem>
                    ))}
                    {form.role_id &&
                    !(
                      selectionTree
                        .find((c) => String(c.id) === String(form.category_id))
                        ?.roles || []
                    ).some(
                      (role) => String(role.role_id ?? role.id) === String(form.role_id),
                    ) ? (
                      <MenuItem value={String(form.role_id)}>
                        Current role (id {form.role_id})
                      </MenuItem>
                    ) : null}
                  </Select>
                </FormControl>
                <Typography variant="caption" color="text.secondary">
                  Tag the category and role for this shift. Leave blank if unknown — you can set it
                  later while editing. Works for open (still clocked-in) records too.
                </Typography>
              </>
            )}
            <PayrollDateTimeField
              label="Clock in"
              value={form.clock_in_at}
              onChange={(v) => setForm((f) => ({ ...f, clock_in_at: v }))}
            />
            <PayrollDateTimeField
              label="Clock out (optional)"
              value={form.clock_out_at}
              onChange={(v) => setForm((f) => ({ ...f, clock_out_at: v }))}
              clearable
            />
            <Typography variant="caption" color="text.secondary">
              Leave clock out blank to start an open shift — the employee can clock out later from the time clock.
            </Typography>
            <TextField
              fullWidth
              size="small"
              multiline
              minRows={2}
              label="Notes / correction"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditorOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveEditor} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete time record?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Remove {deleteTarget?.worker_name} on {deleteTarget?.work_date}? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDelete} disabled={saving}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={segmentEditorOpen}
        onClose={() => !saving && setSegmentEditorOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Edit role segment</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {segmentEditorError ? (
              <Alert severity="error" onClose={() => setSegmentEditorError("")}>
                {segmentEditorError}
              </Alert>
            ) : null}
            <Typography variant="body2" color="text.secondary">
              Updates only this role segment for {segmentTarget?.record?.worker_name}. Employee
              check-in/out for the day is not changed.
            </Typography>
            <FormControl fullWidth size="small">
              <InputLabel>Category</InputLabel>
              <Select
                label="Category"
                value={segmentForm.category_id}
                onChange={(e) =>
                  setSegmentForm((f) => ({
                    ...f,
                    category_id: e.target.value,
                    role_id: "",
                  }))
                }
              >
                {selectionTree.map((cat) => (
                  <MenuItem key={cat.id} value={String(cat.id)}>
                    {cat.name || cat.category_name}
                  </MenuItem>
                ))}
                {segmentForm.category_id &&
                !selectionTree.some((c) => String(c.id) === String(segmentForm.category_id)) ? (
                  <MenuItem value={String(segmentForm.category_id)}>
                    Current category (id {segmentForm.category_id})
                  </MenuItem>
                ) : null}
              </Select>
            </FormControl>
            <FormControl fullWidth size="small" disabled={!segmentForm.category_id}>
              <InputLabel>Role</InputLabel>
              <Select
                label="Role"
                value={segmentForm.role_id}
                onChange={(e) => setSegmentForm((f) => ({ ...f, role_id: e.target.value }))}
              >
                {(
                  selectionTree.find((c) => String(c.id) === String(segmentForm.category_id))
                    ?.roles || []
                ).map((role) => (
                  <MenuItem
                    key={role.role_id ?? role.id}
                    value={String(role.role_id ?? role.id)}
                  >
                    {displayRoleLabel(role)}
                  </MenuItem>
                ))}
                {segmentForm.role_id &&
                !(
                  selectionTree
                    .find((c) => String(c.id) === String(segmentForm.category_id))
                    ?.roles || []
                ).some(
                  (role) => String(role.role_id ?? role.id) === String(segmentForm.role_id),
                ) ? (
                  <MenuItem value={String(segmentForm.role_id)}>
                    Current role (id {segmentForm.role_id})
                  </MenuItem>
                ) : null}
              </Select>
            </FormControl>
            <PayrollDateTimeField
              label="Segment start"
              value={segmentForm.started_at}
              onChange={(v) => setSegmentForm((f) => ({ ...f, started_at: v }))}
            />
            <PayrollDateTimeField
              label="Segment end (optional / Open)"
              value={segmentForm.ended_at}
              onChange={(v) => setSegmentForm((f) => ({ ...f, ended_at: v }))}
              clearable
            />
            <Typography variant="caption" color="text.secondary">
              Leave end blank for an open/current segment. Gaps between segments are allowed and
              will warn; overlapping times are blocked. Adjacent segments are not auto-adjusted.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSegmentEditorOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={() => saveSegmentEditor()} disabled={saving}>
            {saving ? "Saving…" : "Save segment"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={!!breakConflict}
        onClose={() => !saving && setBreakConflict(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Segment overlaps unpaid break</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <Alert severity="warning">
              {breakConflict?.payload?.message ||
                "This role segment overlaps a completed break. Choose how to resolve it — breaks are never changed silently."}
            </Alert>
            {(breakConflict?.payload?.conflicts || []).map((c) => (
              <Typography key={`${c.break_id}-${c.segment_id}`} variant="body2" color="text.secondary">
                Break #{c.break_id}: {formatEasternTimeShort(c.break_start_at)} –{" "}
                {formatEasternTimeShort(c.break_end_at)} overlaps proposed segment (
                {Math.round((c.overlap_seconds || 0) / 60)} min).
              </Typography>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ flexWrap: "wrap", gap: 1, justifyContent: "flex-end" }}>
          <Button onClick={() => setBreakConflict(null)} disabled={saving}>
            Keep break — cancel
          </Button>
          {(breakConflict?.payload?.resolutions || [])
            .filter((r) => r.key !== "keep_break")
            .map((r) => (
              <Button
                key={r.key}
                variant={r.key === "delete_break" ? "outlined" : "contained"}
                color={r.key === "delete_break" ? "error" : "primary"}
                disabled={saving}
                onClick={() =>
                  saveSegmentEditor({
                    key: r.key,
                    break_id: r.break_id ?? breakConflict?.payload?.break_id_to_sync,
                  })
                }
              >
                {r.label}
              </Button>
            ))}
        </DialogActions>
      </Dialog>

      <Dialog
        open={breakEditorOpen}
        onClose={() => !saving && setBreakEditorOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {breakEditorMode === "add"
            ? "Add completed break"
            : breakEditorMode === "close"
              ? "Close open break"
              : "Edit break"}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {breakEditorError ? (
              <Alert severity="error" onClose={() => setBreakEditorError("")}>
                {breakEditorError}
              </Alert>
            ) : null}
            {breakEditorMode === "close" ? (
              <Alert severity="info">
                Open breaks are not deducted from payable hours. Enter the real end time — the system
                will not guess it.
              </Alert>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Completed breaks must fall inside check-in/check-out, end after start, and not overlap
                another completed break. Payable hours = elapsed − completed breaks.
              </Typography>
            )}
            {breakEditorMode !== "close" ? (
              <PayrollDateTimeField
                label="Break start"
                value={breakForm.break_start_at}
                onChange={(v) => setBreakForm((f) => ({ ...f, break_start_at: v }))}
              />
            ) : (
              <Typography variant="body2">
                Started {formatEasternTimeShort(breakTarget?.breakRow?.break_start_at)}
              </Typography>
            )}
            <PayrollDateTimeField
              label="Break end"
              value={breakForm.break_end_at}
              onChange={(v) => setBreakForm((f) => ({ ...f, break_end_at: v }))}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBreakEditorOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={saveBreakEditor} disabled={saving}>
            {saving
              ? "Saving…"
              : breakEditorMode === "close"
                ? "Close break"
                : breakEditorMode === "add"
                  ? "Add break"
                  : "Save break"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!breakDeleteTarget} onClose={() => setBreakDeleteTarget(null)}>
        <DialogTitle>Delete break?</DialogTitle>
        <DialogContent>
          <Typography>
            Delete this{" "}
            {breakDeleteTarget?.breakRow?.status === "open" ? "open" : "completed"} break
            {breakDeleteTarget?.record?.worker_name
              ? ` for ${breakDeleteTarget.record.worker_name}`
              : ""}
            ? Payable hours will be recomputed from remaining completed breaks. Frozen payout lines
            are not changed until Reopen for Correction / Refresh Hours.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBreakDeleteTarget(null)} disabled={saving}>
            Cancel
          </Button>
          <Button color="error" variant="contained" onClick={confirmBreakDelete} disabled={saving}>
            Delete break
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={!!segmentDeleteTarget}
        onClose={() => setSegmentDeleteTarget(null)}
      >
        <DialogTitle>Delete role segment?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Remove only{" "}
            <strong>{segmentDeleteTarget?.segment?.display_label || "this role segment"}</strong>
            {segmentDeleteTarget?.record?.worker_name
              ? ` for ${segmentDeleteTarget.record.worker_name}`
              : ""}
            ? The daily attendance record stays; other role segments are unchanged.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSegmentDeleteTarget(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={confirmSegmentDelete}
            disabled={saving}
          >
            Delete segment
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!classEdit} onClose={() => !classBusy && setClassEdit(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Payroll classification</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            {classEdit?.value
              ? CLASSIFICATION_OVERRIDE_OPTIONS.find((opt) => opt.value === classEdit.value)?.label
              : "Use employee default"}
            {" "}
            applies to this time record only. Hours stay as entered. An approved record must be
            approved again before it can enter payroll.
          </Typography>
          <TextField
            label="Reason (optional)"
            value={classEdit?.reason || ""}
            onChange={(e) =>
              setClassEdit((prev) => (prev ? { ...prev, reason: e.target.value } : prev))
            }
            fullWidth
            size="small"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setClassEdit(null)} disabled={classBusy}>
            Cancel
          </Button>
          <Button variant="contained" onClick={saveClassification} disabled={classBusy}>
            {classBusy ? "Saving…" : "Save classification"}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
