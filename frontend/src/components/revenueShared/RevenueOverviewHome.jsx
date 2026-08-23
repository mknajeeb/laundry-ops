import { Box, CircularProgress, Stack, Typography } from "@mui/material";
import PlanningDatePicker from "../datetime/PlanningDatePicker";
import SectionStatusCard from "./SectionStatusCard";
import { fmtMoney } from "./revenueFormat";

function sectionStatus(section, t) {
  if (!section) {
    return { label: t?.("mobileOps.revenue.needsEntry") || "Needs entry", tone: "warn" };
  }
  if (section.complete || section.status === "complete" || section.status === "no_activity") {
    return { label: t?.("mobileOps.revenue.savedCheck") || "Saved ✓", tone: "ok" };
  }
  if (section.status === "draft" || section.entered) {
    return { label: t?.("mobileOps.revenue.saving")?.replace("…", "") || "Draft", tone: "neutral" };
  }
  return { label: t?.("mobileOps.revenue.needsEntry") || "Needs entry", tone: "warn" };
}

function moneyOrDash(v) {
  return v == null || v === "" ? null : fmtMoney(v);
}

/**
 * Compact operational home — summary strip + tappable section cards.
 * Consumes bootstrap/daily payloads; does not duplicate DHS schedule logic.
 */
