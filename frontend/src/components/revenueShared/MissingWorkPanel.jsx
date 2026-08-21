import { useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Collapse,
  Stack,
  Typography,
} from "@mui/material";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "daily", label: "Daily" },
  { id: "dhs", label: "DHS" },
  { id: "overdue", label: "Overdue" },
];

function statusLabel(status) {
  if (status === "missing") return "Missing";
  if (status === "overdue") return "Pickup overdue";
  if (status === "pending") return "Pending entry";
  if (status === "draft") return "Draft";
  if (status === "no_activity") return "No Activity";
  if (status === "complete" || status === "entered") return "Complete";
  return status || "—";
}

function formatShort(iso) {
  if (!iso) return "—";
  try {
    const [y, m, d] = String(iso).split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

/**
 * Grouped Missing Work queue — Date → Daily/DHS → account.
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
  const summary = data?.summary || {};
  const groups = data?.groups || [];
  const [openDates, setOpenDates] = useState(() => new Set());
  const [openAccounts, setOpenAccounts] = useState(() => new Set());

  const toggleDate = (key) => {
    setOpenDates((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleAccount = (key) => {
    setOpenAccounts((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Default: expand today/yesterday only
  const effectiveOpen = openDates.size
    ? openDates
    : new Set(
        groups
          .filter((g) => g.bucket === "today" || g.bucket === "yesterday")
          .map((g) => g.date_et),
      );

  return (
    <Stack spacing={1.25}>
      <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
        {FILTERS.map((f) => {
          const active = (filter || "all") === f.id;
          return (
            <Button
              key={f.id}
              size="small"
              onClick={() => onFilterChange?.(f.id)}
              sx={{
                textTransform: "none",
                fontWeight: 800,
                minHeight: 34,
                px: 1.25,
                borderRadius: 1.5,
                bgcolor: active ? "#007a91" : "#fff",
                color: active ? "#fff" : "#0f172a",
                border: active ? "1px solid #007a91" : "1px solid #e5e7eb",
              }}
            >
              {f.label}
            </Button>
          );
        })}
      </Box>

      <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#64748b" }}>
        {summary.missing_total ?? 0} missing
        {summary.overdue != null ? ` · ${summary.overdue} overdue` : ""}
      </Typography>

      {loading ? (
        <Box sx={{ py: 4, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : null}

      {!loading && !groups.length ? (
        <Typography sx={{ fontSize: 13, color: "#64748b" }}>No missing work for this filter.</Typography>
      ) : null}

      <Stack spacing={1}>
        {groups.map((g) => {
          const dateOpen = effectiveOpen.has(g.date_et);
          return (
            <Box
              key={g.date_et}
              sx={{
                borderRadius: 2,
                border: "1px solid rgba(0,151,178,0.22)",
                bgcolor: "#fff",
                overflow: "hidden",
              }}
            >
              <Box
                component="button"
                type="button"
                onClick={() => toggleDate(g.date_et)}
                sx={{
                  width: "100%",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  border: "none",
                  bgcolor: "#F8FBFC",
                  px: 1.25,
                  py: 1,
                  minHeight: 44,
                  cursor: "pointer",
                }}
              >
                <Typography sx={{ fontWeight: 900, fontSize: 13, color: "#0f172a", textTransform: "uppercase" }}>
                  {g.label}
                </Typography>
                <Typography sx={{ fontWeight: 800, fontSize: 13, color: "#007a91" }}>
                  {g.count} missing
                </Typography>
              </Box>

              <Collapse in={dateOpen}>
                <Stack spacing={0.75} sx={{ p: 1.25, pt: 0.75 }}>
                  {(g.daily || []).length ? (
                    <Box>
                      <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b", mb: 0.35 }}>
                        DAILY
                      </Typography>
                      {g.daily.map((item) => {
                        const key = `${item.source_key}:${item.processing_date_et}`;
                        return (
                          <Box
                            key={key}
                            sx={{
                              display: "flex",
                              alignItems: "center",
                              gap: 1,
                              py: 0.65,
                              borderBottom: "1px solid #f1f5f9",
                            }}
                          >
                            <Button
                              onClick={() => onOpenItem?.(item)}
                              sx={{
                                flex: 1,
                                justifyContent: "flex-start",
                                textTransform: "none",
                                fontWeight: 800,
                                color: "#0f172a",
                                minHeight: 40,
                              }}
                            >
                              <Box sx={{ textAlign: "left" }}>
                                <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{item.name}</Typography>
                                <Typography sx={{ fontSize: 11, color: "#64748b" }}>
                                  {statusLabel(item.status)}
                                </Typography>
                              </Box>
                            </Button>
                            {item.status === "missing" && onNoActivity ? (
                              <Button
                                size="small"
                                disabled={busyId === key}
                                onClick={() => onNoActivity?.(item, "No activity")}
                                sx={{ textTransform: "none", fontSize: 11 }}
                              >
                                No Activity
                              </Button>
                            ) : null}
                          </Box>
                        );
                      })}
                    </Box>
                  ) : null}

                  {(g.dhs || []).length ? (
                    <Box>
                      <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b", mb: 0.35 }}>
                        DHS
                      </Typography>
                      {g.dhs.map((acct) => {
                        const acctKey = `${g.date_et}:${acct.account_id}`;
                        const multi = (acct.items || []).length > 1;
                        const acctOpen = !multi || openAccounts.has(acctKey);
                        const first = acct.items?.[0];
                        return (
                          <Box key={acctKey} sx={{ mb: 0.5 }}>
                            <Box
                              component="button"
                              type="button"
                              onClick={() => {
                                if (multi) toggleAccount(acctKey);
                                else if (first) onOpenItem?.(first);
                              }}
                              sx={{
                                width: "100%",
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                border: "none",
                                bgcolor: "transparent",
                                py: 0.75,
                                px: 0,
                                minHeight: 44,
                                cursor: "pointer",
                                textAlign: "left",
                              }}
                            >
                              <Box>
                                <Typography sx={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>
                                  {acct.name}
                                </Typography>
                                {first ? (
                                  <Typography sx={{ fontSize: 11, color: "#64748b" }}>
                                    Pickup {formatShort(first.scheduled_pickup_date)}
                                    {first.suggested_processing_date
                                      ? ` · Processing ${formatShort(first.suggested_processing_date)}`
                                      : ""}
                                    {" · "}
                                    {statusLabel(first.status)}
                                  </Typography>
                                ) : null}
                              </Box>
                              {multi ? (
                                <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#64748b" }}>
                                  {acct.items.length}
                                </Typography>
                              ) : null}
                            </Box>
                            <Collapse in={acctOpen && multi}>
                              <Stack spacing={0.5} sx={{ pl: 1 }}>
                                {(acct.items || []).map((item) => {
                                  const key = `${item.source_key}:${item.scheduled_pickup_date}`;
                                  return (
                                    <Button
                                      key={key}
                                      onClick={() => onOpenItem?.(item)}
                                      sx={{
                                        justifyContent: "flex-start",
                                        textTransform: "none",
                                        fontWeight: 700,
                                        color: "#0f172a",
                                        minHeight: 40,
                                      }}
                                    >
                                      Pickup {formatShort(item.scheduled_pickup_date)} · {statusLabel(item.status)}
                                    </Button>
                                  );
                                })}
                              </Stack>
                            </Collapse>
                          </Box>
                        );
                      })}
                    </Box>
                  ) : null}
                </Stack>
              </Collapse>
            </Box>
          );
        })}
      </Stack>
    </Stack>
  );
}
