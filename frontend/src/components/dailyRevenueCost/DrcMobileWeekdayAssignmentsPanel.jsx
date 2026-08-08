import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import {
  getDrcMobileWeekdayAssignments,
  getTaUsers,
  putDrcMobileWeekdayAssignments,
} from "../../api";

const DAY_ORDER = [
  { weekday: 0, label: "Monday" },
  { weekday: 1, label: "Tuesday" },
  { weekday: 2, label: "Wednesday" },
  { weekday: 3, label: "Thursday" },
  { weekday: 4, label: "Friday" },
  { weekday: 5, label: "Saturday" },
  { weekday: 6, label: "Sunday" },
];

/**
 * Manager: weekday assignees per Revenue & Cost section (Phase 5E).
 * Day-first layout: Mon–Sun, five sections with employee selectors.
 */
export default function DrcMobileWeekdayAssignmentsPanel({ canEdit = false }) {
  const [sections, setSections] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [aRes, uRes] = await Promise.all([
        getDrcMobileWeekdayAssignments(),
        getTaUsers().catch(() => ({ data: [] })),
      ]);
      setSections(aRes?.data?.assignments || []);
      const list = Array.isArray(uRes?.data) ? uRes.data : uRes?.data?.users || [];
      setEmployees(
        list
          .filter((u) => u.active !== false)
          .map((u) => ({
            id: u.id,
            label: u.display_name || u.username || `User ${u.id}`,
          })),
      );
      setDirty(false);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load Revenue & Cost assignments");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setDay = (sectionKey, weekday, employeeId) => {
    setDirty(true);
    setSections((prev) =>
      prev.map((sec) =>
        sec.section_key !== sectionKey
          ? sec
          : {
              ...sec,
              days: (sec.days || []).map((d) =>
                d.weekday === weekday
                  ? { ...d, employee_id: employeeId === "" ? null : Number(employeeId) }
                  : d,
              ),
            },
      ),
    );
  };

  const save = async () => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const flat = [];
      for (const sec of sections) {
        for (const d of sec.days || []) {
          flat.push({
            section_key: sec.section_key,
            weekday: d.weekday,
            employee_id: d.employee_id,
          });
        }
      }
      await putDrcMobileWeekdayAssignments(flat);
      setMessage("Revenue & Cost section assignments saved.");
      setDirty(false);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save assignments");
    } finally {
      setSaving(false);
    }
  };

  const daysView = useMemo(
    () =>
      DAY_ORDER.map((day) => ({
        ...day,
        rows: (sections || []).map((sec) => {
          const row = (sec.days || []).find((d) => d.weekday === day.weekday) || {
            employee_id: null,
          };
          return {
            section_key: sec.section_key,
            section_label: sec.section_label || sec.section_key,
            employee_id: row.employee_id ?? null,
          };
        }),
      })),
    [sections],
  );

  return (
    <Box sx={{ mt: 3, p: 2, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
      <Typography fontWeight={800} sx={{ mb: 0.5, fontSize: "1.1rem" }}>
        Revenue & Cost Employee Assignments
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Choose who enters each section on the PIN Revenue & Cost floor. Mobile PIN Access controls
        whether an employee can open Revenue & Cost; these weekday assignments control which
        sections they see. Unassigned sections appear for nobody. Changing today&apos;s assignee is
        blocked while an open draft exists.
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {message ? (
        <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setMessage("")}>
          {message}
        </Alert>
      ) : null}
      {canEdit ? (
        <Button
          size="small"
          variant="contained"
          disabled={loading || saving || !dirty}
          onClick={save}
          sx={{ textTransform: "none", mb: 2 }}
        >
          {saving ? "Saving…" : "Save assignments"}
        </Button>
      ) : null}
      {loading && !sections.length ? (
        <Typography variant="body2" color="text.secondary">
          Loading assignments…
        </Typography>
      ) : (
        <Stack spacing={2.5}>
          {daysView.map((day) => (
            <Box key={day.weekday}>
              <Typography fontWeight={800} sx={{ mb: 1 }}>
                {day.label}
              </Typography>
              <Stack spacing={1}>
                {day.rows.map((row) => (
                  <FormControl
                    key={`${day.weekday}-${row.section_key}`}
                    size="small"
                    fullWidth
                    disabled={!canEdit || loading || saving}
                  >
                    <InputLabel>{row.section_label}</InputLabel>
                    <Select
                      label={row.section_label}
                      value={row.employee_id ?? ""}
                      displayEmpty
                      renderValue={(selected) => {
                        if (selected === "" || selected == null) return "Unassigned";
                        const emp = employees.find((e) => Number(e.id) === Number(selected));
                        return emp?.label || `User ${selected}`;
                      }}
                      onChange={(e) => setDay(row.section_key, day.weekday, e.target.value)}
                    >
                      <MenuItem value="">
                        <em>Unassigned</em>
                      </MenuItem>
                      {employees.map((emp) => (
                        <MenuItem key={emp.id} value={emp.id}>
                          {emp.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                ))}
              </Stack>
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}
