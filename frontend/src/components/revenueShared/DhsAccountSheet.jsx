import { useMemo, useState } from "react";
import {
  Box,
  Button,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import PlanningDatePicker from "../datetime/PlanningDatePicker";
import MoneyAmountField from "./MoneyAmountField";
import SaveStatusChip from "./SaveStatusChip";
import { fmtMoney, parseMoneyInput } from "./revenueFormat";

function calcPreview(account, volume) {
  const pricing = account?.pricing || {};
  const mode = account?.revenue_mode || "calculated";
  if (mode === "absolute") return null;
  const vol = parseMoneyInput(volume);
  if (vol == null) return null;
  const method = pricing.pricing_method || "flat_lb";
  if (method === "flat_lb") {
    const rate = Number(pricing.rate_per_unit || 0);
    return Number((vol * rate).toFixed(2));
  }
  return null;
}

function buildBody(account, draft, entryDate, showOverride, preview) {
  const mode = account?.revenue_mode || "calculated";
  const isAbsolute = mode === "absolute";
  const allowOverride = account?.allow_override !== false;
  const body = {
    account_id: account.account_id,
    dr_commercial_account_id: account.dr_commercial_account_id,
    revenue_mode: mode,
    use_revenue_override: Boolean(showOverride && allowOverride),
    pickup_date: account?.use_pickup_date ? draft?.pickup_date || null : null,
    processing_date:
      account?.use_processing_date !== false
        ? draft?.processing_date || entryDate || null
        : null,
    delivery_date: account?.use_delivery_date ? draft?.delivery_date || null : null,
    scheduled_pickup_date: draft?.scheduled_pickup_date || null,
    scheduled_delivery_date: draft?.scheduled_delivery_date || null,
    date_override: Boolean(
      (draft?.scheduled_pickup_date && draft?.pickup_date && draft.pickup_date !== draft.scheduled_pickup_date) ||
        (draft?.scheduled_delivery_date &&
          draft?.delivery_date &&
          draft.delivery_date !== draft.scheduled_delivery_date),
    ),
  };
  if (isAbsolute) {
    body.revenue = parseMoneyInput(draft?.revenue);
  } else if (showOverride && allowOverride) {
    body.volume = parseMoneyInput(draft?.volume);
    body.revenue = parseMoneyInput(draft?.revenue);
  } else {
    body.volume = parseMoneyInput(draft?.volume);
    body.revenue = preview;
  }
  return body;
}

/**
 * Single DHS commercial account entry — autosave draft; Complete finalizes obligation.
 */
export default function DhsAccountSheet({
  account,
  entryDate,
  draft,
  onChange,
  onAutosave,
  onComplete,
  saving,
  completeBusy,
  saveState,
  saveLabels,
  labels = {},
}) {
  const [showOverride, setShowOverride] = useState(Boolean(draft?.use_revenue_override));
  const mode = account?.revenue_mode || "calculated";
  const isAbsolute = mode === "absolute";
  const allowOverride = account?.allow_override !== false;
  const preview = useMemo(() => calcPreview(account, draft?.volume), [account, draft?.volume]);

  const processingValue =
    draft?.processing_date ||
    (account?.use_processing_date !== false ? entryDate : "") ||
    "";

  const setField = (key, val) => {
    const next = { ...draft, [key]: val };
    onChange?.(next);
    onAutosave?.(buildBody(account, next, entryDate, showOverride, calcPreview(account, next?.volume)));
  };

  return (
    <Stack spacing={1.5} sx={{ pb: 12 }}>
      <Typography sx={{ fontSize: 18, fontWeight: 900 }}>{account?.name}</Typography>

      {draft?.scheduled_pickup_date || draft?.scheduled_delivery_date ? (
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#64748b" }}>
          Schedule defaults
          {draft?.scheduled_pickup_date ? ` · Pickup ${draft.scheduled_pickup_date}` : ""}
          {draft?.scheduled_delivery_date ? ` · Delivery ${draft.scheduled_delivery_date}` : ""}
          {" "}(editable)
        </Typography>
      ) : null}

      {account?.use_pickup_date ? (
        <PlanningDatePicker
          label={labels.pickupDate || "Pickup Date"}
          value={draft?.pickup_date || ""}
          onChange={(v) => setField("pickup_date", v)}
        />
      ) : null}

      {account?.use_processing_date !== false ? (
        <PlanningDatePicker
          label={labels.processingDate || "Processing Date"}
          value={processingValue}
          onChange={(v) => setField("processing_date", v)}
        />
      ) : null}

      {account?.use_delivery_date ? (
        <PlanningDatePicker
          label={labels.deliveryDate || "Delivery Date"}
          value={draft?.delivery_date || ""}
          onChange={(v) => setField("delivery_date", v)}
        />
      ) : null}

      {!isAbsolute ? (
        <MoneyAmountField
          label={labels.volumeLb || "Volume (lb)"}
          value={draft?.volume}
          onChange={(v) => setField("volume", v)}
          prefix=""
        />
      ) : null}

      {!isAbsolute && preview != null ? (
        <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#F0FAFB", border: "1px solid #e5e7eb" }}>
          <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
            {labels.calculated || "Calculated revenue"}
          </Typography>
          <Typography sx={{ fontWeight: 900, fontSize: 20, color: "#007a91" }}>{fmtMoney(preview)}</Typography>
        </Box>
      ) : null}

      {isAbsolute ? (
        <MoneyAmountField
          label={labels.revenue || "Revenue"}
          value={draft?.revenue}
          onChange={(v) => setField("revenue", v)}
        />
      ) : null}

      {!isAbsolute && allowOverride ? (
        <FormControlLabel
          control={
            <Switch
              checked={showOverride}
              onChange={(e) => {
                setShowOverride(e.target.checked);
                const next = { ...draft, use_revenue_override: e.target.checked };
                onChange?.(next);
                onAutosave?.(
                  buildBody(account, next, entryDate, e.target.checked, calcPreview(account, next?.volume)),
                );
              }}
            />
          }
          label={labels.useOverride || "Use revenue override"}
        />
      ) : null}

      {!isAbsolute && allowOverride && showOverride ? (
        <MoneyAmountField
          label={labels.revenueOverride || "Revenue override"}
          value={draft?.revenue}
          onChange={(v) => setField("revenue", v)}
        />
      ) : null}

      <Box
        sx={{
          position: "sticky",
          bottom: 0,
          p: 1.25,
          borderRadius: 2,
          bgcolor: "#fff",
          border: "1px solid #e5e7eb",
          display: "flex",
          flexDirection: "column",
          gap: 1,
          zIndex: 2,
        }}
      >
        <SaveStatusChip state={saveState} labels={saveLabels} />
        <Button
          variant="contained"
          disabled={saving || completeBusy || saveState === "saving"}
          onClick={() =>
            onComplete?.(buildBody(account, draft, entryDate, showOverride, preview))
          }
          sx={{ textTransform: "none", fontWeight: 900, minHeight: 48 }}
        >
          {labels.complete || "Complete"}
        </Button>
      </Box>
    </Stack>
  );
}
