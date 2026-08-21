import { useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "daily", label: "Daily" },
  { id: "dhs", label: "DHS" },
  { id: "overdue", label: "Overdue" },
  { id: "resolved", label: "Resolved" },
];

function statusLabel(status) {
  if (status === "missing") return "Missing";
  if (status === "overdue") return "Pickup overdue";
  if (status === "pending") return "Pending";
  if (status === "no_activity") return "No Activity";
  if (status === "entered") return "Entered";
  if (status === "rescheduled") return "Rescheduled";
  return status || "—";
}

/**
 * Missing Work list — tap row opens entry via onOpenItem.
 */
export default function MissingWorkPanel({
  loading,
  data,
  filter,
  onFilterChange,
  onOpenItem,
  onNoActivity,
  onNoPickup,
  onReschedule,
  busyId,
}) {
  const [reasonByKey, setReasonByKey] = useState({});
  const summary = data?.summary || {};
  const items = data?.items || [];

  return (
    <Stack spacing={1.5}>
      <Box
        sx={{
          p: 1.5,
          borderRadius: 2,
          border: "1px solid rgba(0,151,178,0.28)",
          bgcolor: "#fff",
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", textTransform: "uppercase" }}>
          Missing Work
        </Typography>
        <Typography sx={{ mt: 0.35, fontSize: 22, fontWeight: 900, color: "#007a91" }}>
          {summary.missing_total ?? 0} Missing
        </Typography>
        <Typography sx={{ fontSize: 13, fontWeight: 600, color: "#64748b" }}>
          {summary.daily_missing || 0} Daily Missing · {summary.dhs_pending || 0} DHS Pending
          {summary.overdue != null ? ` · ${summary.overdue} Overdue` : ""}
        </Typography>
      </Box>

      <Tabs
        value={filter || "all"}
        onChange={(_, v) => onFilterChange?.(v)}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ minHeight: 36, "& .MuiTab-root": { minHeight: 36, textTransform: "none", fontWeight: 700 } }}
      >
        {FILTERS.map((f) => (
          <Tab key={f.id} value={f.id} label={f.label} />
        ))}
      </Tabs>

      {loading ? (
        <Box sx={{ py: 4, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : null}

      {!loading && !items.length ? (
        <Typography sx={{ fontSize: 13, color: "#64748b" }}>No missing work for this filter.</Typography>
      ) : null}

      <Stack spacing={1}>
        {items.map((item) => {
          const key = `${item.source_key}:${item.processing_date_et || item.scheduled_pickup_date}`;
          const busy = busyId === key;
          const sub =
            item.kind === "dhs"
              ? `Pickup ${item.scheduled_pickup_date}${item.overdue || item.status === "overdue" ? " · Overdue" : " · Pending Entry"}`
              : `Daily Entry · ${item.processing_date_et} · ${statusLabel(item.status)}`;
          return (
            <Box
              key={key}
              sx={{
                p: 1.5,
                borderRadius: 2,
                border: "1px solid #e5e7eb",
                bgcolor: "#fff",
              }}
            >
              <Box
                component="button"
                type="button"
                onClick={() => onOpenItem?.(item)}
                sx={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  m: 0,
                  p: 0,
                  border: "none",
                  bgcolor: "transparent",
                  cursor: "pointer",
                  appearance: "none",
                  fontFamily: "inherit",
                }}
              >
                <Typography sx={{ fontWeight: 900 }}>{item.name}</Typography>
                <Typography sx={{ mt: 0.25, fontSize: 13, fontWeight: 600, color: item.overdue ? "#b91c1c" : "#d97706" }}>
                  {sub}
                </Typography>
                <Typography sx={{ mt: 0.5, fontSize: 12, fontWeight: 700, color: "#007a91" }}>Enter →</Typography>
              </Box>

              {!item.resolved ? (
                <Stack spacing={1} sx={{ mt: 1.25 }}>
                  <TextField
                    size="small"
                    label="Reason (optional)"
                    value={reasonByKey[key] || ""}
                    onChange={(e) => setReasonByKey((p) => ({ ...p, [key]: e.target.value }))}
                    fullWidth
                  />
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {item.kind === "daily" ? (
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={busy}
                        onClick={() => onNoActivity?.(item, reasonByKey[key] || "")}
                        sx={{ textTransform: "none", fontWeight: 700 }}
                      >
                        No Activity
                      </Button>
                    ) : (
                      <>
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={busy}
                          onClick={() => onNoPickup?.(item, reasonByKey[key] || "")}
                          sx={{ textTransform: "none", fontWeight: 700 }}
                        >
                          No Pickup
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={busy}
                          onClick={() => onReschedule?.(item, reasonByKey[key] || "")}
                          sx={{ textTransform: "none", fontWeight: 700 }}
                        >
                          Reschedule
                        </Button>
                      </>
                    )}
                  </Stack>
                </Stack>
              ) : null}
            </Box>
          );
        })}
      </Stack>
    </Stack>
  );
}
