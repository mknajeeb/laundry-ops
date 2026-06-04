import { Chip } from "@mui/material";
import { schedulingReadinessBadge } from "../../payroll/workerSchedulingProfile";

export default function SchedulingReadinessChip({ worker, size = "small" }) {
  const badge = worker?.readiness || schedulingReadinessBadge(worker || {});
  return <Chip size={size} color={badge.color} label={badge.label} variant={badge.ready ? "filled" : "outlined"} />;
}
