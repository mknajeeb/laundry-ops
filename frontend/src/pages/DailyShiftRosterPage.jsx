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
import {
  createDailyShiftRosterEntry,
  deleteDailyShiftRosterEntry,
  getDailyShiftRoster,
  updateDailyShiftRosterEntry,
} from "../../api";
import { yesterdayRange, todayRange } from "../../utils/foldingDateRange";
import { fmtLaborValue } from "../../utils/employeeProductivityHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import DailyShiftRosterCard from "./DailyShiftRosterCard";
import DailyShiftRosterEntryDialog from "./DailyShiftRosterEntryDialog";

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET Date" },
];

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (dateEt) => {
    if (!dateEt) return;
    setLoading(true);
    setError("");
    try {
      const res = await getDailyShiftRoster({ date_et: dateEt });
      setData(res.data);
      setActiveDateEt(dateEt);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load daily shift roster");
      setData(null);
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
    setDialogOpen(true);
  };

  const openEdit = (entry) => {
    setEditingEntry(entry);
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
      }
      setDialogOpen(false);
      setEditingEntry(null);
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

  const entries = data?.entries || [];
  const summary = data?.summary || {};
  const hasRoster = Boolean(data?.has_roster);

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
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={openCreate}
              sx={{ alignSelf: { xs: "stretch", sm: "auto" }, fontWeight: 700 }}
            >
              Add Employee
            </Button>
          </Stack>

          {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}

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
          ) : (
            <Alert severity="info" sx={{ mb: 2 }}>
              No labor roster recorded for this date.
            </Alert>
          )}

          <Stack spacing={1.5}>
            {entries.map((entry) => (
              <DailyShiftRosterCard
                key={entry.id}
                entry={entry}
                onEdit={openEdit}
                onDelete={handleDelete}
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
          }
        }}
        onSave={handleSave}
        initialEntry={editingEntry}
        saving={saving}
      />
    </Box>
  );
}
