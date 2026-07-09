import { useState } from "react";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  List,
  ListItem,
  ListItemText,
  Popover,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  formatCurrency,
  getDrcSourceIndicatorStyle,
  getDrcSourceLabel,
  isImportedDrcSource,
} from "../../utils/dailyRevenueCostHelpers";

function formatCapturedAt(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

export default function DrcSourceIndicator({ meta, valueLabel }) {
  const [anchor, setAnchor] = useState(null);
  const style = getDrcSourceIndicatorStyle(meta);
  const open = Boolean(anchor);

  if (!meta && !valueLabel) return null;

  const chipLabel = meta?.is_manual_override
    ? `${getDrcSourceLabel(meta.source_system)} · Override`
    : style.label;

  return (
    <>
      <Chip
        size="small"
        label={chipLabel}
        color={style.color}
        variant={style.variant}
        onClick={(e) => setAnchor(e.currentTarget)}
        sx={{ cursor: "pointer", mt: { xs: 0.5, sm: 1.1 }, flexShrink: 0 }}
      />
      <Popover
        open={open}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <Box sx={{ p: 2, maxWidth: 320 }}>
          <Typography variant="subtitle2" fontWeight={700} gutterBottom>
            Source details
          </Typography>
          {valueLabel ? (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Current: {valueLabel}
            </Typography>
          ) : null}
          <Stack spacing={0.75}>
            <Typography variant="body2">
              <strong>Source:</strong> {getDrcSourceLabel(meta?.source_system)}
            </Typography>
            <Typography variant="body2">
              <strong>Import time:</strong> {formatCapturedAt(meta?.source_captured_at)}
            </Typography>
            <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
              <strong>Reference:</strong> {meta?.source_ref || "—"}
            </Typography>
            {meta?.is_manual_override ? (
              <>
                <Typography variant="body2">
                  <strong>Override reason:</strong> {meta?.override_reason || "—"}
                </Typography>
                <Typography variant="body2">
                  <strong>Overridden:</strong> {formatCapturedAt(meta?.overridden_at)}
                </Typography>
              </>
            ) : null}
          </Stack>
          {(meta?.history || []).length > 0 ? (
            <>
              <Divider sx={{ my: 1.5 }} />
              <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                Change history
              </Typography>
              <List dense disablePadding>
                {(meta.history || []).slice(0, 5).map((evt, idx) => (
                  <ListItem key={`${evt.created_at}-${idx}`} disableGutters sx={{ alignItems: "flex-start" }}>
                    <ListItemText
                      primary={`${evt.event_type}: ${evt.old_value ?? "—"} → ${evt.new_value ?? "—"}`}
                      secondary={formatCapturedAt(evt.created_at)}
                      primaryTypographyProps={{ variant: "body2" }}
                      secondaryTypographyProps={{ variant: "caption" }}
                    />
                  </ListItem>
                ))}
              </List>
            </>
          ) : null}
          {isImportedDrcSource(meta) && meta?.source_payload ? (
            <>
              <Divider sx={{ my: 1.5 }} />
              <Typography variant="caption" color="text.secondary" component="pre" sx={{ whiteSpace: "pre-wrap", m: 0 }}>
                {JSON.stringify(meta.source_payload, null, 2)}
              </Typography>
            </>
          ) : null}
        </Box>
      </Popover>
    </>
  );
}

export function DrcFieldRow({ meta, valueLabel, children }) {
  return (
    <Stack direction="row" spacing={1} alignItems="flex-start">
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
      <DrcSourceIndicator meta={meta} valueLabel={valueLabel} />
    </Stack>
  );
}

export function DrcOverrideReasonDialog({ open, fields, reasons, onReasonChange, onCancel, onConfirm, busy }) {
  return (
    <Dialog open={open} onClose={busy ? undefined : onCancel} fullWidth maxWidth="sm">
      <DialogTitle>Override imported values</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          These fields were imported automatically. Enter a reason before saving your changes.
        </Typography>
        <Stack spacing={2}>
          {(fields || []).map((item) => (
            <Box key={item.lineKey}>
              <Typography variant="subtitle2" fontWeight={700}>
                {item.fieldLabel}
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                Imported from {item.sourceLabel}
              </Typography>
              <TextField
                label="Reason for override"
                value={reasons[item.lineKey] || ""}
                onChange={(e) => onReasonChange(item.lineKey, e.target.value)}
                disabled={busy}
                fullWidth
                required
                multiline
                minRows={2}
              />
            </Box>
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={onConfirm}
          disabled={busy || !fields?.every((f) => (reasons[f.lineKey] || "").trim())}
        >
          {busy ? "Saving…" : "Save with overrides"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export function formatDrcSourceValue(field, value) {
  if (["rinse_hd_orders", "rinse_wi_orders"].includes(field)) {
    return `${Number(value) || 0}`;
  }
  if (field === "rinse_wf_pounds" || field === "pounds") {
    return `${Number(value) || 0} lb`;
  }
  return formatCurrency(value);
}
