import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { batchOverrideFromDraft, emptyBatchOverrideDraft } from "../../shiftPlanner/plannerHelpers";

export default function EditBatchDialog({
  open,
  batch,
  employees,
  washerCount,
  dryerCount,
  allBagIds,
  onClose,
  onApply,
  onReset,
}) {
  const [draft, setDraft] = useState(() => emptyBatchOverrideDraft(batch));

  useEffect(() => {
    if (open && batch) setDraft(emptyBatchOverrideDraft(batch));
  }, [open, batch]);

  if (!batch) return null;

  const washers = Array.from({ length: washerCount || 4 }, (_, i) => `W${i + 1}`);
  const dryers = Array.from({ length: dryerCount || 4 }, (_, i) => `D${i + 1}`);
  const people = employees || [];

  const set = (patch) => setDraft((prev) => ({ ...prev, ...patch }));

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Edit Batch {batch.batch_number}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Override composition, machines, and labor for this batch. Invalid capacity or resource
          locks are rejected with a clear validation message.
        </Typography>
        <Stack spacing={1.5}>
          <TextField
            size="small"
            label="Bags included (comma-separated bag IDs)"
            value={draft.bag_ids_text}
            onChange={(e) => set({ bag_ids_text: e.target.value })}
            helperText={allBagIds?.length ? `Known bags: ${allBagIds.slice(0, 12).join(", ")}${allBagIds.length > 12 ? "…" : ""}` : ""}
            fullWidth
          />
          <Stack direction="row" flexWrap="wrap" gap={1.5}>
            <TextField size="small" type="number" label="Batch bag limit" value={draft.batch_size} onChange={(e) => set({ batch_size: e.target.value })} sx={{ width: 140 }} />
            <TextField size="small" type="number" label="Maximum pounds" value={draft.max_pounds} onChange={(e) => set({ max_pounds: e.target.value })} sx={{ width: 140 }} />
            <TextField size="small" type="number" label="Priority (lower sooner)" value={draft.priority} onChange={(e) => set({ priority: e.target.value })} sx={{ width: 160 }} />
            <TextField size="small" label="Planned start time" value={draft.planned_start_time} onChange={(e) => set({ planned_start_time: e.target.value })} sx={{ width: 150 }} placeholder="8:30 AM" />
          </Stack>
          <Stack direction="row" flexWrap="wrap" gap={1.5}>
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel>Washer</InputLabel>
              <Select label="Washer" value={draft.washer_id} onChange={(e) => set({ washer_id: e.target.value })}>
                <MenuItem value="">Auto</MenuItem>
                {washers.map((w) => <MenuItem key={w} value={w}>{w}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel>Dryer</InputLabel>
              <Select label="Dryer" value={draft.dryer_id} onChange={(e) => set({ dryer_id: e.target.value })}>
                <MenuItem value="">Auto</MenuItem>
                {dryers.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Washer person</InputLabel>
              <Select label="Washer person" value={draft.washer_person_id} onChange={(e) => set({ washer_person_id: e.target.value })}>
                <MenuItem value="">Auto</MenuItem>
                {people.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Transfer person</InputLabel>
              <Select label="Transfer person" value={draft.transfer_person_id} onChange={(e) => set({ transfer_person_id: e.target.value })}>
                <MenuItem value="">Auto</MenuItem>
                {people.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 170 }}>
              <InputLabel>Dryer-loading person</InputLabel>
              <Select label="Dryer-loading person" value={draft.dryer_load_person_id} onChange={(e) => set({ dryer_load_person_id: e.target.value })}>
                <MenuItem value="">Auto</MenuItem>
                {people.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Extra helper</InputLabel>
              <Select label="Extra helper" value={draft.extra_helper_id} onChange={(e) => set({ extra_helper_id: e.target.value })}>
                <MenuItem value="">None</MenuItem>
                {people.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
          <Stack direction="row" flexWrap="wrap" gap={1}>
            <FormControlLabel control={<Checkbox checked={draft.sorter_helps_washer} onChange={(e) => set({ sorter_helps_washer: e.target.checked })} />} label="Sorter helps washer" />
            <FormControlLabel control={<Checkbox checked={draft.folder_helps_washer} onChange={(e) => set({ folder_helps_washer: e.target.checked })} />} label="Folder helps washer" />
            <FormControlLabel control={<Checkbox checked={draft.sorting_paused} onChange={(e) => set({ sorting_paused: e.target.checked })} />} label="Pause sorting" />
            <FormControlLabel control={<Checkbox checked={draft.strict_resource_lock} onChange={(e) => set({ strict_resource_lock: e.target.checked })} />} label="Strict planned-start lock" />
          </Stack>
          <FormControl size="small" sx={{ maxWidth: 280 }}>
            <InputLabel>Apply scope</InputLabel>
            <Select label="Apply scope" value={draft.apply_scope} onChange={(e) => set({ apply_scope: e.target.value })}>
              <MenuItem value="this_batch_only">Apply to this batch only</MenuItem>
              <MenuItem value="from_this_batch">Apply from this batch onward</MenuItem>
            </Select>
          </FormControl>
          <Alert severity="info">
            Downstream batches recalculate after this change. Earlier unaffected batches stay locked.
            Use Undo on the results panel to restore the prior scenario.
          </Alert>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button color="warning" onClick={() => onReset(batch.batch_number)} sx={{ textTransform: "none", mr: "auto" }}>
          Reset override
        </Button>
        <Button onClick={onClose} sx={{ textTransform: "none" }}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => onApply(batchOverrideFromDraft(draft))}
          sx={{ textTransform: "none", fontWeight: 700 }}
        >
          Apply & rerun
        </Button>
      </DialogActions>
    </Dialog>
  );
}
