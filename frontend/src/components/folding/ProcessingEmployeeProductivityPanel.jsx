import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { getProcessingProductivity } from "../../api";
import { foldingRangeParams } from "../../utils/foldingDateRange";
import {
  formatFoldingWallDateTime,
  formatLbs,
  formatRate,
} from "../../utils/foldingFormat";

const timeCellSx = { whiteSpace: "nowrap", fontSize: 12, py: 1 };

function SummaryCard({ label, value, sub }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" fontWeight={700}>{value}</Typography>
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
}

export default function ProcessingEmployeeProductivityPanel({
  viewMode,
  userName,
  appliedDateStart,
  appliedDateEnd,
  appliedListDateField,
  searchTick,
  onOpenTimeline,
  onOpenOrder,
  onMapUser,
  onSelectUser,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!searchTick) {
      setData(null);
      return;
    }
    if (viewMode === "user" && !String(userName || "").trim()) {
      setData(null);
      return;
    }
    try {
      setLoading(true);
      setError("");
      const params = {
        ...foldingRangeParams({
          dateStart: appliedDateStart,
          dateEnd: appliedDateEnd,
          dateField: appliedListDateField,
        }),
        include_unmapped: true,
      };
      if (viewMode === "user") params.user_name = String(userName).trim();
      const res = await getProcessingProductivity(params);
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load processing productivity");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [
    viewMode,
    userName,
    appliedDateStart,
    appliedDateEnd,
    appliedListDateField,
    searchTick,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  const team = data?.summary_all_users || {};
  const users = data?.users || [];
  const userBlock = useMemo(() => {
    if (viewMode !== "user") return null;
    return users[0] || null;
  }, [viewMode, users]);

  const clocked = userBlock?.clocked_productivity || {};
  const clockSummary = clocked.summary || team;
  const bagLevel = userBlock?.bag_level || team;
  const records = viewMode === "user" ? (userBlock?.records || data?.records || []) : (data?.records || []);

  if (viewMode === "user" && !userName) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
        Select a user to view Processing productivity.
      </Typography>
    );
  }

  return (
    <Box mt={2}>
      <Typography variant="subtitle2" fontWeight={700} gutterBottom>
        Processing productivity
        {viewMode === "user" && userName ? ` — ${userName}` : " — all users"}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        Based on start-cleaning scans only (sort / weigh / wash / dry handling). Not folding performance.
      </Typography>

      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        <Button size="small" variant="outlined" onClick={load} disabled={loading}>
          Refresh
        </Button>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

      {data ? (
        <>
          <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
            Clocked-hour stats
          </Typography>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Clocked hours"
                value={formatRate(clockSummary.clocked_hours, 2)}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard label="Processing bags" value={clockSummary.total_bags ?? team.total_bags ?? 0} />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard label="Processing lbs" value={formatLbs(clockSummary.total_lbs ?? team.total_lbs)} />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Bags per clocked hour"
                value={formatRate(clockSummary.bags_per_clocked_hour ?? team.bags_per_clocked_hour, 2)}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Lbs per clocked hour"
                value={formatRate(clockSummary.lbs_per_clocked_hour ?? team.lbs_per_clocked_hour, 2)}
              />
            </Grid>
          </Grid>

          {viewMode === "user" && !clocked.available ? (
            <Alert severity="warning" sx={{ mb: 2 }}>
              {clocked.message || "Clocked productivity unavailable."}
              {clocked.map_user_hint && onMapUser ? (
                <Button size="small" sx={{ ml: 1 }} onClick={onMapUser}>
                  Map Rinse user to clock employee
                </Button>
              ) : null}
            </Alert>
          ) : null}

          {viewMode === "all" && users.length > 0 ? (
            <Table size="small" sx={{ mb: 3 }}>
              <TableHead>
                <TableRow>
                  <TableCell>User</TableCell>
                  <TableCell align="right">Mapped</TableCell>
                  <TableCell align="right">Clocked hrs</TableCell>
                  <TableCell align="right">Processing bags</TableCell>
                  <TableCell align="right">Processing lbs</TableCell>
                  <TableCell align="right">Bags / clock hr</TableCell>
                  <TableCell align="right">Lbs / clock hr</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {users.map((u) => {
                  const cs = u.clocked_productivity?.summary || u.bag_level || {};
                  return (
                    <TableRow
                      key={u.user_name}
                      hover
                      sx={{ cursor: onSelectUser ? "pointer" : undefined }}
                      onClick={() => onSelectUser?.(u.user_name)}
                    >
                      <TableCell>{u.user_name}</TableCell>
                      <TableCell align="right">
                        {u.employee_mapping?.mapped ? "Yes" : "No"}
                      </TableCell>
                      <TableCell align="right">{formatRate(cs.clocked_hours, 2)}</TableCell>
                      <TableCell align="right">{cs.total_bags ?? 0}</TableCell>
                      <TableCell align="right">{formatLbs(cs.total_lbs)}</TableCell>
                      <TableCell align="right">{formatRate(cs.bags_per_clocked_hour, 2)}</TableCell>
                      <TableCell align="right">{formatRate(cs.lbs_per_clocked_hour, 2)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : null}

          <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
            Bag-level stats (estimated processing time)
          </Typography>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            <Grid item xs={6} md={2}>
              <SummaryCard label="Processing bags" value={bagLevel.total_bags ?? 0} />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard label="Processing lbs" value={formatLbs(bagLevel.total_lbs)} />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Estimated processing minutes"
                value={bagLevel.estimated_processing_minutes ?? "—"}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Estimated processing hours"
                value={formatRate(bagLevel.estimated_processing_hours, 2)}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Bags per estimated processing hour"
                value={formatRate(bagLevel.bags_per_estimated_processing_hour, 2)}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Lbs per estimated processing hour"
                value={formatRate(bagLevel.lbs_per_estimated_processing_hour, 2)}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Avg estimated min / bag"
                value={formatRate(bagLevel.avg_estimated_minutes_per_bag, 2)}
              />
            </Grid>
          </Grid>

          <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
            Processing records
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Bag ID</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell align="right">Weight</TableCell>
                <TableCell sx={timeCellSx}>Start-cleaning</TableCell>
                <TableCell>Scan user</TableCell>
                <TableCell align="right">Est. min</TableCell>
                <TableCell>Shift linked</TableCell>
                <TableCell>In count</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {records.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} align="center" sx={{ py: 3, color: "text.secondary" }}>
                    {loading ? "Loading…" : "No start-cleaning records in this range."}
                  </TableCell>
                </TableRow>
              ) : records.map((r) => (
                <TableRow key={`${r.bag_id}-${r.scan_event_id}`} hover>
                  <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                  <TableCell>{r.customer || "—"}</TableCell>
                  <TableCell align="right">{r.weight_lbs != null ? formatLbs(r.weight_lbs) : "—"}</TableCell>
                  <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(r.start_cleaning_at)}</TableCell>
                  <TableCell>{r.scan_user_name || "—"}</TableCell>
                  <TableCell align="right">{r.estimated_processing_minutes ?? "—"}</TableCell>
                  <TableCell>{r.shift_linked ? "Yes" : "No"}</TableCell>
                  <TableCell>{r.included_in_processing_count ? "Yes" : "No"}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5}>
                      {onOpenOrder ? (
                        <Button size="small" onClick={() => onOpenOrder(r.bag_id)}>Order</Button>
                      ) : null}
                      {onOpenTimeline ? (
                        <Button size="small" onClick={() => onOpenTimeline(r.bag_id)}>Timeline</Button>
                      ) : null}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      ) : loading ? (
        <Typography variant="body2" color="text.secondary">Loading…</Typography>
      ) : null}
    </Box>
  );
}
