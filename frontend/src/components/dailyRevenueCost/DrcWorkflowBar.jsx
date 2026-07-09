import { useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Stack,
  TextField,
} from "@mui/material";
import LockIcon from "@mui/icons-material/Lock";
import SendIcon from "@mui/icons-material/Send";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import ReplayIcon from "@mui/icons-material/Replay";
import {
  drcWorkflowActionLabel,
  drcWorkflowConfirmMessage,
  drcWorkflowSupportsNotes,
  getDrcWorkflowActions,
} from "../../utils/dailyRevenueCostHelpers";

const ACTION_ICONS = {
  lock: LockIcon,
  submit: SendIcon,
  approve: CheckCircleIcon,
  reject: CancelIcon,
  reopen: ReplayIcon,
};

const ACTION_COLORS = {
  lock: "warning",
  submit: "primary",
  approve: "success",
  reject: "error",
  reopen: "primary",
};

export default function DrcWorkflowBar({
  entryDate,
  entryStatus,
  hasEntry,
  busy = false,
  onWorkflow,
}) {
  const [pendingAction, setPendingAction] = useState(null);
  const [notes, setNotes] = useState("");

  const actions = getDrcWorkflowActions(entryStatus, hasEntry);
  if (!actions.length) return null;

  const closeDialog = () => {
    setPendingAction(null);
    setNotes("");
  };

  const confirmAction = async () => {
    if (!pendingAction) return;
    const payload = { action: pendingAction };
    if (drcWorkflowSupportsNotes(pendingAction) && notes.trim()) {
      payload.notes = notes.trim();
    }
    try {
      await onWorkflow(payload);
      closeDialog();
    } catch {
      // parent surfaces error toast
    }
  };

  return (
    <>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {actions.map((action) => {
          const Icon = ACTION_ICONS[action];
          return (
            <Button
              key={action}
              size="small"
              variant={action === "approve" ? "contained" : "outlined"}
              color={ACTION_COLORS[action] || "primary"}
              startIcon={Icon ? <Icon fontSize="small" /> : null}
              disabled={busy}
              onClick={() => setPendingAction(action)}
            >
              {drcWorkflowActionLabel(action)}
            </Button>
          );
        })}
      </Stack>

      <Dialog open={Boolean(pendingAction)} onClose={busy ? undefined : closeDialog} fullWidth maxWidth="xs">
        <DialogTitle>{drcWorkflowActionLabel(pendingAction)} entry?</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: drcWorkflowSupportsNotes(pendingAction) ? 2 : 0 }}>
            {drcWorkflowConfirmMessage(pendingAction, entryDate)}
          </DialogContentText>
          {drcWorkflowSupportsNotes(pendingAction) ? (
            <TextField
              label={pendingAction === "reject" ? "Rejection reason (optional)" : "Reopen note (optional)"}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              fullWidth
              multiline
              minRows={2}
              disabled={busy}
            />
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color={ACTION_COLORS[pendingAction] || "primary"}
            onClick={confirmAction}
            disabled={busy}
          >
            {busy ? "Working…" : drcWorkflowActionLabel(pendingAction)}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
