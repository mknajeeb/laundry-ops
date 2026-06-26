import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import PrintIcon from "@mui/icons-material/Print";
import {
  createUserHrTimelineEntry,
  deleteUserHrTimelineEntry,
  getTaUserHrProfile,
  getUserHrTimeline,
  previewUserHrTimelineEmail,
} from "../../api";
import ContractorPrintPreviewDialog from "../../contractorForms/ContractorPrintPreviewDialog";
import { openPrintWindow } from "../../contractorForms/contractorPrint";
import "../../contractorForms/contractorPrint.css";
import {
  HR_DISCIPLINE_EMAIL_TEMPLATES,
  HR_TIMELINE_CATEGORIES,
  HR_TIMELINE_ENTRY_TYPES,
  entryTypeLabel,
} from "../../hr/hrTimelineConstants";
import {
  buildOfferLetterTimelineDescription,
  buildOfferLetterEmail,
  defaultOfferLetterFields,
  formatOfferCompensation,
  offerLetterDocumentTitle,
} from "../../hr/offerLetter";
import { buildW2PrefillFromHrProfile } from "../../w2Forms/w2Prefill";
import OfferLetterPrintDocument from "./OfferLetterPrintDocument";
import { VEEWASH_BRAND } from "../../theme/veewashBrand";

