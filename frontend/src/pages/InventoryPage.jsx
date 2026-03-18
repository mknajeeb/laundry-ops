import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  createBagSale,
  createInventoryItem,
  createInventoryReorder,
  getBagSales,
  getInventoryBagPrice,
  getInventoryItems,
  getInventoryReport,
  saveInventoryBagPrice,
  saveInventoryCountsBulk,
} from "../api";

function InventoryPage({ user }) {
  const displayName = user?.display_name || user?.username || "Unknown";
  const today = new Date().toISOString().slice(0, 10);

  const [tab, setTab] = useState("WEEKLY");
  const [items, setItems] = useState([]);
  const [sales, setSales] = useState([]);
  const [report, setReport] = useState({ items: [], bag_totals: {} });
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [saving, setSaving] = useState(false);

  const [weeklyCounts, setWeeklyCounts] = useState({});
  const [managerSelect, setManagerSelect] = useState({});
  const [managerQty, setManagerQty] = useState({});

  const [newItem, setNewItem] = useState({
    item_name: "",
    category: "SUPPLY",
    vendor_name: "",
    unit_label: "unit",
    reorder_threshold: 0,
    on_hand_qty: 0,
    active: true,
  });

  const [bagPrice, setBagPrice] = useState(10);
  const [saleForm, setSaleForm] = useState({
    sale_date: today,
    customer_name: "",
    sale_type: "DROP_OFF",
    qty: 1,
    amount_paid: "",
    entered_by: displayName,
  });

  const load = async () => {
    try {
      const [itemsRes, salesRes, bagPriceRes, reportRes] = await Promise.all([
        getInventoryItems(),
        getBagSales(),
        getInventoryBagPrice(),
        getInventoryReport(),
      ]);

      const list = Array.isArray(itemsRes?.data) ? itemsRes.data : [];
      setItems(list);
      setSales(Array.isArray(salesRes?.data) ? salesRes.data : []);
      setReport(reportRes?.data || { items: [], bag_totals: {} });
      setBagPrice(Number(bagPriceRes?.data?.bag_default_price || 0));

      const nextWeekly = {};
      const nextSelect = {};
      const nextQty = {};
      list.forEach((i) => {
        nextWeekly[i.id] = i.on_hand_qty ?? "";
        nextSelect[i.id] = false;
        const threshold = Number(i.reorder_threshold || 0);
        const onHand = Number(i.on_hand_qty || 0);
        nextQty[i.id] = Math.max(threshold * 2 - onHand, 1);
      });
      setWeeklyCounts(nextWeekly);
      setManagerSelect(nextSelect);
      setManagerQty(nextQty);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: "Inventory load failed." });
    }
  };

  useEffect(() => {
    load();
  }, []);

  const supplyItems = useMemo(
    () => items.filter((i) => String(i.category || "").toUpperCase() === "SUPPLY"),
    [items]
  );

  const bagItem = useMemo(
    () => items.find((i) => String(i.category || "").toUpperCase() === "BAG"),
    [items]
  );

  const managerRows = useMemo(
    () =>
      supplyItems.map((i) => {
        const onHand = Number(i.on_hand_qty || 0);
        const threshold = Number(i.reorder_threshold || 0);
        const suggested = Math.max(threshold * 2 - onHand, 0);
        return {
          ...i,
          onHand,
          threshold,
          suggested,
          low: onHand <= threshold,
        };
      }),
    [supplyItems]
  );

  const onSubmitWeekly = async () => {
    try {
      setSaving(true);
      const rows = supplyItems
        .map((i) => ({
          item_id: i.id,
          counted_qty: weeklyCounts[i.id],
        }))
        .filter((r) => r.counted_qty !== "" && r.counted_qty !== null && r.counted_qty !== undefined)
        .map((r) => ({ ...r, counted_qty: Number(r.counted_qty) }));

      if (rows.length === 0) {
        setMessage({ type: "error", text: "Enter at least one quantity." });
        return;
      }

      await saveInventoryCountsBulk({
        rows,
        counted_by: displayName,
        notes: `Weekly check ${today}`,
      });

      setMessage({ type: "success", text: "Weekly inventory submitted." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Weekly submit failed." });
    } finally {
      setSaving(false);
    }
  };

  const onBulkOrder = async () => {
    try {
      setSaving(true);
      const lines = managerRows
        .filter((i) => managerSelect[i.id])
        .map((i) => ({
          item_id: i.id,
          requested_qty: Number(managerQty[i.id] || 0),
        }))
        .filter((l) => l.requested_qty > 0);

      if (lines.length === 0) {
        setMessage({ type: "error", text: "Select items and requested qty." });
        return;
      }

      await createInventoryReorder({
        lines,
        ordered_by: displayName,
        notes: `Manager reorder ${today}`,
      });

      setMessage({ type: "success", text: "Order submitted and on-hand updated." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Bulk order failed." });
    } finally {
      setSaving(false);
    }
  };

  const onSaveBagPrice = async () => {
    try {
      setSaving(true);
      await saveInventoryBagPrice({ bag_default_price: Number(bagPrice || 0), updated_by: displayName });
      setMessage({ type: "success", text: "Bag price updated." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Bag price save failed." });
    } finally {
      setSaving(false);
    }
  };

  const onAddItem = async () => {
    try {
      setSaving(true);
      await createInventoryItem(newItem);
      setNewItem({
        item_name: "",
        category: "SUPPLY",
        vendor_name: "",
        unit_label: "unit",
        reorder_threshold: 0,
        on_hand_qty: 0,
        active: true,
      });
      setMessage({ type: "success", text: "Item added." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Add item failed." });
    } finally {
      setSaving(false);
    }
  };

  const onSaveSale = async () => {
    try {
      setSaving(true);
      const payload = {
        ...saleForm,
        qty: Number(saleForm.qty),
        entered_by: displayName,
      };
      if (!payload.amount_paid) {
        payload.amount_paid = (Number(bagPrice || 0) * Number(payload.qty || 0)).toFixed(2);
      }
      await createBagSale(payload);
      setSaleForm({
        sale_date: today,
        customer_name: "",
        sale_type: "DROP_OFF",
        qty: 1,
        amount_paid: "",
        entered_by: displayName,
      });
      setMessage({ type: "success", text: "Bag sale recorded." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Sale save failed." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, minHeight: "100%" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 30, fontWeight: 400 }}>Inventory</Typography>
        <Chip label={`Supplies ${supplyItems.length}`} />
      </Stack>

      {message.text && (
        <Typography sx={{ mt: 1, color: message.type === "error" ? "#b91c1c" : "#0f766e", fontSize: 14 }}>
          {message.text}
        </Typography>
      )}

      <Paper sx={{ mt: 1.2, borderRadius: 2, overflow: "hidden" }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="fullWidth">
          <Tab value="WEEKLY" label="Weekly Check" />
          <Tab value="MANAGER" label="Manager" />
          <Tab value="RETAIL" label="Retail Sales" />
          <Tab value="REPORT" label="Report" />
        </Tabs>
      </Paper>

      {tab === "WEEKLY" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Weekly Inventory Check</Typography>
          <Typography sx={{ fontSize: 14, color: "#64748b", mt: 0.3 }}>
            {today} • {displayName}
          </Typography>

          <Stack spacing={1} sx={{ mt: 1.2 }}>
            {supplyItems.map((i) => (
              <Stack key={i.id} direction="row" alignItems="center" spacing={1} sx={{ border: "1px solid #e5e7eb", borderRadius: 1.5, p: 1 }}>
                <Box sx={{ minWidth: 220 }}>
                  <Typography>{i.item_name}</Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                    Available {Number(i.on_hand_qty || 0).toFixed(0)} {i.unit_label || "unit"}
                  </Typography>
                </Box>
                <TextField
                  size="small"
                  type="number"
                  label="Count"
                  value={weeklyCounts[i.id] ?? ""}
                  onChange={(e) => setWeeklyCounts((p) => ({ ...p, [i.id]: e.target.value }))}
                  sx={{ maxWidth: 180 }}
                />
              </Stack>
            ))}
          </Stack>

          <Stack direction="row" justifyContent="flex-end" sx={{ mt: 1.2 }}>
            <Button variant="contained" onClick={onSubmitWeekly} disabled={saving}>
              Submit Weekly Count
            </Button>
          </Stack>
        </Paper>
      )}

      {tab === "MANAGER" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Manager Dashboard</Typography>

          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
            <TextField
              size="small"
              type="number"
              label="Default Bag Price"
              value={bagPrice}
              onChange={(e) => setBagPrice(e.target.value)}
              sx={{ maxWidth: 180 }}
            />
            <Button variant="outlined" onClick={onSaveBagPrice} disabled={saving}>Save Price</Button>
          </Stack>

          <Stack spacing={1} sx={{ mt: 1.2 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 0.5 }}>
              <Button
                size="small"
                variant="text"
                onClick={() => {
                  const allSelected = managerRows.every((r) => managerSelect[r.id]);
                  const next = {};
                  managerRows.forEach((r) => {
                    next[r.id] = !allSelected;
                  });
                  setManagerSelect((p) => ({ ...p, ...next }));
                }}
              >
                {managerRows.every((r) => managerSelect[r.id]) ? "Clear All" : "Select All"}
              </Button>
              <Typography sx={{ fontSize: 13, color: "#64748b" }}>
                Selected {managerRows.filter((r) => managerSelect[r.id]).length}
              </Typography>
            </Stack>
            {managerRows.map((i) => (
              <Stack key={i.id} direction="row" alignItems="center" spacing={1} sx={{ border: "1px solid #e5e7eb", borderRadius: 1.5, p: 1 }}>
                <Checkbox
                  checked={Boolean(managerSelect[i.id])}
                  onChange={(e) => setManagerSelect((p) => ({ ...p, [i.id]: e.target.checked }))}
                />
                <Box sx={{ minWidth: 260 }}>
                  <Typography>{i.item_name}</Typography>
                  <Typography sx={{ fontSize: 12, color: i.low ? "#b45309" : "#64748b" }}>
                    Available {i.onHand.toFixed(0)} • Reorder at {i.threshold.toFixed(0)} • Suggested {i.suggested}
                  </Typography>
                </Box>
                <TextField
                  size="small"
                  type="number"
                  label="Requested Qty"
                  value={managerQty[i.id] ?? ""}
                  onChange={(e) => setManagerQty((p) => ({ ...p, [i.id]: e.target.value }))}
                  sx={{ maxWidth: 180 }}
                />
              </Stack>
            ))}
          </Stack>

          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 1.2 }}>
            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                label="New Item"
                value={newItem.item_name}
                onChange={(e) => setNewItem((p) => ({ ...p, item_name: e.target.value }))}
              />
              <TextField
                size="small"
                label="Vendor"
                value={newItem.vendor_name}
                onChange={(e) => setNewItem((p) => ({ ...p, vendor_name: e.target.value }))}
              />
              <TextField
                size="small"
                type="number"
                label="Threshold"
                value={newItem.reorder_threshold}
                onChange={(e) => setNewItem((p) => ({ ...p, reorder_threshold: e.target.value }))}
                sx={{ maxWidth: 120 }}
              />
              <Button variant="outlined" onClick={onAddItem} disabled={saving || !newItem.item_name}>Add</Button>
            </Stack>
            <Button variant="contained" onClick={onBulkOrder} disabled={saving}>Order Selected</Button>
          </Stack>
        </Paper>
      )}

      {tab === "RETAIL" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Retail Bag Sales</Typography>
          <Typography sx={{ fontSize: 14, color: "#64748b", mt: 0.3 }}>
            Remaining {Number(bagItem?.on_hand_qty || 0).toFixed(0)} bag(s)
          </Typography>

          <Stack direction="row" spacing={1} sx={{ mt: 1.2, flexWrap: "wrap" }}>
            <TextField size="small" type="date" label="Date" InputLabelProps={{ shrink: true }} value={saleForm.sale_date} onChange={(e) => setSaleForm((p) => ({ ...p, sale_date: e.target.value }))} />
            <TextField size="small" label="Customer" value={saleForm.customer_name} onChange={(e) => setSaleForm((p) => ({ ...p, customer_name: e.target.value }))} />
            <TextField size="small" select label="Type" value={saleForm.sale_type} onChange={(e) => setSaleForm((p) => ({ ...p, sale_type: e.target.value }))} sx={{ minWidth: 150 }}>
              <MenuItem value="DROP_OFF">Drop Off</MenuItem>
              <MenuItem value="PICKUP_DELIVERY">Pickup/Delivery</MenuItem>
            </TextField>
            <TextField size="small" type="number" label="Qty" value={saleForm.qty} onChange={(e) => setSaleForm((p) => ({ ...p, qty: e.target.value }))} sx={{ maxWidth: 100 }} />
            <TextField size="small" type="number" label="Amount" value={saleForm.amount_paid} onChange={(e) => setSaleForm((p) => ({ ...p, amount_paid: e.target.value }))} sx={{ maxWidth: 130 }} />
            <Button variant="contained" onClick={onSaveSale} disabled={saving || !saleForm.customer_name || Number(saleForm.qty) <= 0}>Save Sale</Button>
          </Stack>

          <Stack spacing={0.8} sx={{ mt: 1.2 }}>
            {sales.slice(0, 80).map((s) => (
              <Stack key={s.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", borderRadius: 1.2, p: 0.8 }}>
                <Typography sx={{ fontSize: 14 }}>
                  {String(s.sale_date).slice(0, 10)} • {s.customer_name} • Qty {s.qty}
                </Typography>
                <Typography sx={{ fontSize: 14 }}>{s.amount_paid || "NOT CHARGED"}</Typography>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      {tab === "REPORT" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Inventory Report</Typography>
          <Typography sx={{ fontSize: 14, color: "#64748b", mt: 0.3 }}>
            Bags sold {Number(report?.bag_totals?.total_bags_sold || 0).toFixed(0)} • Sales ${Number(report?.bag_totals?.bags_sales_amount || 0).toFixed(2)}
          </Typography>

          <Stack spacing={0.8} sx={{ mt: 1.2 }}>
            {(report?.items || []).map((i) => (
              <Stack key={i.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", borderRadius: 1.2, p: 0.8 }}>
                <Typography sx={{ fontSize: 14 }}>{i.item_name}</Typography>
                <Typography sx={{ fontSize: 14 }}>
                  Available {Number(i.on_hand_qty || 0).toFixed(0)} • Ordered {Number(i.total_ordered_qty || 0).toFixed(0)}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}
    </Box>
  );
}

export default InventoryPage;
