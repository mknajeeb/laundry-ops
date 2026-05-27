import { useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
} from "@mui/material";
import { applyFoldingScoringOverride } from "../../api";

export default function FoldingScoringOverrideMenu({ bagId, onDone, disabled }) {
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState("include");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    try {
      setBusy(true);
      await applyFoldingScoringOverride(bagId, { action, note: note.trim() || undefined });
      setOpen(false);
      setNote("");
      if (onDone) await onDone();
    } catch (e) {
      window.alert(e?.response?.data?.error || "Scoring override failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Stack direction="row" spacing={0.5} flexWrap="wrap">
        <Button size="small" disabled={disabled} onClick={() => { setAction("include"); setOpen(true); }}>
          Include in scoring
        </Button>
        <Button size="small" disabled={disabled} onClick={() => { setAction("exclude"); setOpen(true); }}>
          Exclude from scoring
        </Button>
        <Button size="small" disabled={disabled} onClick={() => { setAction("clear"); setOpen(true); }}>
          Clear override
        </Button>
      </Stack>
      <Dialog open={open} onClose={() => !busy && setOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>
          {action === "clear"
            ? "Clear scoring override"
            : `${action === "include" ? "Include in gaming/scoring" : "Exclude from gaming/scoring"}`}
        </DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            size="small"
            label="Note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
          <Button variant="contained" onClick={run} disabled={busy}>
            {busy ? "Saving…" : "Confirm"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
