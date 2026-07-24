import { useState } from "react";
import { Box, Button, Chip, IconButton, Stack, TextField, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import AddIcon from "@mui/icons-material/Add";
import RemoveIcon from "@mui/icons-material/Remove";
import FlagOutlinedIcon from "@mui/icons-material/FlagOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { OPS_MOBILE } from "./tokens";
import {
  FLOOR_QUICK_NOTES,
  compactQtyDiff,
  itemCurrentQty,
  itemIsStatusTracked,
} from "../utils/inventoryFloorHelpers";
import { VARIANCE_REASON_LABELS } from "../utils/inventoryRoleHelpers";
import { parseQtyInput } from "../utils/inventoryHelpers";

const STATUS_KEYS = ["OK", "LOW", "OUT"];

function statusSx(key, active) {
  const palette = {
    OK: { bg: alpha("#0f766e", 0.14), border: "#0f766e", color: "#0f766e" },
    LOW: { bg: alpha("#b45309", 0.14), border: "#b45309", color: "#92400e" },
    OUT: { bg: alpha("#b91c1c", 0.14), border: "#b91c1c", color: "#991b1b" },
  }[key];
  return {
    flex: 1,
    minHeight: 56,
    borderRadius: `${OPS_MOBILE.radius.button}px`,
    border: "2px solid",
    borderColor: active ? palette.border : alpha(OPS_MOBILE.navy, 0.12),
    bgcolor: active ? palette.bg : alpha("#fff", 0.96),
    color: active ? palette.color : OPS_MOBILE.muted,
    fontWeight: 900,
    fontSize: "1rem",
    textTransform: "none",
  };
}

/**
 * Floor stock-count card — quantity king / status OK·LOW·OUT.
 */
export default function OpsFloorStockCard({
  item,
  countValue,
  noteValue,
  varianceReason,
  varianceThreshold = 5,
  statusValue,
  needsRecount,
  onCountChange,
  onNoteChange,
  onVarianceReasonChange,
  onStatusChange,
  onRecountChange,
}) {
  const [notesOpen, setNotesOpen] = useState(Boolean(String(noteValue || "").trim()));
  const isStatus = itemIsStatusTracked(item);
  const current = itemCurrentQty(item);
  const name = item.name || item.item_name || "Item";
  const entered = countValue === "" || countValue == null ? null : Number(countValue);
  const diff = !isStatus ? compactQtyDiff(countValue, current) : null;
  const needsReason =
    !needsRecount && diff != null && Math.abs(diff) > Number(varianceThreshold || 5);
  const selectedStatus = String(statusValue || item.status_level || "OK").toUpperCase();

  const toggleQuick = (chipValue) => {
    const cur = String(noteValue || "");
    if (cur.includes(chipValue)) {
      onNoteChange?.(
        cur
          .replace(chipValue, "")
          .replace(/\s{2,}/g, " ")
          .replace(/^[,;\s]+|[,;\s]+$/g, "")
          .trim(),
      );
    } else {
      onNoteChange?.(cur ? `${cur.trim()}; ${chipValue}` : chipValue);
    }
  };

  const setQty = (next) => {
    const n = Math.max(0, Number.isFinite(next) ? next : 0);
    onRecountChange?.(false);
    onCountChange?.(String(n));
  };

  const safe = Number.isFinite(entered) ? entered : 0;

  return (
    <Box
      sx={{
        width: "100%",
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        bgcolor: needsRecount ? alpha(OPS_MOBILE.cobalt, 0.08) : alpha("#fff", 0.98),
        px: 1.75,
        py: 1.5,
        boxShadow: `0 1px 0 ${alpha(OPS_MOBILE.navy, 0.06)}`,
      }}
    >
      <Typography
        sx={{
          fontWeight: 900,
          fontSize: { xs: "1.15rem", sm: "1.2rem" },
          lineHeight: 1.25,
          color: OPS_MOBILE.navy,
          whiteSpace: "normal",
          wordBreak: "break-word",
          overflowWrap: "anywhere",
          mb: 1.25,
        }}
      >
        {name}
      </Typography>

      {isStatus ? (
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          {STATUS_KEYS.map((k) => (
            <Button key={k} onClick={() => onStatusChange?.(k)} sx={statusSx(k, selectedStatus === k)}>
              {k}
            </Button>
          ))}
        </Stack>
      ) : (
        <>
          <Stack direction="row" alignItems="stretch" spacing={1} sx={{ mb: 0.75 }}>
            <IconButton
              aria-label={`Decrease ${name}`}
              onClick={() => setQty(safe - 1)}
              disabled={safe <= 0}
              sx={{
                width: 56,
                height: 56,
                borderRadius: 2,
                border: `1px solid ${alpha(OPS_MOBILE.navy, 0.14)}`,
                bgcolor: alpha(OPS_MOBILE.navy, 0.04),
              }}
            >
              <RemoveIcon />
            </IconButton>
            <TextField
              fullWidth
              type="number"
              inputMode="decimal"
              value={countValue ?? ""}
              onChange={(e) => {
                const parsed = parseQtyInput(e.target.value);
                onRecountChange?.(false);
                onCountChange?.(parsed === "" ? "" : String(parsed));
              }}
              inputProps={{
                min: 0,
                style: { textAlign: "center", fontSize: "1.65rem", fontWeight: 900 },
                "aria-label": `${name} quantity`,
              }}
              sx={{
                "& .MuiInputBase-root": {
                  height: 56,
                  borderRadius: 2,
                  bgcolor: alpha(OPS_MOBILE.cobalt, 0.06),
                },
                "& fieldset": { borderColor: alpha(OPS_MOBILE.navy, 0.12) },
              }}
            />
            <IconButton
              aria-label={`Increase ${name}`}
              onClick={() => setQty(safe + 1)}
              sx={{
                width: 56,
                height: 56,
                borderRadius: 2,
                border: `1px solid ${alpha(OPS_MOBILE.navy, 0.14)}`,
                bgcolor: alpha(OPS_MOBILE.cobalt, 0.12),
              }}
            >
              <AddIcon />
            </IconButton>
          </Stack>
          <Typography sx={{ fontWeight: 700, fontSize: "0.9rem", color: OPS_MOBILE.muted, mb: 1 }}>
            Current {current}
            {diff != null ? ` · ${diff > 0 ? `+${diff}` : diff}` : ""}
          </Typography>
        </>
      )}

      <Box
        sx={{
          display: "flex",
          gap: 0.75,
          overflowX: "auto",
          pb: 0.5,
          mb: 0.75,
          WebkitOverflowScrolling: "touch",
        }}
      >
        {FLOOR_QUICK_NOTES.map((chip) => {
          const on = String(noteValue || "").includes(chip.value);
          return (
            <Chip
              key={chip.value}
              size="small"
              label={chip.label}
              onClick={() => toggleQuick(chip.value)}
              sx={{
                flexShrink: 0,
                fontWeight: 800,
                bgcolor: on ? alpha(OPS_MOBILE.cobalt, 0.18) : alpha(OPS_MOBILE.navy, 0.04),
                color: OPS_MOBILE.navy,
              }}
            />
          );
        })}
      </Box>

      {needsReason ? (
        <Box sx={{ display: "flex", gap: 0.75, overflowX: "auto", pb: 0.5, mb: 0.75 }}>
          {Object.entries(VARIANCE_REASON_LABELS).map(([k, lbl]) => (
            <Chip
              key={k}
              size="small"
              label={lbl}
              onClick={() => onVarianceReasonChange?.(k)}
              sx={{
                flexShrink: 0,
                fontWeight: 800,
                bgcolor:
                  varianceReason === k ? alpha(OPS_MOBILE.danger, 0.14) : alpha(OPS_MOBILE.navy, 0.04),
                color: OPS_MOBILE.navy,
              }}
            />
          ))}
        </Box>
      ) : null}

      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Button
          size="small"
          onClick={() => setNotesOpen((v) => !v)}
          endIcon={<ExpandMoreIcon sx={{ transform: notesOpen ? "rotate(180deg)" : "none" }} />}
          sx={{
            textTransform: "none",
            fontWeight: 800,
            minHeight: 44,
            color: OPS_MOBILE.blue,
          }}
        >
          Notes
        </Button>
        <Button
          size="small"
          startIcon={<FlagOutlinedIcon />}
          onClick={() => onRecountChange?.(!needsRecount)}
          sx={{
            textTransform: "none",
            fontWeight: 800,
            minHeight: 44,
            color: needsRecount ? OPS_MOBILE.cobalt : OPS_MOBILE.muted,
          }}
        >
          {needsRecount ? "Needs recount" : "Recount"}
        </Button>
      </Stack>

      {notesOpen ? (
        <TextField
          fullWidth
          multiline
          minRows={2}
          placeholder="Notes"
          value={noteValue ?? ""}
          onChange={(e) => onNoteChange?.(e.target.value)}
          sx={{ mt: 1, "& .MuiInputBase-root": { borderRadius: 2 } }}
        />
      ) : null}
    </Box>
  );
}
