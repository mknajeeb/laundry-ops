import { useCallback, useEffect, useState } from "react";
import { Box, Tab, Tabs, Typography } from "@mui/material";
import { getInventoryReports } from "../../api";
import { LoadingBlock, SectionCard } from "./InventoryShared";
import { formatCurrency } from "../../utils/inventoryHelpers";

function ReportList({ title, rows, labelKey = "label", valueKey = "total", format = formatCurrency }) {
  return (
    <SectionCard title={title}>
      {(rows || []).length === 0 ? (
        <Typography variant="body2" color="text.secondary">No data for this period.</Typography>
      ) : (
        rows.map((r, i) => (
          <Box key={i} sx={{ display: "flex", justifyContent: "space-between", py: 0.75, borderBottom: "1px solid", borderColor: "divider" }}>
            <Typography variant="body2">{r[labelKey] || r.category || r.vendor || r.item_name || r.month}</Typography>
            <Typography variant="body2" fontWeight={600}>{format(r[valueKey] ?? r.total ?? r.qty)}</Typography>
          </Box>
        ))
      )}
    </SectionCard>
  );
}

export default function ReportsTab() {
  const [tab, setTab] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getInventoryReports();
      setData(res?.data || {});
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <LoadingBlock message="Loading reports…" />;

  const tabs = ["Overview", "Purchases", "Inventory", "Activity"];

  return (
    <Box>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" sx={{ mb: 2 }}>
        {tabs.map((t) => <Tab key={t} label={t} />)}
      </Tabs>

      {tab === 0 ? (
        <>
          <SectionCard title="Inventory Value">
            <Typography variant="h5" fontWeight={800}>{formatCurrency(data?.inventory_value?.total)}</Typography>
            <ReportList title="By Category" rows={Object.entries(data?.inventory_value?.by_category || {}).map(([category, total]) => ({ category, total }))} labelKey="category" />
          </SectionCard>
          <ReportList title="Monthly Spend (6 mo)" rows={data?.monthly_spend || []} labelKey="month" />
        </>
      ) : null}

      {tab === 1 ? (
        <>
          <ReportList title="Purchases by Vendor" rows={(data?.purchases_by_vendor || []).map((r) => ({ label: r.vendor, total: r.total }))} />
          <ReportList title="Purchases by Category" rows={(data?.purchases_by_category || []).map((r) => ({ label: r.category, total: r.total }))} />
          <ReportList title="Most Purchased Items" rows={data?.most_purchased || []} labelKey="item_name" valueKey="qty" format={(v) => v} />
          <ReportList title="Least Purchased Items" rows={data?.least_purchased || []} labelKey="item_name" valueKey="qty" format={(v) => v} />
        </>
      ) : null}

      {tab === 2 ? (
        <>
          <ReportList
            title="Low Inventory"
            rows={(data?.low_inventory || []).map((i) => ({
              label: i.name,
              total: `${i.current_on_hand} on hand · reorder ${i.reorder_level}`,
            }))}
            format={(v) => v}
          />
        </>
      ) : null}

      {tab === 3 ? (
        <>
          <SectionCard title="Adjustments (90 days)">
            {(data?.adjustments || []).slice(0, 40).map((a) => (
              <Typography key={a.id} variant="body2" sx={{ py: 0.5 }}>
                {String(a.created_at).slice(0, 10)} · {a.item_name} · {a.qty_change > 0 ? "+" : ""}{a.qty_change} · {a.reason_code || a.reason}
              </Typography>
            ))}
          </SectionCard>
          <SectionCard title="Weekly Count History">
            {(data?.stock_check_history || []).map((c) => (
              <Typography key={c.id} variant="body2" sx={{ py: 0.5 }}>
                {String(c.submitted_at || c.check_date).slice(0, 10)} · {c.checked_by_name}
              </Typography>
            ))}
          </SectionCard>
        </>
      ) : null}
    </Box>
  );
}
