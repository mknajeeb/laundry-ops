import { Box, Button, Stack, Typography } from "@mui/material";
import MoneyAmountField from "./MoneyAmountField";
import SaveStatusChip from "./SaveStatusChip";
import { fmtMoney } from "./revenueFormat";

const STATUS_COLOR = {
  complete: "#0f766e",
  draft: "#0369a1",
  missing: "#d97706",
  no_activity: "#64748b",
};

/**
 * Large Daily operational cards for SS / Drop Off / WF / HD.
 */
export default function DailyEntryCards({
  dateLabel,
  completeness,
  nonRinse,
  rinse,
  onOpenSection,
  t,
}) {
  const byKey = Object.fromEntries((completeness?.sections || []).map((s) => [s.key, s]));
  const cards = [
    {
      key: "self_service",
      title: t?.("mobileOps.revenue.selfService") || "Self Service",
      lines: [
        { label: t?.("mobileOps.revenue.cash") || "Cash", value: nonRinse?.self_service?.cash },
        { label: t?.("mobileOps.revenue.card") || "Card", value: nonRinse?.self_service?.card },
      ],
      total: nonRinse?.self_service?.total,
    },
    {
      key: "drop_off",
      title: t?.("mobileOps.revenue.dropOff") || "Drop Off",
      lines: [
        { label: t?.("mobileOps.revenue.cash") || "Cash", value: nonRinse?.drop_off?.cash },
        { label: t?.("mobileOps.revenue.card") || "Card", value: nonRinse?.drop_off?.card },
      ],
      total: nonRinse?.drop_off?.total,
    },
    {
      key: "rinse_wf",
      title: t?.("mobileOps.revenue.rinseWf") || "Rinse WF",
      lines: [
        { label: "Volume", value: rinse?.wf?.volume_lbs, suffix: " lb" },
        { label: t?.("mobileOps.revenue.revenue") || "Revenue", value: rinse?.wf?.revenue },
      ],
      total: rinse?.wf?.revenue,
    },
    {
      key: "rinse_hd",
      title: t?.("mobileOps.revenue.hangDry") || "Rinse HD",
      lines: [
        { label: "Orders", value: rinse?.hd?.orders },
        { label: t?.("mobileOps.revenue.revenue") || "Revenue", value: rinse?.hd?.revenue },
      ],
      total: rinse?.hd?.revenue,
    },
  ];

  return (
    <Stack spacing={1.5}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 1,
        }}
      >
        <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", textTransform: "uppercase" }}>
          Daily required
        </Typography>
        <Typography sx={{ fontWeight: 900, fontSize: 18, color: "#007a91" }}>
          {completeness?.label || "0/4"}
        </Typography>
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "1fr 1fr" },
          gap: 1.25,
        }}
      >
        {cards.map((c) => {
          const st = byKey[c.key]?.status || "missing";
          return (
            <Box
              key={c.key}
              component="button"
              type="button"
              onClick={() => onOpenSection?.(c.key)}
              sx={{
                textAlign: "left",
                border: "1px solid rgba(0,122,145,0.28)",
                borderRadius: 2.5,
                bgcolor: "#fff",
                p: 1.75,
                minHeight: 148,
                cursor: "pointer",
                appearance: "none",
                fontFamily: "inherit",
                boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
              }}
            >
              <Typography sx={{ fontWeight: 900, fontSize: 16, color: "#0f172a" }}>{c.title}</Typography>
              <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#64748b", mb: 1 }}>{dateLabel}</Typography>
              <Stack spacing={0.35}>
                {c.lines.map((line) => (
                  <Box key={line.label} sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
                    <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#475569" }}>{line.label}</Typography>
                    <Typography sx={{ fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
                      {line.value == null || line.value === ""
                        ? "—"
                        : line.suffix
                          ? `${line.value}${line.suffix}`
                          : fmtMoney(line.value)}
                    </Typography>
                  </Box>
                ))}
              </Stack>
              <Box sx={{ mt: 1.25, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Typography sx={{ fontWeight: 900, fontSize: 17, color: "#007a91" }}>
                  {c.total == null ? "—" : fmtMoney(c.total)}
                </Typography>
                <Typography sx={{ fontSize: 12, fontWeight: 800, color: STATUS_COLOR[st] || "#64748b" }}>
                  {st === "complete" || st === "entered"
                    ? "Complete"
                    : st === "draft"
                      ? "Draft"
                      : st === "no_activity"
                        ? "No Activity"
                        : "Missing"}
                </Typography>
              </Box>
            </Box>
          );
        })}
      </Box>
    </Stack>
  );
}

/** Inline expandable daily money entry used inside focused sheets — re-export helpers. */
export function DailyMoneyBlock({ cash, card, onCash, onCard, saveState, saveLabels, onComplete, onNoActivity, completeLabel, noActivityLabel, completeBusy }) {
  return (
    <Stack spacing={1.5} sx={{ pb: 10 }}>
      <MoneyAmountField label="Cash" value={cash} onChange={onCash} autoFocus />
      <MoneyAmountField label="Card" value={card} onChange={onCard} />
      <Box sx={{ position: "sticky", bottom: 0, bgcolor: "#fff", border: "1px solid #e5e7eb", borderRadius: 2, p: 1.25 }}>
        <SaveStatusChip state={saveState} labels={saveLabels} />
        <Button
          fullWidth
          variant="contained"
          disabled={completeBusy || saveState === "saving"}
          onClick={onComplete}
          sx={{ mt: 1, textTransform: "none", fontWeight: 900, minHeight: 52, fontSize: 16 }}
        >
          {completeLabel || "Complete"}
        </Button>
        {onNoActivity ? (
          <Button fullWidth onClick={onNoActivity} sx={{ mt: 0.5, textTransform: "none", fontWeight: 700 }}>
            {noActivityLabel || "No Activity"}
          </Button>
        ) : null}
      </Box>
    </Stack>
  );
}
