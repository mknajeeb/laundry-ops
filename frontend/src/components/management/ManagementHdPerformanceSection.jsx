import { useCallback, useEffect, useState } from "react";
import { Alert, Box, CircularProgress, Stack, Typography } from "@mui/material";
import { getManagementRinseHdPerformance } from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * HD wash/fold performance for selected ET day.
 * Wash credit → washed_at; Fold credit → folded_at (not revenue entry date).
 */
export default function ManagementHdPerformanceSection({ dateEt }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRinseHdPerformance(dateEt);
      setData(res.data || null);
    } catch (err) {
      setData(null);
      setError(err?.response?.data?.error || err?.message || "Unable to load HD performance");
    } finally {
      setLoading(false);
    }
  }, [dateEt]);

  useEffect(() => {
    load();
  }, [load]);

  const employees = data?.employees || [];

  return (
    <Box sx={{ mt: 2 }}>
      <Typography sx={{ fontSize: 16, fontWeight: 800, mb: 0.25 }}>Rinse HD</Typography>
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600, mb: 1 }}>
        Wash credit by washed_at · Fold credit by folded_at
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <Box sx={{ py: 2, textAlign: "center" }}>
          <CircularProgress size={20} />
        </Box>
      ) : employees.length === 0 ? (
        <Typography sx={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>
          No HD wash/fold attribution for this day.
        </Typography>
      ) : (
        <Stack spacing={1}>
          {employees.map((emp) => (
            <Box
              key={emp.user_id}
              sx={{
                p: 1.25,
                borderRadius: 2,
                border: "1px solid #e5e7eb",
                bgcolor: "#fff",
              }}
            >
              <Typography sx={{ fontWeight: 800, fontSize: 15 }}>{emp.display_name}</Typography>
              <Typography sx={{ mt: 0.35, fontSize: 13, fontWeight: 700, color: VEEWASH_DASHBOARD.hdTeal }}>
                Wash {emp.wash_count} · Fold {emp.fold_count}
              </Typography>
              {emp.fold_count > 0 ? (
                <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                  Fold items {emp.items_on_fold} · {fmtMoney(emp.revenue_on_fold)}
                </Typography>
              ) : null}
              {(emp.wash_bags || []).slice(0, 3).map((b) => (
                <Typography key={`w-${b.bag_id}`} sx={{ fontSize: 11, color: "#64748b" }}>
                  Wash {b.bag_id} · {formatFriendlyEtWall(b.washed_at) || "—"}
                </Typography>
              ))}
              {(emp.fold_bags || []).slice(0, 3).map((b) => (
                <Typography key={`f-${b.bag_id}`} sx={{ fontSize: 11, color: "#64748b" }}>
                  Fold {b.bag_id} · {formatFriendlyEtWall(b.folded_at) || "—"}
                </Typography>
              ))}
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}
