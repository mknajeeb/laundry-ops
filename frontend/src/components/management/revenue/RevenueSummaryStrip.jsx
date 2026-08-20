import { Box, Stack, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";
import { fmtMoney, netCashTone } from "./revenueFormat";

function KpiChip({ label, value, onClick, tone = "default" }) {
  const colors = {
    default: { accent: VEEWASH_DASHBOARD.primaryBlueDark, border: VEEWASH_DASHBOARD.primaryBlueBorder },
    positive: { accent: VEEWASH_DASHBOARD.tealDark, border: VEEWASH_DASHBOARD.tealBorder },
    negative: { accent: "#b91c1c", border: "rgba(185,28,28,0.35)" },
    warn: { accent: VEEWASH_DASHBOARD.pending, border: VEEWASH_DASHBOARD.pendingBorder },
    neutral: { accent: "#64748b", border: "#e5e7eb" },
  };
  const c = colors[tone] || colors.default;
  return (
    <Box
      component={onClick ? "button" : "div"}
      type={onClick ? "button" : undefined}
      onClick={onClick}
      sx={{
        display: "block",
        width: "100%",
        textAlign: "left",
        m: 0,
        px: 1.25,
        py: 1,
        minHeight: 64,
        borderRadius: 1.5,
        border: "1px solid",
        borderColor: c.border,
        bgcolor: "#fff",
        cursor: onClick ? "pointer" : "default",
        appearance: "none",
        fontFamily: "inherit",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        WebkitTapHighlightColor: "transparent",
        "&:hover": onClick ? { borderColor: c.accent } : undefined,
      }}
    >
      <Typography sx={{ fontSize: { xs: 18, sm: 20 }, fontWeight: 800, color: c.accent, lineHeight: 1.1, letterSpacing: -0.3 }}>
        {value}
      </Typography>
      <Typography
        sx={{
          mt: 0.4,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 0.55,
          textTransform: "uppercase",
          color: "#64748b",
        }}
      >
        {label}
      </Typography>
    </Box>
  );
}

export default function RevenueSummaryStrip({ data, cashDay, onOpenCashOut, onOpenGroup }) {
  const net = cashDay?.net_cash_movement;
  const tone = netCashTone(net);
  const items = [
    { id: "total", label: "Total Revenue", value: fmtMoney(data?.total_revenue, { empty: "$0.00" }) },
    { id: "rinse", label: "Rinse", value: fmtMoney(data?.rinse?.total), onClick: () => onOpenGroup?.("rinse") },
    { id: "non_rinse", label: "Non-Rinse", value: fmtMoney(data?.non_rinse_revenue?.total ?? data?.non_rinse?.total), onClick: () => onOpenGroup?.("non_rinse") },
    { id: "dhs", label: "DHS", value: fmtMoney(data?.dhs?.total), onClick: () => onOpenGroup?.("dhs") },
    { id: "cash_in", label: "Cash In", value: fmtMoney(cashDay?.total_cash_revenue) },
    { id: "cash_out", label: "Cash Paid Out", value: fmtMoney(cashDay?.cash_paid_out), onClick: onOpenCashOut, tone: cashDay?.cash_paid_out ? "warn" : "neutral" },
    {
      id: "net",
      label: "Net Cash Movement",
      value: fmtMoney(net, { empty: "—" }),
      tone: tone === "negative" ? "negative" : tone === "positive" ? "positive" : "neutral",
    },
  ];

  return (
    <Box
      sx={{
        display: "grid",
        gap: 1,
        gridTemplateColumns: {
          xs: "repeat(2, minmax(0, 1fr))",
          sm: "repeat(3, minmax(0, 1fr))",
          md: "repeat(4, minmax(0, 1fr))",
          lg: "repeat(7, minmax(0, 1fr))",
        },
      }}
    >
      {items.map((item) => (
        <KpiChip key={item.id} label={item.label} value={item.value} onClick={item.onClick} tone={item.tone} />
      ))}
    </Box>
  );
}

export function RevenueGroupCards({ groups, onOpenGroup }) {
  return (
    <Box
      sx={{
        display: "grid",
        gap: 1.25,
        gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", lg: "repeat(3, minmax(0, 1fr))" },
      }}
    >
      {(groups || []).map((g) => (
        <Box
          key={g.id}
          component="button"
          type="button"
          onClick={() => onOpenGroup?.(g.id)}
          sx={{
            textAlign: "left",
            m: 0,
            p: 1.75,
            borderRadius: 2,
            border: "1px solid",
            borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
            bgcolor: "#fff",
            boxShadow: VEEWASH_DASHBOARD.cardShadow,
            cursor: "pointer",
            appearance: "none",
            fontFamily: "inherit",
            WebkitTapHighlightColor: "transparent",
            "&:hover": { borderColor: VEEWASH_DASHBOARD.primaryBlue },
          }}
        >
          <Stack direction="row" justifyContent="space-between" alignItems="baseline" spacing={1}>
            <Typography sx={{ fontWeight: 800, fontSize: 13, letterSpacing: 0.6, color: "#64748b" }}>
              {g.label}
            </Typography>
            <Typography sx={{ fontWeight: 900, fontSize: 22, color: VEEWASH_DASHBOARD.primaryBlueDark, letterSpacing: -0.4 }}>
              {fmtMoney(g.total, { empty: "—" })}
            </Typography>
          </Stack>
          <Typography sx={{ mt: 0.75, fontSize: 13, color: "#64748b", fontWeight: 600 }}>{g.summary}</Typography>
        </Box>
      ))}
    </Box>
  );
}