export default function RevenueOverviewHome({
  dateEt,
  onDateChange,
  dateLabel,
  loading,
  nonRinse,
  rinse,
  cashToday,
  dailyCompleteness,
  dhsBoard,
  cashTab,
  t,
  onOpenSection,
}) {
  const sections = Object.fromEntries((dailyCompleteness?.sections || []).map((s) => [s.key, s]));
  const ss = nonRinse?.self_service || {};
  const dO = nonRinse?.drop_off || {};
  const wf = rinse?.wf || {};
  const hd = rinse?.hd || {};

  const revenueParts = [ss.total, dO.total, wf.revenue, hd.revenue].filter((v) => v != null);
  const totalRevenue =
    revenueParts.length > 0
      ? revenueParts.reduce((a, b) => a + Number(b || 0), 0)
      : null;
  const cashOut = cashToday?.cash_paid_out ?? cashTab?.summary?.cash_paid_out;
  const completeLabel = dailyCompleteness?.label || "—";

  const dhsDue = (dhsBoard?.due || []).length;
  const dhsOverdue = (dhsBoard?.overdue || []).length;
  const dhsEntered = (dhsBoard?.due || []).filter((r) => r.volume_lbs != null || r.revenue != null).length;
  const dhsTotalLb = [...(dhsBoard?.overdue || []), ...(dhsBoard?.due || [])]
    .reduce((sum, r) => sum + Number(r.volume_lbs || 0), 0);
  const dhsTotalRev = [...(dhsBoard?.overdue || []), ...(dhsBoard?.due || [])]
    .reduce((sum, r) => sum + Number(r.revenue || 0), 0);
  const dhsOpen = dhsDue + dhsOverdue;

  const payoutCount = (cashTab?.payouts || []).length;
  const payoutTotal = cashTab?.summary?.cash_paid_out ?? cashOut;

  if (loading) {
    return (
      <Box sx={{ py: 5, display: "grid", placeItems: "center" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  return (
    <Stack spacing={1.25} sx={{ pb: 2 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 1, flexWrap: "wrap" }}>
        <Typography sx={{ fontWeight: 900, fontSize: 15, color: "#0f172a" }}>
          {t?.("mobileOps.revenue.todayLabel") || "Today"} · {dateLabel || dateEt}
        </Typography>
        {onDateChange ? (
          <Box sx={{ minWidth: 160 }}>
            <PlanningDatePicker value={dateEt} onChange={onDateChange} label="" />
          </Box>
        ) : null}
      </Box>

      <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#475569" }}>
        {(t?.("mobileOps.revenue.summaryLine") || "Revenue {revenue} · Cash Out {cashOut} · {complete} complete")
          .replace("{revenue}", moneyOrDash(totalRevenue) || "—")
          .replace("{cashOut}", moneyOrDash(cashOut) || "—")
          .replace("{complete}", completeLabel)}
      </Typography>

      <Stack spacing={1}>
        <SectionStatusCard
          title={t?.("mobileOps.revenue.selfService") || "Self Service"}
          primary={moneyOrDash(ss.total)}
          secondary={
            ss.cash != null || ss.card != null
              ? `${t?.("mobileOps.revenue.cash") || "Cash"} ${moneyOrDash(ss.cash) || "—"} · ${t?.("mobileOps.revenue.card") || "Card"} ${moneyOrDash(ss.card) || "—"}`
              : null
          }
          statusLabel={sectionStatus(sections.self_service, t).label}
          statusTone={sectionStatus(sections.self_service, t).tone}
          onClick={() => onOpenSection?.("self_service")}
        />
        <SectionStatusCard
          title={t?.("mobileOps.revenue.dropOff") || "Drop Off"}
          primary={moneyOrDash(dO.total)}
          secondary={
            dO.cash != null || dO.card != null
              ? `${t?.("mobileOps.revenue.cash") || "Cash"} ${moneyOrDash(dO.cash) || "—"} · ${t?.("mobileOps.revenue.card") || "Card"} ${moneyOrDash(dO.card) || "—"}`
              : null
          }
          statusLabel={sectionStatus(sections.drop_off, t).label}
          statusTone={sectionStatus(sections.drop_off, t).tone}
          onClick={() => onOpenSection?.("drop_off")}
        />
        <SectionStatusCard
          title={t?.("mobileOps.revenue.dhs") || "DHS"}
          primary={
            dhsTotalRev > 0
              ? fmtMoney(dhsTotalRev)
              : dhsOpen > 0
                ? `${dhsOpen} open`
                : null
          }
          secondary={
            dhsTotalLb > 0
              ? `${Number(dhsTotalLb).toLocaleString()} lb${dhsOpen ? ` · ${dhsEntered}/${dhsOpen} entered` : ""}`
              : dhsOverdue > 0
                ? `${dhsOverdue} overdue`
                : null
          }
          statusLabel={
            dhsOpen === 0
              ? t?.("mobileOps.revenue.noActivity") || "No Activity"
              : dhsEntered >= dhsOpen
                ? t?.("mobileOps.revenue.savedCheck") || "Saved ✓"
                : t?.("mobileOps.revenue.needsEntry") || "Needs entry"
          }
          statusTone={dhsEntered >= dhsOpen && dhsOpen > 0 ? "ok" : dhsOverdue > 0 ? "warn" : "neutral"}
          onClick={() => onOpenSection?.("dhs")}
        />
        <SectionStatusCard
          title={t?.("mobileOps.revenue.cashPaidOut") || "Cash Paid Out"}
          primary={moneyOrDash(payoutTotal)}
          secondary={
            payoutCount
              ? (t?.("mobileOps.revenue.payoutEntries") || "{count} entries").replace("{count}", String(payoutCount))
              : null
          }
          statusLabel={payoutCount ? `${payoutCount}` : t?.("mobileOps.revenue.needsEntry") || "Needs entry"}
          statusTone={payoutCount ? "ok" : "neutral"}
          onClick={() => onOpenSection?.("cash")}
        />
        <SectionStatusCard
          title={t?.("mobileOps.revenue.hangDry") || "Hang Dry"}
          primary={moneyOrDash(hd.revenue)}
          secondary={
            hd.orders != null
              ? (t?.("mobileOps.revenue.hdCompletedCount") || "{count} completed").replace(
                  "{count}",
                  String(hd.orders),
                )
              : null
          }
          statusLabel={sectionStatus(sections.rinse_hd, t).label}
          statusTone={sectionStatus(sections.rinse_hd, t).tone}
          onClick={() => onOpenSection?.("rinse_hd")}
        />
      </Stack>
    </Stack>
  );
}
