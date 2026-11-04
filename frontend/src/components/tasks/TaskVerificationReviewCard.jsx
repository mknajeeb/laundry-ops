import { useState } from "react";
import { Box, Button, Collapse, Stack, TextField, Typography } from "@mui/material";
import ActivityRemarks from "./ActivityRemarks";
import InstructionHint from "./InstructionHint";
import { useI18n } from "../../i18n/I18nContext";
import { localizedConfigured, localizedInstruction, taskStatusLabel } from "./taskEmployeeI18n";
import { formatDashboardTime } from "./taskDashboardFormat";
import { OPS_MOBILE } from "../../opsMobile";
import { CompletionDetails } from "../../opsMobile/TaskCompletionInputs";

function clock(value) {
  const text = formatDashboardTime(value);
  return text === "—" ? null : text;
}

/**
 * One supervisor card for a shared assignment.
 * Checklist records stay separate and can be rejected individually.
 */
export default function TaskVerificationReviewCard({
  card,
  busy = false,
  notice = "",
  error = "",
  onApproveAll,
  onNeedsRedo,
  onRejectItem,
}) {
  const [openPeople, setOpenPeople] = useState(false);
  const [openChecklist, setOpenChecklist] = useState(false);
  const [redo, setRedo] = useState(false);
  const [reason, setReason] = useState("");
  const [itemRejectId, setItemRejectId] = useState(null);
  const [itemReason, setItemReason] = useState("");
  const { t, locale } = useI18n();
  const [supervisorRemark, setSupervisorRemark] = useState("");
  const assigned = (card?.assigned_employees || []).join(" + ");
  const activityName = localizedConfigured(
    { name: card.role_label, name_es: card.name_es },
    locale,
    "name",
    "name_es",
  );
  const overall = card.overall_status ? taskStatusLabel(t, card.overall_status) : card.overall_label;

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: `1px solid ${OPS_MOBILE.border}`,
        bgcolor: "#fff",
      }}
    >
      <Stack direction="row" alignItems="center" spacing={0.5}>
        <Typography sx={{ fontWeight: 900, letterSpacing: 0.2 }}>{activityName || card.role_label}</Typography>
        <InstructionHint text={localizedInstruction(card, locale)} label={t("tasks.pin.instructions")} />
      </Stack>
      {assigned ? (
        <Typography variant="body2" color="text.secondary">
          {t("tasks.pin.assigned", { names: assigned })}
        </Typography>
      ) : null}
      {card.timing_label ? (
        <Typography variant="body2" color="text.secondary">
          {t("tasks.pin.scheduled", { time: card.timing_label })}
        </Typography>
      ) : null}
      <Typography variant="body2" sx={{ mt: 0.75, fontWeight: 800 }}>
        {t("tasks.pin.overall", { status: overall })}
      </Typography>

      <Button
        size="small"
        onClick={() => setOpenPeople((v) => !v)}
        sx={{ textTransform: "none", px: 0, fontWeight: 800 }}
      >
        {openPeople ? t("tasks.pin.hideParticipation") : t("tasks.pin.participation")}
      </Button>
      <Collapse in={openPeople}>
        <Stack spacing={0.5} sx={{ mb: 1 }}>
          {(card.participation || []).map((person) => (
            <Box key={person.employee_id || person.employee_name}>
              <Typography variant="body2" sx={{ fontWeight: 800 }}>
                {person.employee_name} — {person.participation_label}
              </Typography>
              {person.participation_status === "not_started" ? (
                <Typography variant="caption" color="text.secondary">
                  {t("tasks.pin.notStarted")}
                </Typography>
              ) : (
                <Typography variant="caption" color="text.secondary" display="block">
                  {t("tasks.pin.started", { time: clock(person.started_at) || "—" })}
                  {person.participation_status === "finished"
                    ? ` · ${t("tasks.pin.finished", { time: clock(person.finished_at) || "—" })}`
                    : ""}
                </Typography>
              )}
            </Box>
          ))}
        </Stack>
      </Collapse>

      {(card.checklist || []).length ? (
        <>
          <Button
            size="small"
            onClick={() => setOpenChecklist((v) => !v)}
            sx={{ textTransform: "none", px: 0, fontWeight: 800 }}
          >
            {openChecklist ? t("tasks.pin.hideChecklist") : t("tasks.pin.sharedChecklist")}
          </Button>
          <Collapse in={openChecklist}>
            <Stack spacing={0.75} sx={{ mb: 1 }}>
              {card.checklist.map((item) => (
                <Box key={item.task_code || item.task_label}>
                  <Stack direction="row" alignItems="center" spacing={0.5}>
                  <Typography variant="body2">
                    {localizedConfigured(
                      { task_name: item.task_label || item.task_name, task_name_es: item.task_name_es },
                      locale,
                      "task_name",
                      "task_name_es",
                    ) || item.task_label}{" "}
                    —{" "}
                    {item.needs_correction
                      ? t("tasks.pin.needsCorrection")
                      : item.checked_off
                        ? t("tasks.pin.checkedOff")
                        : t("tasks.pin.notCheckedOff")}
                  </Typography>
                  <InstructionHint text={localizedInstruction(item, locale)} label={t("tasks.pin.itemInstructions")} />
                  </Stack>
                  {item.section_label ? (
                    <Typography variant="caption" sx={{ fontWeight: 800 }} display="block">
                      {localizedConfigured(item, locale, "section_label", "section_label_es") || item.section_label}
                    </Typography>
                  ) : null}
                  <Typography variant="caption" color="text.secondary" display="block">
                    {t("tasks.pin.responsible", {
                      name:
                        item.responsibility_label &&
                        item.responsibility_label !== "Anyone on Team" &&
                        item.responsibility_label !== "Any assigned employee"
                          ? item.responsibility_label
                          : t("tasks.pin.anyone"),
                    })}
                    {item.completed_by_name ? ` · ${t("tasks.pin.checkedOffBy", { name: item.completed_by_name })}` : ""}
                  </Typography>
                  <CompletionDetails completionInput={item.completion_input} schema={item.input_schema} />
                  {(item.records || []).map((rec) => (
                    <Box key={rec.activity_id || `${item.task_code}-${rec.employee_id}`} sx={{ pl: 1 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {clock(rec.checked_off_at)
                          ? t("tasks.pin.checkedOffAt", { time: clock(rec.checked_off_at) })
                          : item.checked_off
                            ? t("tasks.pin.checkedOff")
                            : t("tasks.pin.notCheckedOff")}
                        {rec.employee_name ? ` · ${t("tasks.pin.by", { name: rec.employee_name })}` : ""}
                      </Typography>
                      {rec.rejection_reason ? (
                        <Typography variant="caption" color="error" display="block">
                          {rec.rejection_reason}
                        </Typography>
                      ) : null}
                      {rec.activity_id && String(rec.status) === "pending_approval" ? (
                        <Button
                          size="small"
                          color="warning"
                          onClick={() => {
                            setItemRejectId(rec.activity_id);
                            setItemReason("");
                            setRedo(false);
                          }}
                          sx={{ textTransform: "none", px: 0 }}
                        >
                          {t("tasks.pin.rejectThisItem")}
                        </Button>
                      ) : null}
                    </Box>
                  ))}
                </Box>
              ))}
            </Stack>
          </Collapse>
        </>
      ) : null}

      {(card.checklist_sections || []).map((section) => (
        <Stack key={section.section_label} direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
          <Typography variant="caption" sx={{ fontWeight: 800 }}>
            {section.section_label}: {section.status ? taskStatusLabel(t, section.status) : section.status_label}
          </Typography>
          {section.pending_activity_ids?.length ? (
            <Button
              size="small"
              disabled={busy}
              onClick={() =>
                onApproveAll?.(section.pending_activity_ids, { remark: supervisorRemark, section: true })
              }
              sx={{ textTransform: "none", fontWeight: 800 }}
            >
              {t("tasks.pin.verifySection")}
            </Button>
          ) : null}
        </Stack>
      ))}
      <ActivityRemarks remarks={card.remarks || []} items={card.checklist || []} readOnly />

      {card.block_reason ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {card.block_reason}
        </Typography>
      ) : null}
      {notice ? (
        <Typography variant="body2" color="success.main" sx={{ mb: 1 }}>
          {notice}
        </Typography>
      ) : null}
      {error ? (
        <Typography variant="body2" color="error" sx={{ mb: 1 }}>
          {error}
        </Typography>
      ) : null}

      {card.can_approve_all ? (
        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            size="small"
            label={t("tasks.pin.verificationNote")}
            value={supervisorRemark}
            onChange={(e) => setSupervisorRemark(e.target.value)}
          />
          <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant="contained"
            disabled={busy}
            onClick={() => onApproveAll?.(card.pending_activity_ids || [], { remark: supervisorRemark })}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            {t("tasks.pin.approveAll")}
          </Button>
          <Button
            size="small"
            color="warning"
            variant="outlined"
            disabled={busy}
            onClick={() => {
              setRedo(true);
              setItemRejectId(null);
            }}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            {t("tasks.pin.needsRedoAction")}
          </Button>
          </Stack>
        </Stack>
      ) : null}

      {redo ? (
        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            size="small"
            multiline
            minRows={2}
            label={t("tasks.pin.reason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("tasks.pin.requiredShort")}
          />
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              color="warning"
              variant="contained"
              disabled={busy || reason.trim().length < 3}
              onClick={() => onNeedsRedo?.(card.pending_activity_ids || [], reason.trim())}
              sx={{ textTransform: "none", fontWeight: 800 }}
            >
              {t("tasks.pin.submitRedo")}
            </Button>
            <Button size="small" onClick={() => setRedo(false)} sx={{ textTransform: "none" }}>
              {t("tasks.pin.cancel")}
            </Button>
          </Stack>
        </Stack>
      ) : null}

      {itemRejectId ? (
        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            size="small"
            multiline
            minRows={2}
            label={t("tasks.pin.itemReason")}
            value={itemReason}
            onChange={(e) => setItemReason(e.target.value)}
          />
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              color="warning"
              variant="contained"
              disabled={busy || itemReason.trim().length < 3}
              onClick={() => onRejectItem?.(itemRejectId, itemReason.trim())}
              sx={{ textTransform: "none", fontWeight: 800 }}
            >
              {t("tasks.pin.rejectItem")}
            </Button>
            <Button size="small" onClick={() => setItemRejectId(null)} sx={{ textTransform: "none" }}>
              {t("tasks.pin.cancel")}
            </Button>
          </Stack>
        </Stack>
      ) : null}
    </Box>
  );
}
