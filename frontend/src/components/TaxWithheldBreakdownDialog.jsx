import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Typography,
} from "@mui/material";
import {
  formatTaxWithheldDisplay,
  hasTaxWithheldBreakdown,
  isPayoutDetailsFinalized,
  TAX_WITHHELD_BREAKDOWN_LABELS,
} from "../payroll/payoutSettlementDisplay";

function fmtMoney(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "$0.00";
  return `$${n.toFixed(2)}`;
}

export default function TaxWithheldBreakdownDialog({ open, onClose, line, workerName }) {
  const finalized = isPayoutDetailsFinalized(line);
  const breakdown = line?.tax_withheld_breakdown;
  const hasDetails = hasTaxWithheldBreakdown(line);
  const displayTotal = formatTaxWithheldDisplay(line, { pendingLabel: "$0.00" });

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Estimated withholding{workerName ? ` — ${workerName}` : ""}</DialogTitle>
      <DialogContent>
        {!finalized || !hasDetails ? (
          <Typography variant="body2" color="text.secondary">
            No estimated withholding recorded for this payout.
          </Typography>
        ) : (
          <Table size="small">
            <TableBody>
              {TAX_WITHHELD_BREAKDOWN_LABELS.map(({ key, label }) => (
                <TableRow key={key}>
                  <TableCell>{label}</TableCell>
                  <TableCell align="right">{fmtMoney(breakdown?.[key])}</TableCell>
                </TableRow>
              ))}
              {!breakdown?.total_tax_withheld && displayTotal !== "$0.00" ? (
                <TableRow>
                  <TableCell sx={{ fontWeight: 700 }}>Total estimated withholding</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>
                    {displayTotal}
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
