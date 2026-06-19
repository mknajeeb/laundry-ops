import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import {
  confirmPayoutPayment,
  getPayoutAccountantQueue,
  getPayoutBatchDetails,
} from "../api";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

function statusLabel(batch) {
  if (batch.payout_workflow?.accountant_payment_confirmed) return "Confirmed";
  return "Pending";
}

export default function AccountantPaymentQueuePanel() {
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  const loadQueue = useCallback(async () => {
    setError("");
    try {
      const res = await getPayoutAccountantQueue();
      setItems(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load queue");
    }
  }, []);

  const loadDetail = useCallback(async (id) => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await getPayoutBatchDetails(id);
      setDetail(res.data);
      setSelectedId(id);
    } catch (e) {
      setError(e.response?.data?.error || "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const confirmPayment = async () => {
    if (!selectedId) return;
    setError("");
    setInfo("");
    try {
      const res = await confirmPayoutPayment(selectedId);
      setDetail(res.data);
      setInfo("Payment confirmed.");
      await loadQueue();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Confirm failed");
    }
  };

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>{info}</Alert>
      ) : null}

      <Paper sx={{ p: 2, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}>
        <Typography variant="h6" sx={{ color: VEEWASH_BRAND.primaryDark, mb: 2 }}>
          Payment confirmation
        </Typography>

        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Batch</TableCell>
                <TableCell>Period</TableCell>
                <TableCell>Category</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Total</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((b) => (
                <TableRow
                  key={b.id}
                  hover
                  selected={selectedId === b.id}
                  onClick={() => loadDetail(b.id)}
                  sx={{ cursor: "pointer" }}
                >
                  <TableCell>{b.batch_name}</TableCell>
                  <TableCell>{b.pay_period_start} – {b.pay_period_end}</TableCell>
                  <TableCell>{b.worker_category}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={statusLabel(b)}
                      color={b.payout_workflow?.accountant_payment_confirmed ? "success" : "warning"}
                    />
                  </TableCell>
                  <TableCell align="right">
                    ${Number(b.total_payout_amount || 0).toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
              {!items.length ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Typography variant="body2" color="text.secondary">
                      No batches pending payment confirmation.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {detail ? (
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
            <Typography variant="subtitle1" fontWeight={600}>
              {detail.batch_name} ({detail.pay_period_start} – {detail.pay_period_end})
            </Typography>
            {detail.payout_workflow?.can_edit_details === false &&
            !detail.payout_workflow?.accountant_payment_confirmed ? (
              <Button
                variant="contained"
                onClick={confirmPayment}
                disabled={loading}
                sx={{ bgcolor: VEEWASH_BRAND.primary }}
              >
                Confirm payment
              </Button>
            ) : null}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {detail.lines?.length || 0} employees · Gross $
            {Number(detail.summary?.gross_total || 0).toFixed(2)}
          </Typography>
        </Paper>
      ) : null}
    </Stack>
  );
}
