import { Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import NonRinseEntryPanel from "./NonRinseEntryPanel";
import PlanningDatePicker from "../datetime/PlanningDatePicker";
import MoneyAmountField from "./MoneyAmountField";
import SaveStatusChip from "./SaveStatusChip";
import { fmtMoney, moneyToInput } from "./revenueFormat";

function friendlyDate(iso) {
  try {
    const [y, m, d] = String(iso).split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function PeriodChip({ label, onClick }) {
  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        appearance: "none",
        border: 0,
        fontFamily: "inherit",
        cursor: "pointer",
        bgcolor: "rgba(0,122,145,0.1)",
        color: "#0f172a",
        fontWeight: 900,
        fontSize: 14,
        px: 1.25,
        py: 0.75,
        borderRadius: 2,
        minHeight: 40,
      }}
    >
      {label} ▾
    </Box>
  );
}

function SummaryGrid({ items }) {
  return (
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
      {items.map(([lab, val]) => (
        <Box key={lab}>
          <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>{lab}</Typography>
          <Typography sx={{ fontSize: 20, fontWeight: 900, color: "#0f172a", lineHeight: 1.1 }}>{val}</Typography>
        </Box>
      ))}
    </Box>
  );
}

/**
 * Self Service / Drop Off / WF section home: period summary + today's entry + recent.
 */
export default function StreamEntryHome({
  stream,
  periodLabel,
  onPeriodClick,
  summary,
  loading,
  // Non-rinse
  cash,
  card,
  onCashChange,
  onCardChange,
  // WF
  volume,
  onVolumeChange,
  revenueLabel,
  // shared
  dateEt,
  onDateChange,
  saveState,
  onComplete,
  onNoActivity,
  completeBusy,
  recent = [],
  onOpenRecent,
}) {
  const isNonRinse = stream === "self_service" || stream === "drop_off";
  const title =
    stream === "self_service"
      ? "Self Service"
      : stream === "drop_off"
        ? "Drop Off"
        : stream === "rinse_wf"
          ? "Rinse WF"
          : "Rinse HD";

  const summaryItems = isNonRinse
    ? [
        ["Revenue", fmtMoney(summary?.revenue)],
        ["Cash", fmtMoney(summary?.cash)],
        ["Card", fmtMoney(summary?.card)],
        ["Days complete", String(summary?.days_complete ?? 0)],
      ]
    : [
        ["Revenue", fmtMoney(summary?.revenue)],
        ["Volume", summary?.volume_lbs != null ? `${Number(summary.volume_lbs).toLocaleString()} lb` : "—"],
        ["Days complete", String(summary?.days_complete ?? 0)],
        ["Period", periodLabel || "—"],
      ];

  return (
    <Stack spacing={1.5} sx={{ pb: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography sx={{ fontSize: 18, fontWeight: 900 }}>{title}</Typography>
        <PeriodChip label={periodLabel || "This Month"} onClick={onPeriodClick} />
      </Stack>

      {loading && !summary ? (
        <Box sx={{ py: 3, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <SummaryGrid items={summaryItems} />
      )}

      <Typography sx={{ fontSize: 13, fontWeight: 900, color: "#0f172a" }}>Today&apos;s entry</Typography>

      {isNonRinse ? (
        <NonRinseEntryPanel
          cash={cash}
          card={card}
          onCashChange={onCashChange}
          onCardChange={onCardChange}
          saveState={saveState}
          processingDate={dateEt}
          onProcessingDateChange={onDateChange}
          onComplete={onComplete}
          completeBusy={completeBusy}
          onNoActivity={onNoActivity}
        />
      ) : stream === "rinse_wf" ? (
        <Stack spacing={1.25}>
          <PlanningDatePicker label="Processing Date" value={dateEt} onChange={onDateChange} />
          <MoneyAmountField label="Volume (lbs)" value={volume} onChange={onVolumeChange} />
          <Typography sx={{ fontSize: 15, fontWeight: 800, color: "#007a91" }}>
            Revenue {revenueLabel || "—"}
          </Typography>
          <SaveStatusChip state={saveState} />
          <Stack direction="row" spacing={1}>
            <Button
              fullWidth
              variant="outlined"
              disabled={completeBusy}
              onClick={onNoActivity}
              sx={{ textTransform: "none", minHeight: 48 }}
            >
              No Activity
            </Button>
            <Button
              fullWidth
              variant="contained"
              disabled={completeBusy}
              onClick={onComplete}
              sx={{ textTransform: "none", fontWeight: 800, minHeight: 48, bgcolor: "#007a91" }}
            >
              Complete
            </Button>
          </Stack>
        </Stack>
      ) : (
        <Typography sx={{ fontSize: 13, color: "#64748b" }}>
          Use Hang Dry production below for today&apos;s HD entry.
        </Typography>
      )}

      <Typography sx={{ fontSize: 13, fontWeight: 900, pt: 0.5 }}>Recent</Typography>
      <Stack spacing={0.65}>
        {(recent || []).length === 0 ? (
          <Typography sx={{ fontSize: 13, color: "#64748b" }}>No entries in this period yet.</Typography>
        ) : (
          (recent || []).map((r) => (
            <Box
              key={r.date_et}
              component="button"
              type="button"
              onClick={() => onOpenRecent?.(r.date_et)}
              sx={{
                textAlign: "left",
                appearance: "none",
                border: 0,
                fontFamily: "inherit",
                cursor: "pointer",
                p: 1.1,
                borderRadius: 2,
                bgcolor: "#fff",
                boxShadow: "0 1px 0 rgba(15,23,42,0.06)",
              }}
            >
              <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{friendlyDate(r.date_et)}</Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                {isNonRinse
                  ? `${fmtMoney(r.total)} · Cash ${fmtMoney(r.cash)} · Card ${fmtMoney(r.card)}`
                  : `${r.volume_lbs != null ? `${r.volume_lbs} lb` : "—"} · ${fmtMoney(r.revenue)}`}
              </Typography>
            </Box>
          ))
        )}
      </Stack>
    </Stack>
  );
}

export { moneyToInput };