function chipColor(entryType) {
  if (entryType === "coaching") return "info";
  if (entryType === "warning") return "warning";
  if (entryType === "separation_note") return "error";
  if (entryType === "recognition") return "success";
  if (entryType === "offer_letter") return "primary";
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
  const [hrPrefill, setHrPrefill] = useState(null);
  const [offerOpen, setOfferOpen] = useState(false);
  const [offerPreviewOpen, setOfferPreviewOpen] = useState(false);
  const [offerDraft, setOfferDraft] = useState(null);
  const offerPrintRef = useRef(null);

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

  useEffect(() => {
    if (!userId) {
      setHrPrefill(null);
      return;
    }
    let cancelled = false;
    getTaUserHrProfile(userId)
      .then((res) => {
        if (!cancelled) setHrPrefill(buildW2PrefillFromHrProfile(res.data));
      })
      .catch(() => {
        if (!cancelled) setHrPrefill(null);
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const openOfferLetter = () => {
    setOfferDraft(
      defaultOfferLetterFields({
        prefill: hrPrefill,
        workerName,
        workerEmail,
        managerName,
        workerLane,
      }),
    );
    setOfferOpen(true);
  };

  const offerFields = useMemo(() => {
    if (!offerDraft) return null;
    return {
      ...offerDraft,
      compensation: offerDraft.compensation || formatOfferCompensation(offerDraft.hourly_rate),
    };
  }, [offerDraft]);

  const offerEmail = useMemo(
    () => (offerFields ? buildOfferLetterEmail(offerFields) : null),
    [offerFields],
  );

  const offerPrintTitle = useMemo(
    () => offerLetterDocumentTitle(offerFields?.is_contractor),
    [offerFields?.is_contractor],
  );

  const printOfferLetter = () => {
    openPrintWindow(offerPrintRef?.current, {
      pageSize: "letter portrait",
      title: offerPrintTitle,
    });
  };

  const copyOfferEmail = async () => {
    if (!offerEmail) return;
    try {
      await navigator.clipboard.writeText(`Subject: ${offerEmail.subject}\n\n${offerEmail.body}`);
      setInfo("Offer email copied to clipboard.");
    } catch {
      setError("Could not copy — copy manually from the email draft.");
    }
  };

  const openOfferMailto = () => {
    if (!offerEmail) return;
    const subject = encodeURIComponent(offerEmail.subject || "");
    const body = encodeURIComponent(offerEmail.body || "");
    const to = encodeURIComponent(
      offerFields?.candidate_email || workerEmail || "",
    );
    window.location.href = `mailto:${to}?subject=${subject}&body=${body}`;
  };

  const logOfferLetter = async (markSent = false) => {
    if (!offerFields || !offerEmail) return;
    setBusy(true);
    setError("");
    try {
      await createUserHrTimelineEntry(userId, {
        entry_type: "offer_letter",
        category: "General",
        entry_date: offerFields.offer_date || new Date().toISOString().slice(0, 10),
        description: buildOfferLetterTimelineDescription(offerFields),
        email_subject: offerEmail.subject,
        email_body: offerEmail.body,
        email_sent: markSent,
      });
      setInfo(markSent ? "Offer letter logged — mark email as sent." : "Offer letter logged to HR Timeline.");
      setOfferOpen(false);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not log offer letter");
    } finally {
      setBusy(false);
    }
  };

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
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button size="small" startIcon={<PrintIcon />} variant="outlined" onClick={openOfferLetter}>
                Offer letter
              </Button>
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

      <Dialog open={offerOpen} onClose={() => setOfferOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{offerPrintTitle || "Offer letter"}</DialogTitle>
        <DialogContent>
          {offerDraft ? (
            <Stack spacing={1.5} sx={{ mt: 1 }}>
              <TextField
                size="small"
                label="Candidate name"
                value={offerDraft.candidate_name}
                onChange={(e) => setOfferDraft((d) => ({ ...d, candidate_name: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Candidate email"
                type="email"
                value={offerDraft.candidate_email}
                onChange={(e) => setOfferDraft((d) => ({ ...d, candidate_email: e.target.value }))}
                fullWidth
                helperText="Used when opening the offer in your email app."
              />
              <TextField
                size="small"
                label="Address (optional)"
                value={offerDraft.candidate_address}
                onChange={(e) => setOfferDraft((d) => ({ ...d, candidate_address: e.target.value }))}
                fullWidth
                multiline
                minRows={2}
              />
              <TextField
                size="small"
                label="Position title"
                value={offerDraft.position}
                onChange={(e) => setOfferDraft((d) => ({ ...d, position: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Position details (optional)"
                value={offerDraft.position_details}
                onChange={(e) => setOfferDraft((d) => ({ ...d, position_details: e.target.value }))}
                fullWidth
                multiline
                minRows={3}
                helperText="Duties, department, or other role details shown on the letter."
              />
              <Stack direction="row" gap={1} flexWrap="wrap">
                <TextField
                  size="small"
                  type="date"
                  label="Start date"
                  value={offerDraft.start_date}
                  onChange={(e) => setOfferDraft((d) => ({ ...d, start_date: e.target.value }))}
                  InputLabelProps={{ shrink: true }}
                  sx={{ flex: 1, minWidth: 140 }}
                />
                <TextField
                  size="small"
                  type="date"
                  label="Offer date"
                  value={offerDraft.offer_date}
                  onChange={(e) => setOfferDraft((d) => ({ ...d, offer_date: e.target.value }))}
                  InputLabelProps={{ shrink: true }}
                  sx={{ flex: 1, minWidth: 140 }}
                />
              </Stack>
              <TextField
                size="small"
                label={offerDraft.is_contractor ? "Service rate" : "Hourly rate"}
                value={offerDraft.hourly_rate}
                onChange={(e) =>
                  setOfferDraft((d) => ({
                    ...d,
                    hourly_rate: e.target.value,
                    compensation: formatOfferCompensation(e.target.value),
                  }))
                }
                fullWidth
                helperText={offerDraft.compensation || "Enter rate to show on letter"}
              />
              <TextField
                size="small"
                label="Work location"
                value={offerDraft.work_location}
                onChange={(e) => setOfferDraft((d) => ({ ...d, work_location: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Schedule"
                value={offerDraft.schedule}
                onChange={(e) => setOfferDraft((d) => ({ ...d, schedule: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Pay frequency"
                value={offerDraft.pay_frequency}
                onChange={(e) => setOfferDraft((d) => ({ ...d, pay_frequency: e.target.value }))}
                fullWidth
              />
              <Stack direction="row" gap={1} flexWrap="wrap">
                <TextField
                  size="small"
                  label="Manager name"
                  value={offerDraft.manager_name}
                  onChange={(e) => setOfferDraft((d) => ({ ...d, manager_name: e.target.value }))}
                  sx={{ flex: 1, minWidth: 160 }}
                />
                <TextField
                  size="small"
                  label="Manager title"
                  value={offerDraft.manager_title}
                  onChange={(e) => setOfferDraft((d) => ({ ...d, manager_title: e.target.value }))}
                  sx={{ flex: 1, minWidth: 160 }}
                />
              </Stack>
              <TextField
                size="small"
                type="date"
                label="Response deadline (optional)"
                value={offerDraft.response_deadline}
                onChange={(e) => setOfferDraft((d) => ({ ...d, response_deadline: e.target.value }))}
                InputLabelProps={{ shrink: true }}
                fullWidth
              />
              <TextField
                size="small"
                label="Additional terms (optional)"
                value={offerDraft.additional_terms}
                onChange={(e) => setOfferDraft((d) => ({ ...d, additional_terms: e.target.value }))}
                fullWidth
                multiline
                minRows={2}
              />
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions sx={{ flexWrap: "wrap", gap: 0.5 }}>
          <Button onClick={() => setOfferOpen(false)}>Cancel</Button>
          <Button startIcon={<ContentCopyIcon />} onClick={copyOfferEmail} disabled={!offerEmail}>
            Copy email
          </Button>
          <Button startIcon={<EmailIcon />} onClick={openOfferMailto} disabled={!offerEmail}>
            Open in email
          </Button>
          <Button onClick={() => setOfferPreviewOpen(true)} disabled={!offerFields}>
            Preview
          </Button>
          <Button variant="outlined" onClick={() => logOfferLetter(false)} disabled={busy || !offerFields?.position}>
            Log to timeline
          </Button>
          <Button
            variant="outlined"
            onClick={() => logOfferLetter(true)}
            disabled={busy || !offerFields?.position}
          >
            Log + mark email sent
          </Button>
          <Button
            variant="contained"
            startIcon={<PrintIcon />}
            onClick={printOfferLetter}
            disabled={!offerFields?.position}
          >
            Print
          </Button>
        </DialogActions>
      </Dialog>

      <ContractorPrintPreviewDialog
        open={offerPreviewOpen}
        onClose={() => setOfferPreviewOpen(false)}
        title={offerPrintTitle}
        printRef={offerPrintRef}
        onCopyEmail={copyOfferEmail}
        onOpenEmail={openOfferMailto}
      />

      <Box
        aria-hidden
        sx={{
          position: "fixed",
          left: -9999,
          top: 0,
          width: "7.5in",
          pointerEvents: "none",
        }}
      >
        <div ref={offerPrintRef}>
          {offerFields ? (
            <OfferLetterPrintDocument fields={offerFields} prefill={hrPrefill || {}} />
          ) : null}
        </div>
      </Box>
    </Stack>
  );
}
