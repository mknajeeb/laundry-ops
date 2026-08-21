import { useRef } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import PlanningDatePicker from "../datetime/PlanningDatePicker";
import MoneyAmountField from "./MoneyAmountField";
import SaveStatusChip from "./SaveStatusChip";
import { fmtMoney, parseMoneyInput } from "./revenueFormat";

/**
 * Shared Self Service / Drop Off Cash+Card entry.
 * Parent owns draft values, debounced autosave, and Complete finalization.
 */
export default function NonRinseEntryPanel({
  title,
  cash,
  card,
  onCashChange,
  onCardChange,
  saveState,
  saveLabels,
  cashLabel = "Cash",
  cardLabel = "Card",
  totalLabel = "Total",
  processingDate,
  onProcessingDateChange,
  processingDateLabel = "Processing Date",
  onComplete,
  completeLabel = "Complete",
  completeBusy = false,
  onNoActivity,
  noActivityLabel = "No Activity",
}) {
  const cardRef = useRef(null);
  const cashN = parseMoneyInput(cash);
  const cardN = parseMoneyInput(card);
  const total =
    cashN == null && cardN == null ? null : Number(cashN || 0) + Number(cardN || 0);

  return (
    <Stack spacing={1.5} sx={{ pb: 12 }}>
      {title ? (
        <Typography sx={{ fontSize: 18, fontWeight: 900, color: "#0f172a" }}>{title}</Typography>
      ) : null}
      {onProcessingDateChange ? (
        <PlanningDatePicker
          label={processingDateLabel}
          value={processingDate || ""}
          onChange={onProcessingDateChange}
        />
      ) : null}
      <MoneyAmountField
        label={cashLabel}
        value={cash}
        onChange={onCashChange}
        onEnterNext={() => cardRef.current?.focus?.()}
        autoFocus
      />
      <MoneyAmountField
        label={cardLabel}
        value={card}
        onChange={onCardChange}
        inputRef={cardRef}
      />
      <Box
        sx={{
          position: "sticky",
          bottom: 0,
          p: 1.25,
          borderRadius: 2,
          bgcolor: "#fff",
          border: "1px solid #e5e7eb",
          display: "flex",
          flexDirection: "column",
          gap: 1,
          zIndex: 2,
        }}
      >
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 18, color: "#007a91" }}>
            {totalLabel} {fmtMoney(total)}
          </Typography>
          <SaveStatusChip state={saveState} labels={saveLabels} />
        </Box>
        <Button
          variant="contained"
          disabled={completeBusy || saveState === "saving"}
          onClick={() => onComplete?.()}
          sx={{ textTransform: "none", fontWeight: 900, minHeight: 48 }}
        >
          {completeLabel}
        </Button>
        {onNoActivity ? (
          <Button
            size="small"
            disabled={completeBusy}
            onClick={() => onNoActivity?.()}
            sx={{ textTransform: "none", fontWeight: 700 }}
          >
            {noActivityLabel}
          </Button>
        ) : null}
      </Box>
    </Stack>
  );
}
