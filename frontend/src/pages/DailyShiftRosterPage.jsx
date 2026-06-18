import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import {
  createDailyShiftRosterEntry,
  deleteDailyShiftRosterEntry,
  getDailyShiftRoster,
  importDailyShiftRosterFromPayroll,
  updateDailyShiftRosterEntry,
} from "../api";
import { yesterdayRange, todayRange } from "../utils/foldingDateRange";
import { fmtLaborValue } from "../utils/employeeProductivityHelpers";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import DailyShiftRosterCard from "../components/shift/DailyShiftRosterCard";
import DailyShiftRosterEntryDialog from "../components/shift/DailyShiftRosterEntryDialog";

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET Date" },
];

function draftKey(entry) {
  return `${entry?.employee_name || ""}|${entry?.start_time || ""}`;
}

function resolvePreset(isoDate) {
  const today = todayRange().start;
  const yesterday = yesterdayRange().start;
  if (!isoDate || isoDate === today) return "today";
  if (isoDate === yesterday) return "yesterday";
  return "custom";
}

export default function DailyShiftRosterPage() {
  const [datePreset, setDatePreset] = useState("today");
  const [customDate, setCustomDate] = useState(todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(todayRange().start);
  const [data, setData] = useState(null);
  const [draftEntries, setDraftEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [editingDraft, setEditingDraft] = useState(false);
  const [saving, setSaving] = useState(false);
  const [roleSavingKey, setRoleSavingKey] = useState("");

  const load = useCallback(async (dateEt) => {
    if (!dateEt) return;
    setLoading(true);
    setError("");
    try {
      const res = await getDailyShiftRoster({ date_et: dateEt });
      setData(res.data);
      setActiveDateEt(dateEt);
      if (!res.data?.has_roster && res.data?.payroll_prefill?.length) {
        setDraftEntries(res.data.payroll_prefill);
      } else {
        setDraftEntries([]);
      }
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load daily shift roster");
      setData(null);
      setDraftEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(activeDateEt);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const applyDate = (isoDate) => {
    if (!isoDate) return;
    setActiveDateEt(isoDate);
    load(isoDate);
  };

  const handleDatePreset = (_, value) => {
    if (!value) return;
    setDatePreset(value);
    if (value === "today") applyDate(todayRange().start);
    else if (value === "yesterday") applyDate(yesterdayRange().start);
    else if (value === "custom") setCustomDate(activeDateEt);
  };

  const openCreate = () => {
    setEditingEntry(null);
    setEditingDraft(false);
    setDialogOpen(true);
  };

  const openEdit = (entry, { draft = false } = {}) => {
    setEditingEntry(entry);
    setEditingDraft(draft);
    setDialogOpen(true);
  };

  const handleSave = async (form) => {
    setSaving(true);
    setError("");
    try {
      if (editingEntry?.id) {
        await updateDailyShiftRosterEntry(editingEntry.id, form);
      } else {
        await createDailyShiftRosterEntry({ ...form, date_et: activeDateEt });
        if (editingDraft) {
          const key = draftKey(editingEntry);
          setDraftEntries((prev) => prev.filter((e) => draftKey(e) !== key));
        }
      }
      setDialogOpen(false);
      setEditingEntry(null);
      setEditingDraft(false);
      await load(activeDateEt);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save roster entry");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (entry) => {
    if (!entry?.id) return;
    const ok = window.confirm(`Remove ${entry.employee_name} from the roster?`);
    if (!ok) return;
    setError("");
    try {
      await deleteDailyShiftRosterEntry(entry.id);
      await load(activeDateEt);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to delete roster entry");
    }
  };

  const handleRoleChange = async (entry, role) => {
    if (!entry || role === entry.role) return;
    const key = draftKey(entry);
    if (!entry.id) {
      setDraftEntries((prev) =>
        prev.map((e) => (draftKey(e) === key ? { ...e, role } : e)),
      );
      return;
    }
    setRoleSavingKey(String(entry.id));
    setError("");
    try {
      await updateDailyShiftRosterEntry(entry.id, { role });
      await load(activeDateEt);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to update role");
    } finally {
      setRoleSavingKey("");
    }
  };

  const handleImportFromPayroll = async () => {
    setImporting(true);
    setError("");
    try {
      const res = await importDailyShiftRosterFromPayroll({ date_et: activeDateEt });
      setData(res.data);
      setDraftEntries([]);
      setActiveDateEt(activeDateEt);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to import from payroll");
    } finally {
      setImporting(false);
    }
  };

  const entries = data?.entries || [];
  const summary = data?.summary || {};
  const hasRoster = Boolean(data?.has_roster);
  const displayEntries = hasRoster ? entries : draftEntries;
  const infoMessage = data?.message || null;

  return (
    <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 1, sm: 2 }, py: { xs: 1.5, sm: 2.5 } }}>
      <Paper
        elevation={0}
        sx={{
          borderRadius: 2.5,
          overflow: "hidden",
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
          bgcolor: "#ffffff",
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        <Box
          sx={{
            px: { xs: 1.5, sm: 2 },
            py: { xs: 1.25, sm: 1.5 },
            bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
            color: "#fff",
          }}
        >
          <Typography variant="h5" fontWeight={800} sx={{ fontSize: { xs: "1.15rem", sm: "1.35rem" } }}>
            Daily Shift Roster
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.35, opacity: 0.92 }}>
            Record who worked today — ET {activeDateEt}
          </Typography>
        </Box>

        <Box sx={{ p: { xs: 1.25, sm: 2 } }}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            justifyContent="space-between"
            alignItems={{ xs: "stretch", sm: "center" }}
            spacing={1}
            sx={{ mb: 2 }}
          >
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, alignItems: "center" }}>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={datePreset}
                onChange={handleDatePreset}
                sx={{ flexWrap: "wrap" }}
              >
                {DATE_PRESETS.map((p) => (
                  <ToggleButton key={p.id} value={p.id} sx={{ textTransform: "none", fontWeight: 600 }}>
                    {p.label}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
              {datePreset === "custom" ? (
                <>
                  <TextField
                    type="date"
                    size="small"
                    label="Custom ET Date"
                    value={customDate || ""}
                    onChange={(e) => setCustomDate(e.target.value)}
                    InputLabelProps={{ shrink: true }}
                    sx={{ width: 170 }}
                  />
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() => customDate && applyDate(customDate)}
                    disabled={loading || !customDate}
                  >
                    Apply
                  </Button>
                </>
              ) : null}
              {loading ? <CircularProgress size={18} /> : null}
            </Box>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignSelf: { xs: "stretch", sm: "auto" } }}>
              <Button
                variant="outlined"
                startIcon={<DownloadOutlinedIcon />}
                onClick={handleImportFromPayroll}
                disabled={loading || importing}
                sx={{ fontWeight: 700 }}
              >
                {importing ? "Importing…" : "Import from Payroll"}
              </Button>
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={openCreate}
                sx={{ fontWeight: 700 }}
              >
                Add Employee
              </Button>
            </Stack>
          </Stack>

          {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}

          {infoMessage ? (
            <Alert severity={hasRoster ? "info" : "warning"} sx={{ mb: 2 }}>
              {infoMessage}
            </Alert>
          ) : null}

          {hasRoster ? (
            <Box
              sx={{
                mb: 2,
                p: 1.5,
                borderRadius: 2,
                bgcolor: VEEWASH_DASHBOARD.snapshotBg,
                border: "1px solid",
                borderColor: VEEWASH_DASHBOARD.snapshotBorder,
                display: "grid",
                gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)" },
                gap: 1.25,
              }}
            >
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  Employees
                </Typography>
                <Typography variant="h6" fontWeight={800}>
                  {summary.employee_count ?? entries.length}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  Total Hours
                </Typography>
                <Typography variant="h6" fontWeight={800}>
                  {fmtLaborValue(summary.total_hours, { digits: 2 })}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  Total Cost
                </Typography>
                <Typography variant="h6" fontWeight={800} sx={{ color: VEEWASH_DASHBOARD.primaryBlueDark }}>
                  {fmtLaborValue(summary.total_cost, { currency: true })}
                </Typography>
              </Box>
            </Box>
          ) : null}

          <Stack spacing={1.5}>
            {displayEntries.map((entry) => (
              <DailyShiftRosterCard
                key={entry.id || draftKey(entry)}
                entry={entry}
                draft={!hasRoster}
                onEdit={(e) => openEdit(e, { draft: !hasRoster })}
                onDelete={handleDelete}
                onRoleChange={handleRoleChange}
                roleSaving={roleSavingKey === String(entry.id)}
              />
            ))}
          </Stack>
        </Box>
      </Paper>

      <DailyShiftRosterEntryDialog
        open={dialogOpen}
        onClose={() => {
          if (!saving) {
            setDialogOpen(false);
            setEditingEntry(null);
            setEditingDraft(false);
          }
        }}
        onSave={handleSave}
        initialEntry={editingEntry}
        saving={saving}
      />
    </Box>
  );
}
