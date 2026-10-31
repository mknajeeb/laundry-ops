import { useState } from "react";
import { Box, Button, Collapse, Stack, TextField, Typography } from "@mui/material";
import { formatDashboardTime } from "./taskDashboardFormat";
import { OPS_MOBILE } from "../../opsMobile";

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
  const assigned = (card?.assigned_employees || []).join(" + ");

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: `1px solid ${OPS_MOBILE.border}`,
        bgcolor: "#fff",
      }}
    >
      <Typography sx={{ fontWeight: 900, letterSpacing: 0.2 }}>{card.role_label}</Typography>
      {assigned ? (
        <Typography variant="body2" color="text.secondary">
          Assigned: {assigned}
        </Typography>
      ) : null}
      {card.timing_label ? (
        <Typography variant="body2" color="text.secondary">
          Scheduled: {card.timing_label}
        </Typography>
      ) : null}
      <Typography variant="body2" sx={{ mt: 0.75, fontWeight: 800 }}>
        Overall status: {card.overall_label}
      </Typography>

      <Button
        size="small"
        onClick={() => setOpenPeople((v) => !v)}
        sx={{ textTransform: "none", px: 0, fontWeight: 800 }}
      >
        {openPeople ? "Hide participation" : "Participation"}
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
                  Not started
                </Typography>
              ) : (
                <Typography variant="caption" color="text.secondary" display="block">
                  {clock(person.started_at) ? `Started: ${clock(person.started_at)}` : "Started: —"}
                  {person.participation_status === "finished"
                    ? ` · Finished: ${clock(person.finished_at) || "—"}`
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
            {openChecklist ? "Hide shared checklist" : "Shared checklist"}
          </Button>
          <Collapse in={openChecklist}>
            <Stack spacing={0.75} sx={{ mb: 1 }}>
              {card.checklist.map((item) => (
                <Box key={item.task_code || item.task_label}>
                  <Typography variant="body2">
                    {item.task_label} —{" "}
                    {item.needs_correction
                      ? "Needs correction"
                      : item.checked_off
                        ? "Checked off"
                        : "Not checked off"}
                  </Typography>
                  {(item.records || []).map((rec) => (
                    <Box key={rec.activity_id || `${item.task_code}-${rec.employee_id}`} sx={{ pl: 1 }}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {clock(rec.checked_off_at) ? `Checked off: ${clock(rec.checked_off_at)}` : "Not checked off"}
                        {rec.employee_name ? ` · By: ${rec.employee_name}` : ""}
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
                          Reject this item
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
        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <Button
            size="small"
            variant="contained"
            disabled={busy}
            onClick={() => onApproveAll?.(card.pending_activity_ids || [])}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            Approve All
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
            Needs Redo
          </Button>
        </Stack>
      ) : null}

      {redo ? (
        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            size="small"
            multiline
            minRows={2}
            label="Reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Required"
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
              Submit redo
            </Button>
            <Button size="small" onClick={() => setRedo(false)} sx={{ textTransform: "none" }}>
              Cancel
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
            label="Reason for this item"
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
              Reject item
            </Button>
            <Button size="small" onClick={() => setItemRejectId(null)} sx={{ textTransform: "none" }}>
              Cancel
            </Button>
          </Stack>
        </Stack>
      ) : null}
    </Box>
  );
}
