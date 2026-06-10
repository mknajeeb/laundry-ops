import { Alert, Box, Paper, Stack, Typography } from "@mui/material";

function ComparisonRow({ label, vendorHome, internalScan, difference, status }) {
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.5 }}>
        {label}
      </Typography>
      <Typography variant="body2">
        Vendor Home: {vendorHome ?? "—"}
      </Typography>
      <Typography variant="body2">
        Internal Scan: {internalScan ?? "—"}
      </Typography>
      <Typography variant="body2" color="warning.dark" fontWeight={700}>
        {status ?? "Needs Review"}
        {difference != null ? ` · Δ ${difference > 0 ? "+" : ""}${difference}` : ""}
      </Typography>
    </Box>
  );
}

export default function VendorHomeComparisonSection({ parity, presence }) {
  if (!parity) return null;

  const comp = parity.comparison || {};
  const at = comp.at_veewash || {};
  const due = comp.due_today || {};
  const presenceInfo = presence || parity.presence || {};

  return (
    <Paper elevation={0} sx={{ p: { xs: 1.25, md: 1.5 }, borderRadius: 2, border: "1px solid", borderColor: "divider", mb: 2.5 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>
        Vendor Home vs Internal Scan View
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Vendor Home uses portal processing state; Internal Scan uses local scan-completion rules.
      </Typography>

      {parity.reason ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {parity.reason}
        </Alert>
      ) : null}

      {(presenceInfo.at_vendor_active === 0 && presenceInfo.rfv_active === 0) ? (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          At Vendor presence rows: {presenceInfo.at_vendor_active ?? 0} · RFV presence rows: {presenceInfo.rfv_active ?? 0}
          {" — "}Portal presence not loaded — Vendor Home parity cannot be record-level reconciled.
        </Alert>
      ) : null}

      <ComparisonRow
        label="At VeeWash"
        vendorHome={`${parity.at_veewash_total ?? "—"} total / ${parity.at_veewash_yet_to_process ?? "—"} pending / ${parity.at_veewash_processed ?? "—"} processed`}
        internalScan={`${at.internal_scan_total ?? parity.internal_scan?.at_facility_total ?? "—"} total / ${at.internal_scan_in_progress ?? parity.internal_scan?.in_progress ?? "—"} pending / ${parity.internal_scan?.completed_still_at_facility ?? "—"} completed`}
        difference={at.difference_total}
        status={at.status}
      />
      <ComparisonRow
        label="Due Today"
        vendorHome={`${parity.due_today_total ?? "—"} total / ${parity.due_today_yet_to_process ?? "—"} pending / ${parity.due_today_processed ?? "—"} processed`}
        internalScan={`${due.internal_scan_total ?? parity.internal_scan?.due_today_total ?? "—"} total / ${due.internal_scan_pending ?? parity.internal_scan?.due_today_yet_to_process ?? "—"} pending / ${parity.internal_scan?.due_today_completed ?? "—"} completed`}
        difference={due.difference_total}
        status={due.status}
      />
    </Paper>
  );
}
