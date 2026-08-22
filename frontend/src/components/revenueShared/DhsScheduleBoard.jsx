import { useMemo, useState } from "react";
import {
  Box,
  Button,
  Collapse,
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
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { fmtMoney } from "./revenueFormat";

function friendlyDate(iso) {
  try {
    const [y, m, d] = String(iso).split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return iso || "—";
  }
}

function OccurrenceCard({ row, onOpen, onSkip }) {
  const lbs = row.volume_lbs;
  const rev = row.revenue;
  const meta =
    lbs != null || rev != null
      ? [lbs != null ? `${Number(lbs).toLocaleString()} lb` : null, rev != null ? fmtMoney(rev) : null]
          .filter(Boolean)
          .join(" · ")
      : null;
  return (
    <Box
      sx={{
        display: "flex",
        gap: 1,
        py: 1.1,
        px: 1.15,
        bgcolor: "#fff",
        borderRadius: 2,
        boxShadow: "0 1px 0 rgba(15,23,42,0.06)",
      }}
    >
      <Box
        sx={{
          width: 4,
          borderRadius: 99,
          bgcolor:
            row.lifecycle === "overdue" ? "#b91c1c" : row.lifecycle === "due" ? "#007a91" : "#94a3b8",
          flexShrink: 0,
        }}
      />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={0.75} alignItems="baseline">
          <Typography sx={{ fontWeight: 900, fontSize: 16, color: "#0f172a", lineHeight: 1.15 }}>
            {row.name}
          </Typography>
          {row.is_manual ? (
            <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#b45309" }}>Manual</Typography>
          ) : null}
        </Stack>
        <Typography sx={{ fontSize: 13, color: "#475569", mt: 0.25 }}>
          Pickup {friendlyDate(row.scheduled_pickup_date)}
        </Typography>
        <Typography sx={{ fontSize: 13, color: "#475569" }}>
          Delivery {friendlyDate(row.scheduled_delivery_date)}
        </Typography>
        {meta ? (
          <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#0f766e", mt: 0.25 }}>{meta}</Typography>
        ) : null}
        <Typography
          sx={{
            fontSize: 12,
            fontWeight: 800,
            mt: 0.35,
            color: row.lifecycle === "overdue" ? "#b91c1c" : "#334155",
          }}
        >
          {row.lifecycle_label || row.lifecycle}
        </Typography>
      </Box>
      <Stack spacing={0.5} sx={{ flexShrink: 0 }}>
        <Button
          size="small"
          variant="contained"
          onClick={() => onOpen(row)}
          sx={{ textTransform: "none", minHeight: 40, px: 1.5, bgcolor: "#007a91", fontWeight: 800 }}
        >
          Open
        </Button>
        <Button size="small" variant="text" onClick={() => onSkip(row)} sx={{ textTransform: "none", minHeight: 32, color: "#64748b" }}>
          Skip
        </Button>
      </Stack>
    </Box>
  );
}

function LifecycleGroup({ title, groups, color, defaultOpen, onOpen, onSkip }) {
  const [open, setOpen] = useState(defaultOpen);
  const count = useMemo(() => (groups || []).reduce((n, g) => n + (g.items || []).length, 0), [groups]);
  if (!count) return null;
  return (
    <Box>
      <Box
        component="button"
        type="button"
        onClick={() => setOpen((v) => !v)}
        sx={{
          width: "100%",
          display: "flex",
          justifyContent: "space-between",
          border: 0,
          bgcolor: "transparent",
          p: 0,
          mb: 0.85,
          cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        <Typography sx={{ fontSize: 12, fontWeight: 900, letterSpacing: 0.4, color }}>{title} · {count}</Typography>
        <Typography sx={{ fontSize: 11, color }}>{open ? "▾" : "▸"}</Typography>
      </Box>
      <Collapse in={open}>
        <Stack spacing={1.25}>
          {(groups || []).map((g) => (
            <Box key={g.pickup_date}>
              <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b", mb: 0.55 }}>
                {g.label}
              </Typography>
              <Stack spacing={0.7}>
                {(g.items || []).map((row) => (
                  <OccurrenceCard
                    key={row.occurrence_id || `${row.account_id}-${row.scheduled_pickup_date}`}
                    row={row}
                    onOpen={onOpen}
                    onSkip={onSkip}
                  />
                ))}
              </Stack>
            </Box>
          ))}
        </Stack>
      </Collapse>
    </Box>
  );
}

export default function DhsScheduleBoard({
  board,
  dateEt,
  onOpenOccurrence,
  onSkipOccurrence,
  onAddManualPickup,
  busy = false,
}) {
  const [skipRow, setSkipRow] = useState(null);
  const [skipNote, setSkipNote] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [manual, setManual] = useState({
    account_id: "",
    pickup_date: dateEt,
    delivery_date: "",
    use_account_delivery_rule: true,
    note: "",
  });

  const groups = board?.groups || {};
  const counts = board?.counts || {};

  return (
    <Stack spacing={1.5} sx={{ pb: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#64748b" }}>
          {board?.summary_label || friendlyDate(dateEt)}
        </Typography>
        <Button
          size="small"
          variant="contained"
          disabled={busy}
          onClick={() => setManualOpen(true)}
          sx={{ textTransform: "none", fontWeight: 800, bgcolor: "#007a91", minHeight: 40 }}
        >
          + Add Pickup
        </Button>
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 0.75,
          p: 1.2,
          borderRadius: 2,
          bgcolor: "rgba(0,122,145,0.06)",
        }}
      >
        {[
          ["Overdue", counts.overdue ?? 0, "#b91c1c"],
          ["Due", counts.due ?? 0, "#007a91"],
          ["Upcoming", counts.upcoming ?? 0, "#475569"],
        ].map(([lab, val, color]) => (
          <Box key={lab}>
            <Typography sx={{ fontSize: 11, fontWeight: 700, color }}>{lab}</Typography>
            <Typography sx={{ fontSize: 22, fontWeight: 900, color, lineHeight: 1.1 }}>{val}</Typography>
          </Box>
        ))}
      </Box>

      <LifecycleGroup
        title="OVERDUE"
        groups={groups.overdue}
        color="#b91c1c"
        defaultOpen
        onOpen={onOpenOccurrence}
        onSkip={(row) => { setSkipNote(""); setSkipRow(row); }}
      />
      <LifecycleGroup
        title="DUE"
        groups={groups.due}
        color="#007a91"
        defaultOpen
        onOpen={onOpenOccurrence}
        onSkip={(row) => { setSkipNote(""); setSkipRow(row); }}
      />
      <LifecycleGroup
        title="UPCOMING"
        groups={groups.upcoming}
        color="#475569"
        defaultOpen={false}
        onOpen={onOpenOccurrence}
        onSkip={(row) => { setSkipNote(""); setSkipRow(row); }}
      />

      <Dialog open={Boolean(skipRow)} onClose={() => setSkipRow(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>Skip this pickup?</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 14, mb: 1 }}>
            {skipRow?.name} · {friendlyDate(skipRow?.scheduled_pickup_date)}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", mb: 1 }}>
            Skips this occurrence only. Schedule unchanged.
          </Typography>
          <TextField fullWidth size="small" label="Reason (optional)" value={skipNote} onChange={(e) => setSkipNote(e.target.value)} />
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={() => setSkipRow(null)} sx={{ textTransform: "none" }}>Cancel</Button>
          <Button
            variant="contained"
            color="warning"
            sx={{ textTransform: "none", fontWeight: 800 }}
            onClick={async () => {
              await onSkipOccurrence?.(skipRow, skipNote.trim() || undefined);
              setSkipRow(null);
              setSkipNote("");
            }}
          >
            Skip
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={manualOpen} onClose={() => setManualOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>Add Pickup</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 0.5 }}>
            <FormControl fullWidth size="small">
              <InputLabel>Account</InputLabel>
              <Select label="Account" value={manual.account_id} onChange={(e) => setManual({ ...manual, account_id: e.target.value })}>
                {(board?.accounts || []).map((a) => (
                  <MenuItem key={a.id} value={String(a.id)}>{a.name}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField type="date" size="small" label="Pickup date" InputLabelProps={{ shrink: true }} value={manual.pickup_date} onChange={(e) => setManual({ ...manual, pickup_date: e.target.value })} />
            <FormControlLabel
              control={<Switch checked={manual.use_account_delivery_rule} onChange={(e) => setManual({ ...manual, use_account_delivery_rule: e.target.checked })} />}
              label="Use account delivery rule"
            />
            {!manual.use_account_delivery_rule ? (
              <TextField type="date" size="small" label="Delivery date" InputLabelProps={{ shrink: true }} value={manual.delivery_date} onChange={(e) => setManual({ ...manual, delivery_date: e.target.value })} />
            ) : null}
            <TextField fullWidth size="small" label="Note (optional)" value={manual.note} onChange={(e) => setManual({ ...manual, note: e.target.value })} />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={() => setManualOpen(false)} sx={{ textTransform: "none" }}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!manual.account_id || !manual.pickup_date || busy}
            sx={{ textTransform: "none", fontWeight: 800, bgcolor: "#007a91" }}
            onClick={async () => {
              await onAddManualPickup?.({
                account_id: Number(manual.account_id),
                scheduled_pickup_date: manual.pickup_date,
                scheduled_delivery_date: manual.use_account_delivery_rule ? null : manual.delivery_date || null,
                use_account_delivery_rule: Boolean(manual.use_account_delivery_rule),
                note: manual.note || null,
              });
              setManualOpen(false);
            }}
          >
            Add
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
