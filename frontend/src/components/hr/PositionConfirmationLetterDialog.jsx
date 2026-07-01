import { useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  TextField,
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import EmailIcon from "@mui/icons-material/Email";
import PrintIcon from "@mui/icons-material/Print";
import { createUserHrTimelineEntry } from "../../api";
import ContractorPrintPreviewDialog from "../../contractorForms/ContractorPrintPreviewDialog";
import { getPrintDocumentPdfBlob, openPrintWindow } from "../../contractorForms/contractorPrint";
import {
  POSITION_CONFIRMATION_DOCUMENT_TITLE,
  buildPositionConfirmationEmail,
  buildPositionConfirmationEmailFilename,
  buildPositionConfirmationTimelineDescription,
  defaultPositionConfirmationFields,
} from "../../hr/positionConfirmationLetter";
import PositionConfirmationPrintDocument from "./PositionConfirmationPrintDocument";

export default function PositionConfirmationLetterDialog({
  open,
  onClose,
  userId,
  workerName = "",
  workerEmail = "",
  managerName = "",
  hrPrefill = null,
  onLogged,
  setError,
  setInfo,
  busy,
  setBusy,
}) {
  const [draft, setDraft] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const printRef = useRef(null);

  useEffect(() => {
    if (!open) {
      setDraft(null);
      setPreviewOpen(false);
      return;
    }
    setDraft(
      defaultPositionConfirmationFields({
        prefill: hrPrefill,
        workerName,
        workerEmail,
        managerName,
      }),
    );
  }, [open, hrPrefill, workerName, workerEmail, managerName]);

  const fields = useMemo(() => draft, [draft]);

  const email = useMemo(
    () => (fields ? buildPositionConfirmationEmail(fields) : null),
    [fields],
  );

  const emailWithAttachment = useMemo(
    () => (fields ? buildPositionConfirmationEmail(fields, { includeAttachmentNote: true }) : null),
    [fields],
  );

  const printLetter = () => {
    openPrintWindow(printRef?.current, {
      pageSize: "letter portrait",
      title: POSITION_CONFIRMATION_DOCUMENT_TITLE,
    });
  };

  const copyEmail = async () => {
    if (!email) return;
    try {
      await navigator.clipboard.writeText(`Subject: ${email.subject}\n\n${email.body}`);
      setInfo("Confirmation email copied to clipboard.");
    } catch {
      setError("Could not copy — copy manually from the email draft.");
    }
  };

  const openMailto = (emailContent = email) => {
    if (!emailContent) return;
    const subject = encodeURIComponent(emailContent.subject || "");
    const body = encodeURIComponent(emailContent.body || "");
    const to = encodeURIComponent(fields?.employee_email || workerEmail || "");
    window.location.href = `mailto:${to}?subject=${subject}&body=${body}`;
  };

  const sendEmailWithPdf = async () => {
    if (!fields || !emailWithAttachment || !printRef.current) return;
    setBusy(true);
    setError("");
    try {
      const filename = buildPositionConfirmationEmailFilename(fields);
      const blob = await getPrintDocumentPdfBlob(printRef.current, {
        pageSize: "letter portrait",
        title: POSITION_CONFIRMATION_DOCUMENT_TITLE,
      });
      if (!blob) {
        throw new Error("Could not generate position confirmation PDF");
      }
      const file = new File([blob], filename, { type: "application/pdf" });
      const sharePayload = {
        title: emailWithAttachment.subject,
        text: emailWithAttachment.body,
        files: [file],
      };
      if (navigator.share && navigator.canShare?.(sharePayload)) {
        await navigator.share(sharePayload);
        setInfo("Email opened with the confirmation letter PDF attached.");
        return;
      }

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      const attachNote = `\n\nPlease attach the downloaded file: ${filename}`;
      openMailto({
        subject: emailWithAttachment.subject,
        body: `${emailWithAttachment.body}${attachNote}`,
      });
      setInfo("PDF downloaded — attach it in your email draft.");
    } catch (e) {
      if (e?.name !== "AbortError") {
        setError(e?.message || "Could not prepare confirmation email with PDF");
      }
    } finally {
      setBusy(false);
    }
  };

  const logLetter = async (markSent = false) => {
    if (!fields || !email) return;
    setBusy(true);
    setError("");
    try {
      await createUserHrTimelineEntry(userId, {
        entry_type: "position_confirmation_letter",
        category: "General",
        entry_date: fields.letter_date || new Date().toISOString().slice(0, 10),
        description: buildPositionConfirmationTimelineDescription(fields),
        email_subject: email.subject,
        email_body: email.body,
        email_sent: markSent,
      });
      setInfo(
        markSent
          ? "Position confirmation logged — mark email as sent."
          : "Position confirmation logged to HR Timeline.",
      );
      onClose();
      await onLogged?.();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not log position confirmation letter");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
        <DialogTitle>{POSITION_CONFIRMATION_DOCUMENT_TITLE}</DialogTitle>
        <DialogContent>
          {draft ? (
            <Stack spacing={1.5} sx={{ mt: 1 }}>
              <TextField
                size="small"
                label="Employee name"
                value={draft.employee_name}
                onChange={(e) => setDraft((d) => ({ ...d, employee_name: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Employee email"
                type="email"
                value={draft.employee_email}
                onChange={(e) => setDraft((d) => ({ ...d, employee_email: e.target.value }))}
                fullWidth
                helperText="Used when opening the letter in your email app."
              />
              <TextField
                size="small"
                label="Address (optional)"
                value={draft.employee_address}
                onChange={(e) => setDraft((d) => ({ ...d, employee_address: e.target.value }))}
                fullWidth
                multiline
                minRows={2}
              />
              <TextField
                size="small"
                label="Position title"
                value={draft.position}
                onChange={(e) => setDraft((d) => ({ ...d, position: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Position details (optional)"
                value={draft.position_details}
                onChange={(e) => setDraft((d) => ({ ...d, position_details: e.target.value }))}
                fullWidth
                multiline
                minRows={2}
                helperText="Department, duties, or other role details shown on the letter."
              />
              <Stack direction="row" gap={1} flexWrap="wrap">
                <TextField
                  size="small"
                  type="date"
                  label="Letter date"
                  value={draft.letter_date}
                  onChange={(e) => setDraft((d) => ({ ...d, letter_date: e.target.value }))}
                  InputLabelProps={{ shrink: true }}
                  sx={{ flex: 1, minWidth: 140 }}
                />
                <TextField
                  size="small"
                  type="date"
                  label="Effective date of confirmation"
                  value={draft.effective_date}
                  onChange={(e) => setDraft((d) => ({ ...d, effective_date: e.target.value }))}
                  InputLabelProps={{ shrink: true }}
                  sx={{ flex: 1, minWidth: 140 }}
                />
              </Stack>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={!!draft.include_probation_dates}
                    onChange={(e) => {
                      const checked = e.target.checked;
                      setDraft((d) => {
                        const hire =
                          hrPrefill?.hire_date || hrPrefill?.start_date || "";
                        return {
                          ...d,
                          include_probation_dates: checked,
                          probation_start_date:
                            checked && !d.probation_start_date && hire
                              ? String(hire).slice(0, 10)
                              : d.probation_start_date,
                        };
                      });
                    }}
                  />
                }
                label="Include probation dates on letter"
              />
              {draft.include_probation_dates ? (
                <Stack direction="row" gap={1} flexWrap="wrap">
                  <TextField
                    size="small"
                    type="date"
                    label="Probation start date"
                    value={draft.probation_start_date}
                    onChange={(e) =>
                      setDraft((d) => ({ ...d, probation_start_date: e.target.value }))
                    }
                    InputLabelProps={{ shrink: true }}
                    sx={{ flex: 1, minWidth: 140 }}
                  />
                  <TextField
                    size="small"
                    type="date"
                    label="Probation end date"
                    value={draft.probation_end_date}
                    onChange={(e) => setDraft((d) => ({ ...d, probation_end_date: e.target.value }))}
                    InputLabelProps={{ shrink: true }}
                    sx={{ flex: 1, minWidth: 140 }}
                  />
                </Stack>
              ) : null}
              <TextField
                size="small"
                label="Probation period summary"
                value={draft.probation_summary}
                onChange={(e) => setDraft((d) => ({ ...d, probation_summary: e.target.value }))}
                fullWidth
                multiline
                minRows={3}
                helperText="Editable paragraph about performance during probation."
              />
              <TextField
                size="small"
                label="Custom content (optional)"
                value={draft.custom_content}
                onChange={(e) => setDraft((d) => ({ ...d, custom_content: e.target.value }))}
                fullWidth
                multiline
                minRows={3}
                helperText="Extra paragraphs inserted before the standard closing terms."
              />
              <TextField
                size="small"
                label="Employment status"
                value={draft.employment_status}
                onChange={(e) => setDraft((d) => ({ ...d, employment_status: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Work location"
                value={draft.work_location}
                onChange={(e) => setDraft((d) => ({ ...d, work_location: e.target.value }))}
                fullWidth
              />
              <TextField
                size="small"
                label="Reporting to"
                value={draft.reporting_to}
                onChange={(e) => setDraft((d) => ({ ...d, reporting_to: e.target.value }))}
                fullWidth
              />
              <Stack direction="row" gap={1} flexWrap="wrap">
                <TextField
                  size="small"
                  label="Signatory name"
                  value={draft.signatory_name}
                  onChange={(e) => setDraft((d) => ({ ...d, signatory_name: e.target.value }))}
                  sx={{ flex: 1, minWidth: 160 }}
                />
                <TextField
                  size="small"
                  label="Signatory title"
                  value={draft.signatory_title}
                  onChange={(e) => setDraft((d) => ({ ...d, signatory_title: e.target.value }))}
                  sx={{ flex: 1, minWidth: 160 }}
                />
              </Stack>
              <TextField
                size="small"
                label="Additional terms (optional)"
                value={draft.additional_terms}
                onChange={(e) => setDraft((d) => ({ ...d, additional_terms: e.target.value }))}
                fullWidth
                multiline
                minRows={2}
              />
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions sx={{ flexWrap: "wrap", gap: 0.5 }}>
          <Button onClick={onClose}>Cancel</Button>
          <Button startIcon={<ContentCopyIcon />} onClick={copyEmail} disabled={!email}>
            Copy email
          </Button>
          <Button
            startIcon={<EmailIcon />}
            onClick={sendEmailWithPdf}
            disabled={busy || !emailWithAttachment || !fields?.position}
          >
            Send email (PDF)
          </Button>
          <Button onClick={() => setPreviewOpen(true)} disabled={!fields}>
            Preview
          </Button>
          <Button variant="outlined" onClick={() => logLetter(false)} disabled={busy || !fields?.position}>
            Log to timeline
          </Button>
          <Button variant="outlined" onClick={() => logLetter(true)} disabled={busy || !fields?.position}>
            Log + mark email sent
          </Button>
          <Button
            variant="contained"
            startIcon={<PrintIcon />}
            onClick={printLetter}
            disabled={!fields?.position}
          >
            Print
          </Button>
        </DialogActions>
      </Dialog>

      <ContractorPrintPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title={POSITION_CONFIRMATION_DOCUMENT_TITLE}
        printRef={printRef}
        onCopyEmail={copyEmail}
        onOpenEmail={sendEmailWithPdf}
        openEmailLabel="Send email (PDF)"
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
        <div ref={printRef}>
          {fields ? (
            <PositionConfirmationPrintDocument fields={fields} prefill={hrPrefill || {}} />
          ) : null}
        </div>
      </Box>
    </>
  );
}
