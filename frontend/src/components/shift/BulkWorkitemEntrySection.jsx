import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { postVeewashStep1Correction } from "../../api";

const NO_CHARGE_REASONS = [
  "Customer cancelled",
  "False alarm",
  "Duplicate scan",
  "Other",
];

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

/**
 * Bulk Workitems entry UI for Review drawer.
 * Shows active catalog with +/- qty; or No Chargeable Bulk Items + reason.
 */
export default function BulkWorkitemEntrySection({
  bag,
  selectedDateEt,
  catalog = [],
  readOnly = false,
  onSaved,
  onError,
}) {
  const reasons = bag?.reason_codes || [];
  const needsBulk = reasons.includes("WF_BULK_WORKITEM_REVIEW");
  const scan = bag?.bulk_workitem_scan || {};
  const existing = bag?.bulk_workitems || [];
  const serviceType = String(bag?.service_type || "").toUpperCase();

  const initialQty = useMemo(() => {
    const map = {};
    for (const wi of catalog) map[wi.id] = 0;
    for (const line of existing) {
      if (line.workitem_id != null) map[line.workitem_id] = Number(line.quantity) || 0;
    }
    return map;
  }, [catalog, existing]);

  const [qty, setQty] = useState(initialQty);
  const [noCharge, setNoCharge] = useState(
    String(bag?.bulk_resolution?.resolution_type || "") === "no_charge"
  );
  const [noChargeReason, setNoChargeReason] = useState(
    bag?.bulk_resolution?.no_charge_reason || ""
  );
  const [otherReason, setOtherReason] = useState("");
  const [saveReason, setSaveReason] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setQty(initialQty);
    setNoCharge(String(bag?.bulk_resolution?.resolution_type || "") === "no_charge");
    setNoChargeReason(bag?.bulk_resolution?.no_charge_reason || "");
  }, [bag?.bag_id, initialQty, bag?.bulk_resolution]);

  // Bulk workitem entry is WF-only — never show under HD.
  if (serviceType === "HD") {
    return null;
  }
  if (!needsBulk && !existing.length && !scan?.count) {
    return null;
  }

  const bump = (id, delta) => {
    setQty((q) => ({ ...q, [id]: Math.max(0, Number(q[id] || 0) + delta) }));
  };

  const lines = catalog.map((wi) => {
    const q = Number(qty[wi.id] || 0);
    const price = Number(wi.current_unit_price) || 0;
    return {
      workitem_id: wi.id,
      name: wi.name,
      unit_price: price,
      quantity: q,
      line_total: Math.round(price * q * 100) / 100,
    };
  });
  // Historical inactive lines still visible
  for (const line of existing) {
    if (line.workitem_id != null && !catalog.some((c) => c.id === line.workitem_id)) {
      const q = Number(qty[line.workitem_id] ?? line.quantity ?? 0);
      const price = Number(line.unit_price) || 0;
      lines.push({
        workitem_id: line.workitem_id,
        name: `${line.workitem_name || "Workitem"} (inactive)`,
        unit_price: price,
        quantity: q,
        line_total: Math.round(price * q * 100) / 100,
        historical: true,
      });
    }
  }

  const total = lines.reduce((s, l) => s + (l.line_total || 0), 0);

  const submit = async () => {
    setSaving(true);
    try {
      const reason =
        noCharge
          ? noChargeReason === "Other"
            ? otherReason.trim()
            : noChargeReason.trim()
          : saveReason.trim();
      if (!reason) {
        onError?.(noCharge ? "No-charge reason is required" : "Correction reason is required");
        return;
      }
      const body = {
        action: "save_bulk_workitems",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason,
        no_chargeable: noCharge,
        no_charge_reason: noCharge ? reason : undefined,
        items: noCharge
          ? []
          : lines
              .filter((l) => l.quantity > 0)
              .map((l) => ({ workitem_id: l.workitem_id, quantity: l.quantity })),
      };
      const res = await postVeewashStep1Correction(body);
      if (!res?.data?.ok) {
        onError?.(res?.data?.error || "Failed to save bulk workitems");
        return;
      }
      onSaved?.(res.data);
    } catch (e) {
      onError?.(e?.response?.data?.error || e?.message || "Failed to save bulk workitems");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ mt: 1.5, p: 1.25, border: "1px solid #e2e8f0", borderRadius: 1 }}>
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.5 }}>
        Bulk Workitems
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        Reason: Bulk Workitems Require Review
        {scan?.first_at ? ` · create-workitem-bulk @ ${String(scan.first_at).slice(0, 19)}` : ""}
        {scan?.employee ? ` · ${scan.employee}` : ""}
      </Typography>

      {!noCharge
        ? lines.map((line) => (
            <Box key={line.workitem_id} sx={{ mb: 1.25 }}>
              <Typography fontWeight={700}>{line.name}</Typography>
              <Typography variant="caption" display="block">
                Price: ${money(line.unit_price)}
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ my: 0.5 }}>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={readOnly}
                  onClick={() => bump(line.workitem_id, -1)}
                >
                  −
                </Button>
                <Typography fontFamily="monospace" sx={{ minWidth: 24, textAlign: "center" }}>
                  {line.quantity}
                </Typography>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={readOnly}
                  onClick={() => bump(line.workitem_id, 1)}
                >
                  +
                </Button>
              </Stack>
              <Typography variant="caption">Line Total: ${money(line.line_total)}</Typography>
            </Box>
          ))
        : null}

      {!noCharge ? (
        <Typography fontWeight={800} sx={{ mt: 1 }}>
          Bulk Item Total ${money(total)}
        </Typography>
      ) : null}

      <FormControlLabel
        sx={{ mt: 1 }}
        control={
          <Checkbox
            checked={noCharge}
            disabled={readOnly}
            onChange={(e) => setNoCharge(e.target.checked)}
          />
        }
        label="No Chargeable Bulk Items"
      />

      {noCharge ? (
        <Stack spacing={1} sx={{ mt: 0.5 }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Reason</InputLabel>
            <Select
              label="Reason"
              value={NO_CHARGE_REASONS.includes(noChargeReason) ? noChargeReason : noChargeReason ? "Other" : ""}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "Other") {
                  setNoChargeReason("Other");
                } else {
                  setNoChargeReason(v);
                  setOtherReason("");
                }
              }}
              disabled={readOnly}
            >
              {NO_CHARGE_REASONS.map((r) => (
                <MenuItem key={r} value={r}>
                  {r}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {(noChargeReason === "Other" ||
            (noChargeReason && !NO_CHARGE_REASONS.includes(noChargeReason))) && (
            <TextField
              size="small"
              label="Other reason"
              value={otherReason || (NO_CHARGE_REASONS.includes(noChargeReason) ? "" : noChargeReason)}
              onChange={(e) => setOtherReason(e.target.value)}
              disabled={readOnly}
            />
          )}
        </Stack>
      ) : (
        <TextField
          size="small"
          fullWidth
          required
          label="Correction reason"
          value={saveReason}
          onChange={(e) => setSaveReason(e.target.value)}
          disabled={readOnly}
          sx={{ mt: 1 }}
        />
      )}

      {!readOnly ? (
        <Button
          variant="contained"
          size="small"
          sx={{ mt: 1.25 }}
          disabled={saving}
          onClick={submit}
        >
          {saving ? "Saving…" : "Save bulk workitems"}
        </Button>
      ) : (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          Shift is closed — reopen to edit bulk workitems.
        </Typography>
      )}

      {(bag.bulk_audits || []).length > 0 ? (
        <Box sx={{ mt: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700}>
            Bulk correction history
          </Typography>
          {(bag.bulk_audits || []).slice(0, 5).map((a, i) => (
            <Typography key={i} variant="caption" display="block">
              {String(a.created_at || "").slice(0, 19)} · {a.actor_display_name || "—"} ·{" "}
              {a.previous_total} → {a.new_total} · {a.reason}
            </Typography>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}
