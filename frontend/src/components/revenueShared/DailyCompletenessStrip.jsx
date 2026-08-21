import { Box, Stack, Typography } from "@mui/material";
import { fmtMoney } from "./revenueFormat";

const STATUS_TONE = {
  complete: "#0f766e",
  entered: "#0f766e",
  draft: "#0369a1",
  no_activity: "#64748b",
  missing: "#d97706",
  pending: "#d97706",
  overdue: "#b91c1c",
};

function statusLabel(status) {
  if (status === "complete" || status === "entered") return "Complete";
  if (status === "draft") return "Draft";
  if (status === "no_activity") return "No Activity";
  if (status === "pending") return "Pending";
  if (status === "overdue") return "Overdue";
  if (status === "missing") return "Missing";
  return status || "—";
}

function formatDayHelp(iso) {
  if (!iso) return "";
  try {
    const [y, m, d] = String(iso).split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function CompactRow({ label, amount, status, onClick }) {
  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 1,
        width: "100%",
        border: "none",
        bgcolor: "transparent",
        textAlign: "left",
        py: 0.85,
        px: 0.25,
        minHeight: 44,
        cursor: "pointer",
        borderRadius: 1,
        "&:active": { bgcolor: "rgba(0,122,145,0.06)" },
      }}
    >
      <Typography sx={{ flex: 1, fontWeight: 800, fontSize: 14, color: "#0f172a" }}>{label}</Typography>
      <Typography sx={{ fontWeight: 700, fontSize: 13, color: "#64748b", minWidth: 56, textAlign: "right" }}>
        {amount != null && amount !== "" ? amount : "—"}
      </Typography>
      <Typography
        sx={{
          fontSize: 12,
          fontWeight: 800,
          color: STATUS_TONE[status] || "#64748b",
          minWidth: 72,
          textAlign: "right",
        }}
      >
        {statusLabel(status)}
      </Typography>
    </Box>
  );
}

/**
 * Entry checklist: Daily required 4/4 + DHS due summary (not in denominator).
 */
export default function DailyCompletenessStrip({
  completeness,
  dhsDay,
  amounts,
  onOpenSection,
  onOpenDhsAccount,
  onOpenCash,
  cashAmount,
}) {
  const sections = completeness?.sections || [];
  const dayIso = completeness?.processing_date_et;
  const dhs = dhsDay || {};
  const dhsAccounts = dhs.accounts || [];

  if (!sections.length && !dhsAccounts.length) return null;

  return (
    <Stack spacing={1.25}>
      <Box
        sx={{
          p: 1.25,
          borderRadius: 2,
          border: "1px solid rgba(0,151,178,0.28)",
          bgcolor: "#fff",
        }}
      >
        <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.4, color: "#64748b", textTransform: "uppercase" }}>
          Daily required
        </Typography>
        <Typography sx={{ mt: 0.2, fontWeight: 900, fontSize: 18, color: "#0f172a" }}>
          {completeness?.label || "0/4"} complete
        </Typography>
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#64748b" }}>
          Expected for {formatDayHelp(dayIso)}
        </Typography>
        <Stack spacing={0} sx={{ mt: 0.5 }}>
          {sections.map((s) => (
            <CompactRow
              key={s.key}
              label={s.label}
              amount={amounts?.[s.key] != null ? fmtMoney(amounts[s.key]) : null}
              status={s.status}
              onClick={() => onOpenSection?.(s)}
            />
          ))}
        </Stack>
      </Box>

      <Box
        sx={{
          p: 1.25,
          borderRadius: 2,
          border: "1px solid rgba(0,151,178,0.22)",
          bgcolor: "#fff",
        }}
      >
        <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.4, color: "#64748b", textTransform: "uppercase" }}>
          DHS
        </Typography>
        {dhs.nothing_due ? (
          <Typography sx={{ mt: 0.35, fontWeight: 800, fontSize: 15, color: "#64748b" }}>Nothing due</Typography>
        ) : (
          <>
            <Typography sx={{ mt: 0.2, fontWeight: 900, fontSize: 16, color: "#0f172a" }}>
              {dhs.complete ?? 0}/{dhs.due ?? 0} due complete
            </Typography>
            <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#64748b" }}>
              {dhs.due ?? 0} accounts due based on pickup schedule
            </Typography>
            <Stack spacing={0} sx={{ mt: 0.5 }}>
              {dhsAccounts.map((a) => (
                <CompactRow
                  key={`${a.account_id}-${a.scheduled_pickup_date}`}
                  label={a.name}
                  amount={
                    a.entry?.amount != null
                      ? fmtMoney(a.entry.amount)
                      : null
                  }
                  status={a.resolved ? "complete" : a.status}
                  onClick={() => onOpenDhsAccount?.(a)}
                />
              ))}
            </Stack>
          </>
        )}
      </Box>

      {onOpenCash ? (
        <Box
          sx={{
            p: 1.25,
            borderRadius: 2,
            border: "1px solid #e5e7eb",
            bgcolor: "#fff",
          }}
        >
          <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.4, color: "#64748b", textTransform: "uppercase" }}>
            Optional
          </Typography>
          <CompactRow
            label="Cash Paid Out"
            amount={cashAmount != null ? fmtMoney(cashAmount) : null}
            status=""
            onClick={onOpenCash}
          />
        </Box>
      ) : null}
    </Stack>
  );
}
