import { useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import PlanningDatePicker from "../../datetime/PlanningDatePicker";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";
import { CASH_PERIODS, fmtMoney, netCashTone } from "./revenueFormat";

function Row({ label, value, bold, tone }) {
  const color =
    tone === "negative"
      ? "#b91c1c"
      : tone === "positive"
        ? VEEWASH_DASHBOARD.tealDark
        : bold
          ? VEEWASH_DASHBOARD.primaryBlueDark
          : "#0f172a";
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="center">
      <Typography sx={{ fontSize: 13, color: "#64748b", fontWeight: bold ? 700 : 500 }}>{label}</Typography>
      <Typography sx={{ fontSize: bold ? 16 : 14, fontWeight: bold ? 800 : 700, color }}>{value}</Typography>
    </Stack>
  );
}

export default function CashActivityPanel({
  period,
  onPeriodChange,
  customStart,
  customEnd,
  onCustomStart,
  onCustomEnd,
  loading,
  activity,
  onAddPayout,
  onDeletePayout,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [payoutsOpen, setPayoutsOpen] = useState(false);
  const payouts = activity?.payouts || activity?.cash_out?.payouts || [];
  const netTone = netCashTone(activity?.net_cash_movement);

  return (
    <Box
      sx={{
        border: "1px solid #e5e7eb",
        borderRadius: 2,
        bgcolor: "#fff",
        p: { xs: 1.5, sm: 2 },
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography sx={{ fontWeight: 800, fontSize: 15 }}>Cash Activity</Typography>
        <IconButton size="small" onClick={onAddPayout} aria-label="Add cash payout">
          <AddIcon fontSize="small" />
        </IconButton>
      </Stack>

      <Tabs
        value={period}
        onChange={(_, v) => onPeriodChange?.(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ mb: 1.5, minHeight: 36, "& .MuiTab-root": { minHeight: 36, fontWeight: 700, fontSize: 13 } }}
      >
        {CASH_PERIODS.map((p) => (
          <Tab key={p.id} value={p.id} label={p.label} />
        ))}
      </Tabs>

      {period === "custom" ? (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1.5 }}>
          <PlanningDatePicker value={customStart} onChange={onCustomStart} label="Start (ET)" />
          <PlanningDatePicker value={customEnd} onChange={onCustomEnd} label="End (ET)" />
        </Stack>
      ) : null}

      {loading ? (
        <CircularProgress size={24} />
      ) : (
        <Stack spacing={1.25}>
          <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#94a3b8", textTransform: "uppercase" }}>
            Cash In
          </Typography>
          <Row label="Self Service" value={fmtMoney(activity?.self_service_cash ?? activity?.cash_in?.self_service)} />
          <Row label="Drop Off" value={fmtMoney(activity?.drop_off_cash ?? activity?.cash_in?.drop_off)} />
          <Row label="Total Cash In" value={fmtMoney(activity?.total_cash_revenue ?? activity?.cash_in?.total)} bold />

          <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#94a3b8", textTransform: "uppercase", pt: 0.5 }}>
            Cash Out
          </Typography>
          <Box
            component="button"
            type="button"
            onClick={() => setPayoutsOpen(true)}
            sx={{
              display: "block",
              width: "100%",
              textAlign: "left",
              m: 0,
              p: 0,
              border: "none",
              bgcolor: "transparent",
              cursor: "pointer",
              appearance: "none",
              fontFamily: "inherit",
            }}
          >
            <Row label="Cash Paid Out" value={fmtMoney(activity?.cash_paid_out)} tone="warn" />
            <Typography sx={{ fontSize: 11, color: VEEWASH_DASHBOARD.primaryBlue, fontWeight: 700, mt: 0.25 }}>
              View payouts →
            </Typography>
          </Box>

          <Row
            label="Net Cash Movement"
            value={fmtMoney(activity?.net_cash_movement)}
            bold
            tone={netTone === "negative" ? "negative" : netTone === "positive" ? "positive" : undefined}
          />
          <Typography sx={{ fontSize: 11, color: "#94a3b8" }}>
            Not Cash on Hand — opening cash / deposits are not tracked yet.
          </Typography>
        </Stack>
      )}

      <Drawer
        anchor={isMobile ? "bottom" : "right"}
        open={payoutsOpen}
        onClose={() => setPayoutsOpen(false)}
        PaperProps={{
          sx: {
            width: { xs: "100%", sm: 400 },
            ...(isMobile ? { maxHeight: "85vh", borderTopLeftRadius: 16, borderTopRightRadius: 16 } : {}),
          },
        }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ p: 1.5, borderBottom: "1px solid #e5e7eb" }}>
          <Typography sx={{ fontWeight: 800 }}>Payouts</Typography>
          <Button size="small" onClick={() => setPayoutsOpen(false)} sx={{ textTransform: "none" }}>
            Close
          </Button>
        </Stack>
        <Box sx={{ p: 1.5 }}>
          {!payouts.length ? (
            <Typography sx={{ fontSize: 13, color: "#64748b" }}>No payouts in this period.</Typography>
          ) : (
            <Stack spacing={1}>
              {payouts.map((p) => (
                <Stack
                  key={p.id}
                  direction="row"
                  justifyContent="space-between"
                  alignItems="flex-start"
                  sx={{ p: 1.25, borderRadius: 1.5, bgcolor: VEEWASH_DASHBOARD.snapshotBg, border: "1px solid #e5e7eb" }}
                >
                  <Box sx={{ minWidth: 0, pr: 1 }}>
                    <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{p.purpose}</Typography>
                    <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                      {p.payout_business_date || p.date_et} · {fmtMoney(p.amount)}
                      {p.entered_by ? ` · ${p.entered_by}` : ""}
                    </Typography>
                    {p.note ? (
                      <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 0.25 }}>{p.note}</Typography>
                    ) : null}
                  </Box>
                  <IconButton size="small" onClick={() => onDeletePayout?.(p.id)} aria-label="Delete payout">
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Stack>
              ))}
            </Stack>
          )}
          <Button
            fullWidth
            startIcon={<AddIcon />}
            onClick={onAddPayout}
            sx={{ mt: 1.5, textTransform: "none", fontWeight: 700 }}
          >
            Add payout
          </Button>
        </Box>
      </Drawer>
    </Box>
  );
}
