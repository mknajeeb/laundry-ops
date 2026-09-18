import { Alert, Typography } from "@mui/material";

export const WF_OPS_MAINTENANCE_BANNER_TEXT =
  "Wash & Fold maintenance in progress. Wash & Fold data may be temporarily unavailable while operational state is rebuilt. Hang Dry is unaffected.";

/** Clear org-scoped WF ops maintenance banner (single source: backend flag). */
export default function WfOpsMaintenanceBanner({ active = false, sx = null }) {
  if (!active) return null;
  return (
    <Alert
      severity="warning"
      data-testid="wf-ops-maintenance-banner"
      role="status"
      sx={{ mb: 1.25, py: 0.75, ...(sx || {}) }}
    >
      <Typography sx={{ fontSize: 13, fontWeight: 700, lineHeight: 1.35 }}>
        {WF_OPS_MAINTENANCE_BANNER_TEXT}
      </Typography>
    </Alert>
  );
}
