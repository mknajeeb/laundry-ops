import { Box, Button, Chip, Stack, Typography } from "@mui/material";
import ManagementCopyableId from "../components/management/ManagementCopyableId";
import MoneyAmountField from "../components/revenueShared/MoneyAmountField";
import SaveStatusChip from "../components/revenueShared/SaveStatusChip";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import { OPS_MOBILE } from "./tokens";

function fmtTime(v) {
  if (!v) return "—";
  return formatFriendlyEtWall(v) || String(v);
}

function statusLabel(status) {
  if (status === "awaiting_entry") return "Awaiting Entry";
  if (status === "pending_wash") return "Pending Wash";
  if (status === "washed") return "Washed";
  if (status === "complete") return "Complete";
  return status || "—";
}

/**
 * Mobile HD awaiting-entry card: customer + ID + wash/fold on the left;
 * Items/Revenue inline on the right (stack below on narrow). Tap card (not inputs)
 * opens detail sheet. Autosave is draft-only; Complete is explicit.
 */
export default function HdMobileAwaitingCard({
  order,
  items,
  revenue,
  saveState,
  saveLabels,
  completing = false,
  onOpenDetail,
  onItemsChange,
  onRevenueChange,
  onComplete,
  labels = {},
}) {
  const customer =
    String(order?.customer_name || order?.name_clean || order?.customer || "").trim() ||
    "Unknown Customer";
  const status = order?.status || "awaiting_entry";

  const stopCardOpen = (e) => {
    e?.stopPropagation?.();
  };

  return (
    <Box
      data-testid="hd-mobile-awaiting-card"
      data-hd-inline-card={order?.bag_id || "1"}
      onClick={() => onOpenDetail?.(order)}
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", sm: "minmax(0, 1fr) minmax(148px, 190px)" },
        gap: { xs: 1.25, sm: 1.5 },
        width: "100%",
        textAlign: "left",
        p: 1.5,
        borderRadius: 2,
        border: "1px solid #e5e7eb",
        bgcolor: "#fff",
        cursor: "pointer",
        fontFamily: "inherit",
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Typography
            data-hd-customer="1"
            sx={{ fontSize: 17, fontWeight: 900, lineHeight: 1.2, color: "#0f172a" }}
          >
            {customer}
          </Typography>
          <Chip
            size="small"
            label={statusLabel(status)}
            sx={{ height: 22, fontWeight: 700, flexShrink: 0, bgcolor: "#fff7ed" }}
          />
        </Stack>
        <Box sx={{ mt: 0.4 }} onClick={stopCardOpen} onMouseDown={stopCardOpen}>
          <ManagementCopyableId value={order?.bag_id} fontSize={13} fontWeight={800} />
        </Box>
        <Typography
          data-hd-washed-by="1"
          sx={{ mt: 0.85, fontSize: 13, fontWeight: 700, color: "#334155" }}
        >
          {labels.washedBy || "Washed by"} {order?.washed_by_name || "—"}
        </Typography>
        <Typography sx={{ fontSize: 12, color: OPS_MOBILE.muted, fontWeight: 600 }}>
          {fmtTime(order?.washed_at)}
        </Typography>
        <Typography sx={{ mt: 0.45, fontSize: 13, fontWeight: 700, color: "#334155" }}>
          {labels.foldedBy || "Folded by"} {order?.folded_by_name || "—"}
        </Typography>
        <Typography sx={{ fontSize: 12, color: OPS_MOBILE.muted, fontWeight: 600 }}>
          {fmtTime(order?.folded_at)}
        </Typography>
      </Box>

      <Stack
        spacing={1}
        data-hd-inline-entry-fields="1"
        onClick={stopCardOpen}
        onMouseDown={stopCardOpen}
        sx={{ minWidth: 0 }}
      >
        <MoneyAmountField
          label={labels.items || "Items"}
          value={items}
          onChange={onItemsChange}
          prefix=""
          sx={{ p: 1 }}
        />
        <MoneyAmountField
          label={labels.revenue || "Revenue"}
          value={revenue}
          onChange={onRevenueChange}
          sx={{ p: 1 }}
        />
        <SaveStatusChip state={saveState} labels={saveLabels} />
        <Button
          variant="contained"
          disabled={completing || saveState === "saving"}
          onClick={(e) => {
            e.stopPropagation();
            onComplete?.(order);
          }}
          sx={{ textTransform: "none", fontWeight: 900, minHeight: 44 }}
        >
          {completing ? labels.saving || "Saving…" : labels.complete || "Complete"}
        </Button>
      </Stack>
    </Box>
  );
}
