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

function friendlyDate(iso) {
  try {
    const [y, m, d] = String(iso).split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return iso || "—";
  }
}

function actionTitle(row) {
  const action = row.action || "pickup";
  const when = friendlyDate(row.action_date || row.scheduled_pickup_date);
  if (action === "delivery") return `Delivery · ${when}`;
  if (action === "processing") return `Processing · ${when}`;
  return `Pickup · ${when}`;
}

function statusTone(status) {
  if (status === "overdue") return "#b91c1c";
  if (status === "draft" || status === "complete") return "#0f766e";
  if (status === "skipped" || status === "no_activity") return "#64748b";
  return "#334155";
}

function OccurrenceCard({ row, onOpen, onSkip }) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "stretch",
        gap: 1,
        py: 1,
        px: 1.1,
        bgcolor: "#fff",
        borderRadius: 1.5,
        boxShadow: "0 1px 0 rgba(15,23,42,0.06)",
      }}
    >
      <Box
        sx={{
          width: 4,
          borderRadius: 99,
          bgcolor: row.action === "delivery" ? "#0ea5e9" : row.action === "processing" ? "#a855f7" : "#0f766e",
          flexShrink: 0,
        }}
      />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={0.75} alignItems="baseline">
          <Typography sx={{ fontWeight: 800, fontSize: 15, color: "#0f172a", lineHeight: 1.2 }}>
            {row.name}
          </Typography>
          {row.is_manual ? (
            <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#b45309" }}>Manual</Typography>
          ) : null}
        </Stack>
        <Typography sx={{ fontSize: 13, color: "#475569", mt: 0.15 }}>{actionTitle(row)}</Typography>
        <Typography sx={{ fontSize: 11, fontWeight: 700, color: statusTone(row.status), mt: 0.2, textTransform: "capitalize" }}>
          {row.status || "pending"}
        </Typography>
      </Box>
      <Stack spacing={0.5} sx={{ flexShrink: 0, justifyContent: "center" }}>
        <Button
          size="small"
          variant="contained"
          onClick={() => onOpen(row)}
          sx={{ textTransform: "none", minHeight: 36, px: 1.5, bgcolor: "#007a91", "&:hover": { bgcolor: "#006679" } }}
        >
          Open
        </Button>
        {row.action === "pickup" && !row.resolved ? (
          <Button
            size="small"
            variant="text"
            onClick={() => onSkip(row)}
            sx={{ textTransform: "none", minHeight: 32, color: "#64748b" }}
          >
            Skip
          </Button>
        ) : null}
      </Stack>
    </Box>
  );
}

