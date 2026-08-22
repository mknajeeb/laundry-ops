import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";
import CashPayoutForm from "./CashPayoutForm";
import { fmtMoney, todayEtIso } from "./revenueFormat";

const PERIODS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "week", label: "Week" },
  { id: "month", label: "Month" },
];

/**
 * Cash ledger: summary first → list → Add/Edit returns to summary.
 */
export default function CashLedgerPanel({
  period,
  onPeriodChange,
  summary,
  payouts = [],
  loading = false,
  onCreate,
  onUpdate,
  onDelete,
  busy = false,
}) {
  const [mode, setMode] = useState("summary"); // summary | add | edit
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [formBusy, setFormBusy] = useState(false);
  const [payoutDate, setPayoutDate] = useState(todayEtIso());
  const [purpose, setPurpose] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (mode === "edit" && editing) {
      setPayoutDate(String(editing.payout_date_et || editing.payout_business_date || todayEtIso()).slice(0, 10));
      setPurpose(editing.purpose || "");
      setAmount(editing.amount != null ? String(editing.amount) : "");
      setNote(editing.note || "");
    }
    if (mode === "add") {
      setPayoutDate(todayEtIso());
      setPurpose("");
      setAmount("");
      setNote("");
      setEditing(null);
    }
  }, [mode, editing]);

  const s = summary || {};

  const submitForm = async () => {
    setFormBusy(true);
    try {
      const payload = {
        payout_business_date: payoutDate,
        purpose,
        amount: Number(amount),
        note: note || null,
      };
      if (mode === "edit" && editing?.id) {
        await onUpdate?.(editing.id, payload);
      } else {
        await onCreate?.(payload);
      }
      setMode("summary");
      setEditing(null);
    } finally {
      setFormBusy(false);
    }
  };

  if (mode === "add" || mode === "edit") {
    return (
      <Stack spacing={1.5}>
        <Typography sx={{ fontSize: 18, fontWeight: 900 }}>
          {mode === "edit" ? "Edit Payout" : "Add Payout"}
        </Typography>
        <CashPayoutForm
          payoutDate={payoutDate}
          purpose={purpose}
          amount={amount}
          note={note}
          busy={formBusy || busy}
          onChange={(patch) => {
            if ("payoutDate" in patch) setPayoutDate(patch.payoutDate);
            if ("purpose" in patch) setPurpose(patch.purpose);
            if ("amount" in patch) setAmount(patch.amount);
            if ("note" in patch) setNote(patch.note);
          }}
          onCancel={() => {
            setMode("summary");
            setEditing(null);
          }}
          onSubmit={submitForm}
          labels={{ save: mode === "edit" ? "Save" : "Add Payout" }}
        />
      </Stack>
    );
  }

  return (
    <Stack spacing={1.5} sx={{ pb: 2 }}>
      <Typography sx={{ fontSize: 18, fontWeight: 900, color: "#0f172a" }}>Cash Position</Typography>

      <Box sx={{ display: "flex", gap: 0.6, overflowX: "auto", pb: 0.25 }}>
        {PERIODS.map((p) => {
          const active = period === p.id;
          return (
            <Box
              key={p.id}
              component="button"
              type="button"
              onClick={() => onPeriodChange?.(p.id)}
              sx={{
                appearance: "none",
                border: 0,
                fontFamily: "inherit",
                cursor: "pointer",
                flex: "0 0 auto",
                minHeight: 36,
                px: 1.25,
                borderRadius: 999,
                fontWeight: 800,
                fontSize: 12,
                bgcolor: active ? "#0f172a" : "#e2e8f0",
                color: active ? "#fff" : "#334155",
              }}
            >
              {p.label}
            </Box>
          );
        })}
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 0.75,
          p: 1.25,
          borderRadius: 2,
          bgcolor: "rgba(0,122,145,0.07)",
        }}
      >
        {[
          ["Received", s.cash_received],
          ["Paid Out", s.cash_paid_out],
          ["Net", s.net_cash],
        ].map(([lab, val]) => (
          <Box key={lab}>
            <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>{lab}</Typography>
            <Typography sx={{ fontSize: 18, fontWeight: 900, color: "#0f172a", lineHeight: 1.15 }}>
              {fmtMoney(val)}
            </Typography>
          </Box>
        ))}
      </Box>

      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography sx={{ fontSize: 14, fontWeight: 900 }}>Cash Paid Out</Typography>
        <Button
          variant="contained"
          onClick={() => setMode("add")}
          sx={{ textTransform: "none", fontWeight: 800, bgcolor: "#007a91", minHeight: 40 }}
        >
          + Add Payout
        </Button>
      </Stack>

      {loading ? (
        <Typography sx={{ color: "#64748b", fontSize: 13 }}>Loading…</Typography>
      ) : (
        <Stack spacing={0.75}>
          {(payouts || []).length === 0 ? (
            <Typography sx={{ color: "#64748b", fontSize: 13, py: 2, textAlign: "center" }}>
              No payouts in this period.
            </Typography>
          ) : (
            (payouts || []).map((p) => (
              <Box
                key={p.id}
                sx={{
                  p: 1.15,
                  borderRadius: 2,
                  bgcolor: "#fff",
                  boxShadow: "0 1px 0 rgba(15,23,42,0.06)",
                }}
              >
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 900, fontSize: 15 }}>{p.purpose || "Payout"}</Typography>
                    <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                      {String(p.payout_date_et || p.payout_business_date || "").slice(0, 10)}
                      {p.note ? ` · ${p.note}` : ""}
                    </Typography>
                    <Typography sx={{ fontSize: 16, fontWeight: 900, color: "#007a91", mt: 0.25 }}>
                      {fmtMoney(p.amount)}
                    </Typography>
                  </Box>
                  <Stack direction="row" spacing={0.5}>
                    <Button
                      size="small"
                      sx={{ textTransform: "none", minHeight: 36 }}
                      onClick={() => {
                        setEditing(p);
                        setMode("edit");
                      }}
                    >
                      Edit
                    </Button>
                    <Button
                      size="small"
                      color="error"
                      sx={{ textTransform: "none", minHeight: 36 }}
                      onClick={() => setDeleteTarget(p)}
                    >
                      Delete
                    </Button>
                  </Stack>
                </Stack>
              </Box>
            ))
          )}
        </Stack>
      )}

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>Delete payout?</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 14 }}>
            {deleteTarget?.purpose} · {fmtMoney(deleteTarget?.amount)}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", mt: 1 }}>
            Removes it from the ledger. An audit record is kept.
          </Typography>
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={() => setDeleteTarget(null)} sx={{ textTransform: "none" }}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            sx={{ textTransform: "none", fontWeight: 800 }}
            onClick={async () => {
              await onDelete?.(deleteTarget);
              setDeleteTarget(null);
            }}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
