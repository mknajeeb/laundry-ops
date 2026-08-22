import { Box, Button, Stack, Typography } from "@mui/material";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import ManagementCopyableId from "./ManagementCopyableId";
import {
  bagHasSpecialtyBulk,
  fmtLbs,
} from "./reviewDrawerModel";

function rushLabel(flag) {
  const raw = String(flag || "").trim().toLowerCase();
  if (!raw || raw === "non-rush" || raw === "non_rush" || raw === "nonrush") {
    return "Non-Rush";
  }
  if (raw === "rush" || raw.includes("rush")) return "Rush";
  return String(flag);
}

function fmtTime(v) {
  if (!v) return null;
  try {
    return formatFriendlyEtWall(v) || String(v);
  } catch {
    return String(v);
  }
}

function bulkIndicator(bag) {
  if (!bagHasSpecialtyBulk(bag)) return null;
  const parts = [];
  if (Number(bag?.comforter_quantity) > 0) {
    parts.push(`Comforter ×${bag.comforter_quantity}`);
  }
  if (Number(bag?.bath_mat_quantity) > 0) {
    parts.push(`Bath Mat ×${bag.bath_mat_quantity}`);
  }
  if (bag?.specialty_summary) parts.push(bag.specialty_summary);
  return parts.length ? parts.join(" · ") : "Bulk items";
}

/**
 * Missing From Portal / Specialty queue row — summary + one action: Detailed Review.
 */
export default function ManagementRinseWfReviewDrawerRow({
  bag,
  onDetailedReview,
}) {
  const pre =
    bag?.evidence_pre_weight_lbs != null
      ? fmtLbs(bag.evidence_pre_weight_lbs)
      : fmtLbs(bag?.pre_weight_lbs);
  const post = fmtLbs(bag?.post_weight_lbs ?? bag?.post_weight_value);
  const completionEmp = bag?.completion_employee || bag?.completed_by;
  const completionAt = fmtTime(bag?.completion_at);
  const bulk = bulkIndicator(bag);

  return (
    <Box sx={{ py: 1.1 }} data-testid="review-drawer-row">
      <Typography sx={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>
        {bag.customer_name || "—"}
      </Typography>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 0.15 }} flexWrap="wrap">
        <ManagementCopyableId value={bag.bag_id} fontSize={13} fontWeight={700} />
        <Typography sx={{ fontSize: 12, color: "#64748b" }}>· {rushLabel(bag.rush_flag)}</Typography>
      </Stack>
      <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#334155", mt: 0.45 }}>
        {bag.short_reason || "Review"}
      </Typography>
      <Stack direction="row" spacing={1.25} flexWrap="wrap" sx={{ mt: 0.25 }}>
        <Typography data-testid="review-drawer-pre" sx={{ fontSize: 12, color: "#475569" }}>
          PRE {pre || "—"}
        </Typography>
        {post ? (
          <Typography data-testid="review-drawer-post" sx={{ fontSize: 12, color: "#475569" }}>
            POST {post}
          </Typography>
        ) : null}
      </Stack>
      {bulk ? (
        <Typography sx={{ fontSize: 12, color: "#b45309", mt: 0.25, fontWeight: 600 }}>
          {bulk}
        </Typography>
      ) : null}
      {completionEmp || completionAt ? (
        <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 0.2 }}>
          {[completionEmp, completionAt].filter(Boolean).join(" · ")}
        </Typography>
      ) : null}
      <Button
        data-testid="review-detailed-review"
        size="small"
        variant="contained"
        onClick={() => onDetailedReview?.(bag)}
        sx={{ mt: 0.85, textTransform: "none", fontWeight: 800 }}
      >
        Detailed Review
      </Button>
    </Box>
  );
}