function DaySection({ section, defaultOpen, onOpen, onSkip }) {
  const [open, setOpen] = useState(defaultOpen);
  const pickupN = (section.pickups || []).length;
  const deliveryN = (section.deliveries || []).length;
  const procN = (section.processing || []).length;
  return (
    <Box>
      <Box
        component="button"
        type="button"
        onClick={() => setOpen((v) => !v)}
        sx={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          border: 0,
          bgcolor: "transparent",
          p: 0,
          mb: 0.75,
          cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        <Typography sx={{ fontSize: 12, fontWeight: 900, letterSpacing: 0.4, color: "#0f172a" }}>
          {section.label}
        </Typography>
        <Typography sx={{ fontSize: 11, color: "#64748b", fontWeight: 700 }}>
          {pickupN}P · {deliveryN}D{procN ? ` · ${procN}Proc` : ""} {open ? "▾" : "▸"}
        </Typography>
      </Box>
      <Collapse in={open}>
        <Stack spacing={1.25}>
          {pickupN ? (
            <Box>
              <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#0f766e", mb: 0.5, letterSpacing: 0.3 }}>
                PICKUPS
              </Typography>
              <Stack spacing={0.65}>
                {(section.pickups || []).map((row) => (
                  <OccurrenceCard
                    key={`${row.occurrence_id || row.account_id}-pu-${row.scheduled_pickup_date}`}
                    row={row}
                    onOpen={onOpen}
                    onSkip={onSkip}
                  />
                ))}
              </Stack>
            </Box>
          ) : null}
          {deliveryN ? (
            <Box>
              <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#0284c7", mb: 0.5, letterSpacing: 0.3 }}>
                DELIVERIES
              </Typography>
              <Stack spacing={0.65}>
                {(section.deliveries || []).map((row) => (
                  <OccurrenceCard
                    key={`${row.occurrence_id || row.account_id}-de-${row.scheduled_delivery_date}`}
                    row={row}
                    onOpen={onOpen}
                    onSkip={onSkip}
                  />
                ))}
              </Stack>
            </Box>
          ) : null}
          {procN ? (
            <Box>
              <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#7e22ce", mb: 0.5, letterSpacing: 0.3 }}>
                NEEDS PROCESSING
              </Typography>
              <Stack spacing={0.65}>
                {(section.processing || []).map((row) => (
                  <OccurrenceCard
                    key={`${row.occurrence_id || row.account_id}-pr-${row.suggested_processing_date}`}
                    row={row}
                    onOpen={onOpen}
                    onSkip={onSkip}
                  />
                ))}
              </Stack>
            </Box>
          ) : null}
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
  const [overdueOpen, setOverdueOpen] = useState(true);

  const sections = useMemo(() => board?.sections || [], [board]);
  const overdue = useMemo(() => board?.overdue || [], [board]);
  const counts = board?.counts || {};
  const summaryLabel = board?.summary_label || friendlyDate(dateEt);

  const confirmSkip = async () => {
    if (!skipRow) return;
    await onSkipOccurrence?.(skipRow, skipNote.trim() || undefined);
    setSkipRow(null);
    setSkipNote("");
  };

  const submitManual = async () => {
    if (!manual.account_id || !manual.pickup_date) return;
    await onAddManualPickup?.({
      account_id: Number(manual.account_id),
      scheduled_pickup_date: manual.pickup_date,
      scheduled_delivery_date: manual.use_account_delivery_rule ? null : manual.delivery_date || null,
      use_account_delivery_rule: Boolean(manual.use_account_delivery_rule),
      note: manual.note || null,
    });
    setManualOpen(false);
    setManual({
      account_id: "",
      pickup_date: dateEt,
      delivery_date: "",
      use_account_delivery_rule: true,
      note: "",
    });
  };

  return (
    <Stack spacing={1.5} sx={{ pb: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Box>
          <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", textTransform: "uppercase" }}>
            Today — {summaryLabel}
          </Typography>
        </Box>
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
          gridTemplateColumns: "1fr 1fr",
          gap: 0.75,
          p: 1.25,
          borderRadius: 2,
          bgcolor: "rgba(0,122,145,0.06)",
        }}
      >
        {[
          ["Pickups", counts.pickups_today ?? 0],
          ["Deliveries", counts.deliveries_today ?? 0],
          ["Needs Processing", counts.needs_processing ?? counts.pending_processing ?? 0],
          ["Overdue", counts.overdue ?? 0],
        ].map(([lab, val]) => (
          <Box key={lab} sx={{ py: 0.5 }}>
            <Typography sx={{ fontSize: 11, color: lab === "Overdue" ? "#b91c1c" : "#64748b", fontWeight: 700 }}>
              {lab}
            </Typography>
            <Typography sx={{ fontSize: 22, fontWeight: 900, color: lab === "Overdue" && val ? "#b91c1c" : "#0f172a", lineHeight: 1.1 }}>
              {val}
            </Typography>
          </Box>
        ))}
      </Box>

      {(board?.needs_schedule_confirm || []).length ? (
        <Typography sx={{ fontSize: 12, color: "#b45309", fontWeight: 700 }}>
          Confirm schedule: {(board.needs_schedule_confirm || []).map((a) => a.name).join(", ")}
        </Typography>
      ) : null}

      {sections.map((section) => (
        <DaySection
          key={section.date}
          section={section}
          defaultOpen={!section.collapsed_default}
          onOpen={onOpenOccurrence}
          onSkip={(row) => {
            setSkipNote("");
            setSkipRow(row);
          }}
        />
      ))}

      {overdue.length ? (
        <Box>
          <Box
            component="button"
            type="button"
            onClick={() => setOverdueOpen((v) => !v)}
            sx={{
              width: "100%",
              display: "flex",
              justifyContent: "space-between",
              border: 0,
              bgcolor: "transparent",
              p: 0,
              mb: 0.75,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            <Typography sx={{ fontSize: 12, fontWeight: 900, color: "#b91c1c", letterSpacing: 0.4 }}>
              OVERDUE · {overdue.length}
            </Typography>
            <Typography sx={{ fontSize: 11, color: "#b91c1c" }}>{overdueOpen ? "▾" : "▸"}</Typography>
          </Box>
          <Collapse in={overdueOpen}>
            <Stack spacing={0.65}>
              {overdue.map((row) => (
                <OccurrenceCard
                  key={`${row.occurrence_id || row.account_id}-od-${row.action}-${row.action_date}`}
                  row={row}
                  onOpen={onOpenOccurrence}
                  onSkip={(r) => {
                    setSkipNote("");
                    setSkipRow(r);
                  }}
                />
              ))}
            </Stack>
          </Collapse>
        </Box>
      ) : null}

      {!sections.length && !overdue.length ? (
        <Typography sx={{ fontSize: 13, color: "#64748b", textAlign: "center", py: 3 }}>
          No DHS work in this window.
        </Typography>
      ) : null}

      <Dialog open={Boolean(skipRow)} onClose={() => setSkipRow(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>Skip this pickup?</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 14, mb: 1.5 }}>
            {skipRow?.name} · {friendlyDate(skipRow?.scheduled_pickup_date)}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", mb: 1 }}>
            Skips this occurrence only. The recurring schedule is unchanged.
          </Typography>
          <TextField
            fullWidth
            size="small"
            label="Reason (optional)"
            value={skipNote}
            onChange={(e) => setSkipNote(e.target.value)}
          />
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={() => setSkipRow(null)} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button variant="contained" color="warning" onClick={confirmSkip} sx={{ textTransform: "none", fontWeight: 800 }}>
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
              <Select
                label="Account"
                value={manual.account_id}
                onChange={(e) => setManual({ ...manual, account_id: e.target.value })}
              >
                {(board?.accounts || []).map((a) => (
                  <MenuItem key={a.id} value={String(a.id)}>
                    {a.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              type="date"
              size="small"
              label="Pickup date"
              InputLabelProps={{ shrink: true }}
              value={manual.pickup_date}
              onChange={(e) => setManual({ ...manual, pickup_date: e.target.value })}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={manual.use_account_delivery_rule}
                  onChange={(e) => setManual({ ...manual, use_account_delivery_rule: e.target.checked })}
                />
              }
              label="Use account delivery rule"
            />
            {!manual.use_account_delivery_rule ? (
              <TextField
                type="date"
                size="small"
                label="Delivery date"
                InputLabelProps={{ shrink: true }}
                value={manual.delivery_date}
                onChange={(e) => setManual({ ...manual, delivery_date: e.target.value })}
              />
            ) : null}
            <TextField
              fullWidth
              size="small"
              label="Note (optional)"
              value={manual.note}
              onChange={(e) => setManual({ ...manual, note: e.target.value })}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={() => setManualOpen(false)} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={!manual.account_id || !manual.pickup_date || busy}
            onClick={submitManual}
            sx={{ textTransform: "none", fontWeight: 800, bgcolor: "#007a91" }}
          >
            Add
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
