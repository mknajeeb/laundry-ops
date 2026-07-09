import { Box, Button, Chip, Grid, Stack, Typography } from "@mui/material";
import AddShoppingCartIcon from "@mui/icons-material/AddShoppingCart";
import { formatCurrency, formatDateTime } from "../../utils/inventoryHelpers";
import { SectionCard, SummaryStatCard } from "./InventoryShared";

export default function DashboardTab({ dashboard, roleTier, onCreatePO, onGoCheck }) {
  const kpis = dashboard?.kpis || {};
  const showMoney = roleTier !== "floor";

  return (
    <Box>
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        {showMoney ? (
          <Grid item xs={6} sm={4} md={2}>
            <SummaryStatCard label="Inventory Value" value={formatCurrency(kpis.inventory_value)} color="primary.main" />
          </Grid>
        ) : null}
        <Grid item xs={6} sm={4} md={2}>
          <SummaryStatCard label="Below Reorder" value={kpis.items_below_reorder ?? 0} color="warning.main" />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <SummaryStatCard label="Pending POs" value={kpis.pending_purchase_orders ?? 0} />
        </Grid>
        {showMoney ? (
          <>
            <Grid item xs={6} sm={4} md={2}>
              <SummaryStatCard label="This Week $" value={formatCurrency(kpis.this_week_purchases)} />
            </Grid>
            <Grid item xs={6} sm={4} md={2}>
              <SummaryStatCard label="This Month $" value={formatCurrency(kpis.this_month_purchases)} />
            </Grid>
          </>
        ) : null}
        <Grid item xs={6} sm={4} md={2}>
          <SummaryStatCard
            label="Days Since Check"
            value={kpis.days_since_last_check ?? "—"}
            color={Number(kpis.days_since_last_check) > 7 ? "error.main" : "success.main"}
          />
        </Grid>
      </Grid>

      {kpis.last_stock_check_at ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Last check: {kpis.last_stock_check_by || "—"} · {formatDateTime(kpis.last_stock_check_at)}
        </Typography>
      ) : null}

      <SectionCard
        title="Low Stock"
        subtitle="Items needing attention"
        action={
          roleTier !== "floor" ? (
            <Button size="small" variant="contained" startIcon={<AddShoppingCartIcon />} onClick={onCreatePO}>
              Create Purchase Order
            </Button>
          ) : null
        }
      >
        {(dashboard?.low_stock || []).length === 0 ? (
          <Typography variant="body2" color="text.secondary">All tracked items are above reorder level.</Typography>
        ) : (
          (dashboard?.low_stock || []).map((row) => (
            <Stack
              key={row.id}
              direction={{ xs: "column", sm: "row" }}
              justifyContent="space-between"
              alignItems={{ sm: "center" }}
              sx={{ py: 1.25, borderBottom: "1px solid", borderColor: "divider", gap: 1 }}
            >
              <Box>
                <Typography fontWeight={600}>{row.name}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {row.category} · On hand {row.on_hand} · Reorder {row.reorder_level}
                  {row.vendor ? ` · ${row.vendor}` : ""}
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} alignItems="center">
                {row.weeks_remaining != null ? (
                  <Chip size="small" label={`~${row.weeks_remaining} wk left`} color="warning" variant="outlined" />
                ) : null}
                <Chip size="small" label={`Order ${row.suggested_qty}`} />
              </Stack>
            </Stack>
          ))
        )}
      </SectionCard>

      <SectionCard title="Recent Activity">
        {(dashboard?.recent_activity || []).map((a) => (
          <Typography key={`${a.event_type}-${a.id}-${a.event_at}`} variant="body2" sx={{ py: 0.75, borderBottom: "1px solid", borderColor: "divider" }}>
            {formatDateTime(a.event_at)} · {a.label}
          </Typography>
        ))}
        {(!dashboard?.recent_activity || dashboard.recent_activity.length === 0) ? (
          <Typography variant="body2" color="text.secondary">No recent activity.</Typography>
        ) : null}
      </SectionCard>

      {roleTier === "floor" ? (
        <Button fullWidth variant="contained" size="large" sx={{ mt: 2 }} onClick={onGoCheck}>
          Start Weekly Stock Check
        </Button>
      ) : null}
    </Box>
  );
}
