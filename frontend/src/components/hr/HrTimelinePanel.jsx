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
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import EmailIcon from "@mui/icons-material/Email";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import {
  createUserHrTimelineEntry,
  deleteUserHrTimelineEntry,
  getUserHrTimeline,
  previewUserHrTimelineEmail,
} from "../api";
import {
  HR_DISCIPLINE_EMAIL_TEMPLATES,
  HR_TIMELINE_CATEGORIES,
  HR_TIMELINE_ENTRY_TYPES,
  entryTypeLabel,
} from "../hr/hrTimelineConstants";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

function chipColor(entryType) {
  if (entryType === "coaching") return "info";
  if (entryType === "warning") return "warning";
  if (entryType === "separation_note") return "error";
  if (entryType === "recognition") return "success";
  if (entryType === "management_note") return "default";
  return "default";
}

function formatDate(val) {
  if (!val) return "—";
  const s = String(val).slice(0, 10);
  return s || "—";
}

export default function HrTimelinePanel({
  userId,
  workerName = "",
  workerLane = "employee_w2",
  workerEmail = "",
  managerName = "",
  canEdit = false,
}) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [manualDraft, setManualDraft] = useState({
    entry_type: "management_note",
    category: "General",
    entry_date: new Date().toISOString().slice(0, 10),
    description: "",
  });
  const [emailDraft, setEmailDraft] = useState({
    template_id: "coaching_late_arrival",
    issue_summary: "",
    examples: "",
    scheduled_start: "",
    actual_time: "",
    effective_date: "",
    location: "",
  });
  const [emailPreview, setEmailPreview] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    try {
      const res = await getUserHrTimeline(userId);
      setItems(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load HR Timeline");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  const templateFields = useMemo(
    () => ({
      worker_name: workerName || "[Name]",
      manager_name: managerName || "[Manager Name]",
      manager_title: "[Title]",
      date: new Date().toLocaleDateString(),
      issue_summary: emailDraft.issue_summary || "[brief factual summary]",
      examples: emailDraft.examples || "[examples]",
      scheduled_start: emailDraft.scheduled_start || "[scheduled start time]",
      actual_time: emailDraft.actual_time || "[actual time]",
      effective_date: emailDraft.effective_date || "[date / immediately]",
      location: emailDraft.location || "[location]",
      contact_name: "[contact name]",
    }),
    [workerName, managerName, emailDraft],
  );

  const refreshPreview = async () => {
    if (!userId) return;
    try {
      const res = await previewUserHrTimelineEmail(userId, {
        template_id: emailDraft.template_id,
        worker_lane: workerLane,
        fields: templateFields,
      });
      setEmailPreview(res.data);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Preview failed");
    }
  };

  useEffect(() => {
    if (!emailOpen) return;
    refreshPreview();
  }, [emailOpen, emailDraft.template_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveManual = async () => {
    setBusy(true);
    setError("");
    try {
      await createUserHrTimelineEntry(userId, manualDraft);
      setInfo("Timeline entry saved.");
      setManualOpen(false);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const sendDisciplineEmail = async (markSent) => {
    setBusy(true);
    setError("");
    try {
      const res = await createUserHrTimelineEntry(userId, {
        template_id: emailDraft.template_id,
        worker_lane: workerLane,
        fields: templateFields,
        description: emailPreview?.body || "",
        email_sent: markSent,
      });
      setInfo(markSent ? "Timeline entry created — mark email as sent." : "Timeline entry created.");
      setEmailOpen(false);
      setEmailPreview(null);
      await load();
      return res.data;
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not create entry");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const copyEmail = async () => {
    const body = emailPreview?.body || "";
    const subject = emailPreview?.subject || "";
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
      setInfo("Email copied to clipboard.");
    } catch {
      setError("Could not copy — copy manually from preview.");
    }
  };

  const openMailto = () => {
    const subject = encodeURIComponent(emailPreview?.subject || "");
    const body = encodeURIComponent(emailPreview?.body || "");
    const to = workerEmail ? encodeURIComponent(workerEmail) : "";
    window.location.href = `mailto:${to}?subject=${subject}&body=${body}`;
  };

  const removeEntry = async (entryId) => {
    if (!window.confirm("Delete this timeline entry?")) return;
    setBusy(true);
    try {
      await deleteUserHrTimelineEntry(userId, entryId);
      setInfo("Entry deleted.");
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>{info}</Alert>
      ) : null}

      <Paper
        variant="outlined"
        sx={{ p: 2, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
          <Box>
            <Typography variant="subtitle1" fontWeight={700}>
              HR Timeline
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Internal manager log — email discipline + timeline entry. No worker signatures.
            </Typography>
          </Box>
          {canEdit ? (
            <Stack direction="row" spacing={1}>
              <Button size="small" startIcon={<EmailIcon />} onClick={() => setEmailOpen(true)}>
                Send discipline email
              </Button>
              <Button size="small" startIcon={<AddIcon />} variant="outlined" onClick={() => setManualOpen(true)}>
                Add entry
              </Button>
            </Stack>
          ) : null}
        </Stack>
      </Paper>

      {loading ? (
        <Typography color="text.secondary">Loading timeline…</Typography>
      ) : items.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No HR Timeline entries yet.
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Category</TableCell>
              <TableCell>Manager</TableCell>
              <TableCell>Summary</TableCell>
              <TableCell width={48} />
            </TableRow>
          </TableHead>
          <TableBody>
            {items.map((row) => (
              <TableRow key={row.id} hover>
                <TableCell>{formatDate(row.entry_date)}</TableCell>
                <TableCell>
                  <Chip size="small" label={entryTypeLabel(row.entry_type)} color={chipColor(row.entry_type)} />
                </TableCell>
                <TableCell>{row.category}</TableCell>
                <TableCell>{row.manager_name_snapshot || "—"}</TableCell>
                <TableCell sx={{ maxWidth: 360 }}>
                  <Typography variant="body2" noWrap title={row.description}>
                    {row.email_subject || row.description?.slice(0, 120) || "—"}
                  </Typography>
                  {row.email_sent_at ? (
                    <Typography variant="caption" color="success.main">Email logged</Typography>
                  ) : null}
                </TableCell>
                <TableCell>
                  {canEdit ? (
                    <Button size="small" color="inherit" onClick={() => removeEntry(row.id)} disabled={busy}>
                      <DeleteOutlineIcon fontSize="small" />
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={manualOpen} onClose={() => setManualOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add HR Timeline entry</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <FormControl size="small" fullWidth>
              <InputLabel>Type</InputLabel>
              <Select
                label="Type"
                value={manualDraft.entry_type}
                onChange={(e) => setManualDraft((d) => ({ ...d, entry_type: e.target.value }))}
              >
                {HR_TIMELINE_ENTRY_TYPES.map((t) => (
                  <MenuItem key={t.id} value={t.id}>{t.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Category</InputLabel>
              <Select
                label="Category"
                value={manualDraft.category}
                onChange={(e) => setManualDraft((d) => ({ ...d, category: e.target.value }))}
              >
                {HR_TIMELINE_CATEGORIES.map((c) => (
                  <MenuItem key={c} value={c}>{c}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              type="date"
              label="Date"
              value={manualDraft.entry_date}
              onChange={(e) => setManualDraft((d) => ({ ...d, entry_date: e.target.value }))}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              size="small"
              label="Description"
              value={manualDraft.description}
              onChange={(e) => setManualDraft((d) => ({ ...d, description: e.target.value }))}
              multiline
              minRows={4}
              fullWidth
              helperText="Use Management Note for internal observations that are not formal coaching or warning."
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setManualOpen(false)}>Cancel</Button>
          <Button onClick={saveManual} disabled={busy || !manualDraft.description.trim()} variant="contained">
            Save entry
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={emailOpen} onClose={() => setEmailOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Discipline email + timeline entry</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <FormControl size="small" fullWidth>
              <InputLabel>Template</InputLabel>
              <Select
                label="Template"
                value={emailDraft.template_id}
                onChange={(e) => setEmailDraft((d) => ({ ...d, template_id: e.target.value }))}
              >
                {HR_DISCIPLINE_EMAIL_TEMPLATES.map((t) => (
                  <MenuItem key={t.id} value={t.id}>{t.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label="Issue / facts (brief)"
              value={emailDraft.issue_summary}
              onChange={(e) => setEmailDraft((d) => ({ ...d, issue_summary: e.target.value }))}
              fullWidth
              multiline
              minRows={2}
            />
            <TextField
              size="small"
              label="Examples / dates"
              value={emailDraft.examples}
              onChange={(e) => setEmailDraft((d) => ({ ...d, examples: e.target.value }))}
              fullWidth
              multiline
              minRows={2}
            />
            {emailDraft.template_id === "coaching_late_arrival" ? (
              <Stack direction="row" gap={1} flexWrap="wrap">
                <TextField
                  size="small"
                  label="Scheduled start"
                  value={emailDraft.scheduled_start}
                  onChange={(e) => setEmailDraft((d) => ({ ...d, scheduled_start: e.target.value }))}
                />
                <TextField
                  size="small"
                  label="Actual arrival"
                  value={emailDraft.actual_time}
                  onChange={(e) => setEmailDraft((d) => ({ ...d, actual_time: e.target.value }))}
                />
                <TextField
                  size="small"
                  label="Location"
                  value={emailDraft.location}
                  onChange={(e) => setEmailDraft((d) => ({ ...d, location: e.target.value }))}
                />
              </Stack>
            ) : null}
            <Button size="small" onClick={refreshPreview}>Refresh preview</Button>
            {emailPreview ? (
              <Paper variant="outlined" sx={{ p: 1.5, bgcolor: "action.hover" }}>
                <Typography variant="subtitle2" fontWeight={600}>{emailPreview.subject}</Typography>
                <Typography variant="body2" sx={{ mt: 1, whiteSpace: "pre-wrap" }}>
                  {emailPreview.body}
                </Typography>
              </Paper>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button startIcon={<ContentCopyIcon />} onClick={copyEmail} disabled={!emailPreview}>
            Copy
          </Button>
          <Button startIcon={<EmailIcon />} onClick={openMailto} disabled={!emailPreview}>
            Open in email
          </Button>
          <Button onClick={() => setEmailOpen(false)}>Cancel</Button>
          <Button
            variant="outlined"
            onClick={() => sendDisciplineEmail(false)}
            disabled={busy || !emailPreview}
          >
            Log entry only
          </Button>
          <Button
            variant="contained"
            onClick={() => sendDisciplineEmail(true)}
            disabled={busy || !emailPreview}
          >
            Log + mark email sent
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
