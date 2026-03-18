import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
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
  removeInventoryItem,
  saveInventoryBagPrice,
  saveInventoryCountsBulk,
  updateInventoryItem,
} from "../api";

function fmtDate(value) {
  if (!value) return "-";
  const d = new Date(`${value}T00:00:00`);
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function fmtDateTime(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function InventoryPage({ user }) {
  const displayName = user?.display_name || user?.username || "Unknown";
  const today = new Date().toISOString().slice(0, 10);

  const [tab, setTab] = useState("WEEKLY");
  const [items, setItems] = useState([]);
  const [sales, setSales] = useState([]);
  const [report, setReport] = useState({ items: [], bag_totals: {}, latest_count: null, activity: [] });
  const [message, setMessage] = useState({ type: "", text: "" });
  const [saving, setSaving] = useState(false);

  const [weeklyCounts, setWeeklyCounts] = useState({});
  const [managerSelect, setManagerSelect] = useState({});
  const [managerQty, setManagerQty] = useState({});

  const [newItem, setNewItem] = useState({
    item_name: "",
    category: "SUPPLY",
    vendor_name: "",
    unit_label: "unit",
    reorder_threshold: "",
    on_hand_qty: "",
    active: true,
  });
  const [editItem, setEditItem] = useState(null);

  const [bagPrice, setBagPrice] = useState(10);
  const [saleForm, setSaleForm] = useState({
    sale_date: today,
    customer_name: "",
    sale_type: "DROP_OFF",
    qty: 1,
    amount_paid: "",
  });

  const [reportFilters, setReportFilters] = useState({
    start_date: "",
    end_date: "",
    item_id: "",
  });

  const load = async (reportParams = {}) => {
    const [itemsRes, salesRes, bagPriceRes, reportRes] = await Promise.all([
      getInventoryItems(),
      getBagSales(),
      getInventoryBagPrice(),
      getInventoryReport(reportParams),
    ]);

    const list = Array.isArray(itemsRes?.data) ? itemsRes.data : [];
    setItems(list);
    setSales(Array.isArray(salesRes?.data) ? salesRes.data : []);
    setReport(reportRes?.data || { items: [], bag_totals: {}, latest_count: null, activity: [] });
    setBagPrice(Number(bagPriceRes?.data?.bag_default_price || 0));

    const nextWeekly = {};
    const nextSelect = {};
    const nextQty = {};
    list.forEach((i) => {
      nextWeekly[i.id] = "";
      nextSelect[i.id] = false;
      nextQty[i.id] = "";
    });
    setWeeklyCounts(nextWeekly);
    setManagerSelect(nextSelect);
    setManagerQty(nextQty);
  };

  useEffect(() => {
    (async () => {
      try {
        await load();
      } catch (e) {
        console.error(e);
        setMessage({ type: "error", text: "Inventory load failed." });
      }
    })();
  }, []);

  const supplyItems = useMemo(
    () => items.filter((i) => String(i.category || "").toUpperCase() === "SUPPLY" && i.active !== false),
    [items]
  );

  const allActiveItems = useMemo(() => items.filter((i) => i.active !== false), [items]);

  const latestCountedBy = report?.latest_count?.counted_by || displayName;
  const latestCountedAt = report?.latest_count?.counted_at || new Date().toISOString();

  const onSubmitWeekly = async () => {
    try {
      setSaving(true);
      const rows = supplyItems
        .map((i) => ({
          item_id: i.id,
          counted_qty: weeklyCounts[i.id],
        }))
        .filter((r) => r.counted_qty !== "" && r.counted_qty !== null && r.counted_qty !== undefined)
        .map((r) => ({ ...r, counted_qty: parseInt(r.counted_qty, 10) }));

      if (rows.length === 0) {
        setMessage({ type: "error", text: "Enter count before submit." });
        return;
      }

      if (rows.some((r) => Number.isNaN(r.counted_qty) || r.counted_qty < 0)) {
        setMessage({ type: "error", text: "Counts must be whole numbers." });
        return;
      }

      await saveInventoryCountsBulk({
        rows,
        counted_by: displayName,
        notes: `Weekly check ${today}`,
      });

      const cleared = {};
      supplyItems.forEach((i) => {
        cleared[i.id] = "";
      });
      setWeeklyCounts((prev) => ({ ...prev, ...cleared }));

      setMessage({ type: "success", text: "Submitted." });
      await load(reportFilters);

      const blankAgain = {};
      supplyItems.forEach((i) => {
        blankAgain[i.id] = "";
      });
      setWeeklyCounts((prev) => ({ ...prev, ...blankAgain }));
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Submit failed." });
    } finally {
      setSaving(false);
    }
  };

  const onOrderSelected = async () => {
    try {
      setSaving(true);
      const lines = supplyItems
        .filter((i) => managerSelect[i.id])
        .map((i) => ({
          item_id: i.id,
          requested_qty: parseInt(managerQty[i.id], 10),
        }))
        .filter((l) => !Number.isNaN(l.requested_qty) && l.requested_qty > 0);

      if (lines.length === 0) {
        setMessage({ type: "error", text: "Select items and enter order qty." });
        return;
      }

      await createInventoryReorder({
        lines,
        ordered_by: displayName,
        notes: `Manager order ${today}`,
      });

      const blankQty = {};
      const uncheck = {};
      supplyItems.forEach((i) => {
        blankQty[i.id] = "";
        uncheck[i.id] = false;
      });
      setManagerQty((prev) => ({ ...prev, ...blankQty }));
      setManagerSelect((prev) => ({ ...prev, ...uncheck }));

      setMessage({ type: "success", text: "Order submitted." });
      await load(reportFilters);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Order failed." });
    } finally {
      setSaving(false);
    }
  };

  const onSaveBagPrice = async () => {
    try {
      setSaving(true);
      await saveInventoryBagPrice({
        bag_default_price: Number(bagPrice || 0),
        updated_by: displayName,
      });
      setMessage({ type: "success", text: "Price saved." });
      await load(reportFilters);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Price save failed." });
    } finally {
      setSaving(false);
    }
  };

  const onCreateItem = async () => {
    try {
      setSaving(true);
      await createInventoryItem({
        ...newItem,
        reorder_threshold: Number(newItem.reorder_threshold || 0),
        on_hand_qty: Number(newItem.on_hand_qty || 0),
      });
      setNewItem({
        item_name: "",
        category: "SUPPLY",
        vendor_name: "",
        unit_label: "unit",
        reorder_threshold: "",
        on_hand_qty: "",
        active: true,
      });
      setMessage({ type: "success", text: "Item added." });
      await load(reportFilters);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Add failed." });
    } finally {
      setSaving(false);
    }
  };

  const onSaveEditItem = async () => {
    if (!editItem) return;
    try {
      setSaving(true);
      await updateInventoryItem({
        ...editItem,
        reorder_threshold: Number(editItem.reorder_threshold || 0),
        on_hand_qty: Number(editItem.on_hand_qty || 0),
      });
      setEditItem(null);
      setMessage({ type: "success", text: "Item updated." });
      await load(reportFilters);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Update failed." });
    } finally {
      setSaving(false);
    }
  };

  const onRemoveItem = async (id) => {
    try {
      setSaving(true);
      await removeInventoryItem(id);
      setMessage({ type: "success", text: "Item removed." });
      await load(reportFilters);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Remove failed." });
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
      });
      setMessage({ type: "success", text: "Bag sale saved." });
      await load(reportFilters);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Sale save failed." });
    } finally {
      setSaving(false);
    }
  };

  const onRunReport = async () => {
    try {
      setSaving(true);
      await load(reportFilters);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: "Report load failed." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, minHeight: "100%" }}>
      <Typography sx={{ fontSize: 30, fontWeight: 400 }}>Inventory</Typography>

      {message.text && (
        <Typography sx={{ mt: 1, color: message.type === "error" ? "#b91c1c" : "#0f766e", fontSize: 14 }}>
          {message.text}
        </Typography>
      )}

      <Paper sx={{ mt: 1.2, borderRadius: 2, overflow: "hidden" }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile>
          <Tab value="WEEKLY" label="Weekly Check" />
          <Tab value="MANAGER" label="Manager" />
          <Tab value="RETAIL" label="Retail Sales" />
          <Tab value="SETTINGS" label="Settings" />
          <Tab value="REPORT" label="Report" />
        </Tabs>
      </Paper>

      {tab === "WEEKLY" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Remaining Inventory</Typography>
          <Typography sx={{ fontSize: 14, color: "#64748b", mt: 0.3 }}>
            Counted by: {latestCountedBy} on {fmtDateTime(latestCountedAt)}
          </Typography>

          <Stack spacing={1} sx={{ mt: 1.2 }}>
            {supplyItems.map((i) => (
              <Stack key={i.id} direction="row" alignItems="center" spacing={1} sx={{ border: "1px solid #e5e7eb", borderRadius: 1.5, p: 1 }}>
                <Box sx={{ minWidth: 220 }}>
                  <Typography>{i.item_name}</Typography>
                </Box>
                <TextField
                  size="small"
                  type="number"
                  label="Count"
                  value={weeklyCounts[i.id] ?? ""}
                  onChange={(e) => setWeeklyCounts((p) => ({ ...p, [i.id]: e.target.value }))}
                  inputProps={{ step: 1, min: 0 }}
                  sx={{ maxWidth: 180 }}
                />
              </Stack>
            ))}
          </Stack>

          <Stack direction="row" justifyContent="flex-end" sx={{ mt: 1.2 }}>
            <Button variant="contained" onClick={onSubmitWeekly} disabled={saving}>
              Submit
            </Button>
          </Stack>
        </Paper>
      )}

      {tab === "MANAGER" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Manager Dashboard</Typography>
          <Typography sx={{ fontSize: 14, color: "#64748b", mt: 0.3 }}>
            Latest weekly check: {report?.latest_count?.counted_by || "-"} • {fmtDateTime(report?.latest_count?.counted_at)}
          </Typography>

          <Stack spacing={1} sx={{ mt: 1.2 }}>
            {supplyItems.map((i) => (
              <Stack key={i.id} direction="row" alignItems="center" spacing={1} sx={{ border: "1px solid #e5e7eb", borderRadius: 1.5, p: 1 }}>
                <Checkbox
                  checked={Boolean(managerSelect[i.id])}
                  onChange={(e) => setManagerSelect((p) => ({ ...p, [i.id]: e.target.checked }))}
                />
                <Box sx={{ minWidth: 260 }}>
                  <Typography>{i.item_name}</Typography>
                  <Typography sx={{ fontSize: 13, color: "#64748b" }}>Remaining {Number(i.on_hand_qty || 0).toFixed(0)}</Typography>
                </Box>
                <TextField
                  size="small"
                  type="number"
                  label="Order Qty"
                  value={managerQty[i.id] ?? ""}
                  onChange={(e) => setManagerQty((p) => ({ ...p, [i.id]: e.target.value }))}
                  inputProps={{ step: 1, min: 0 }}
                  sx={{ maxWidth: 180 }}
                />
              </Stack>
            ))}
          </Stack>

          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 1.2 }}>
            <Button
              variant="text"
              onClick={() => {
                const allSelected = supplyItems.every((r) => managerSelect[r.id]);
                const next = {};
                supplyItems.forEach((r) => {
                  next[r.id] = !allSelected;
                });
                setManagerSelect((p) => ({ ...p, ...next }));
              }}
            >
              {supplyItems.every((r) => managerSelect[r.id]) ? "Clear All" : "Select All"}
            </Button>
            <Button variant="contained" onClick={onOrderSelected} disabled={saving}>
              Order
            </Button>
          </Stack>
        </Paper>
      )}

      {tab === "RETAIL" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Retail Sales</Typography>

          <Stack direction="row" spacing={1} sx={{ mt: 1.2, flexWrap: "wrap" }}>
            <TextField size="small" type="date" label="Date" InputLabelProps={{ shrink: true }} value={saleForm.sale_date} onChange={(e) => setSaleForm((p) => ({ ...p, sale_date: e.target.value }))} />
            <TextField size="small" label="Customer" value={saleForm.customer_name} onChange={(e) => setSaleForm((p) => ({ ...p, customer_name: e.target.value }))} />
            <TextField size="small" select label="Type" value={saleForm.sale_type} onChange={(e) => setSaleForm((p) => ({ ...p, sale_type: e.target.value }))} sx={{ minWidth: 160 }}>
              <MenuItem value="DROP_OFF">Drop Off</MenuItem>
              <MenuItem value="PICKUP_DELIVERY">Pickup/Delivery</MenuItem>
            </TextField>
            <TextField size="small" type="number" label="Qty" value={saleForm.qty} onChange={(e) => setSaleForm((p) => ({ ...p, qty: e.target.value }))} sx={{ maxWidth: 90 }} />
            <TextField size="small" type="number" label="Amount" value={saleForm.amount_paid} onChange={(e) => setSaleForm((p) => ({ ...p, amount_paid: e.target.value }))} sx={{ maxWidth: 130 }} />
            <Button variant="contained" onClick={onSaveSale} disabled={saving || !saleForm.customer_name || Number(saleForm.qty) <= 0}>Save</Button>
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

      {tab === "SETTINGS" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Inventory Settings</Typography>

          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.2 }}>
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

          <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: "wrap" }}>
            <TextField
              size="small"
              label="Item Name"
              value={newItem.item_name}
              onChange={(e) => setNewItem((p) => ({ ...p, item_name: e.target.value }))}
            />
            <TextField
              size="small"
              select
              label="Category"
              value={newItem.category}
              onChange={(e) => setNewItem((p) => ({ ...p, category: e.target.value }))}
              sx={{ minWidth: 120 }}
            >
              <MenuItem value="SUPPLY">Supply</MenuItem>
              <MenuItem value="BAG">Bag</MenuItem>
            </TextField>
            <TextField
              size="small"
              label="Vendor"
              value={newItem.vendor_name}
              onChange={(e) => setNewItem((p) => ({ ...p, vendor_name: e.target.value }))}
            />
            <TextField
              size="small"
              label="Unit"
              value={newItem.unit_label}
              onChange={(e) => setNewItem((p) => ({ ...p, unit_label: e.target.value }))}
              sx={{ maxWidth: 120 }}
            />
            <TextField
              size="small"
              type="number"
              label="Reorder"
              value={newItem.reorder_threshold}
              onChange={(e) => setNewItem((p) => ({ ...p, reorder_threshold: e.target.value }))}
              sx={{ maxWidth: 120 }}
            />
            <TextField
              size="small"
              type="number"
              label="On Hand"
              value={newItem.on_hand_qty}
              onChange={(e) => setNewItem((p) => ({ ...p, on_hand_qty: e.target.value }))}
              sx={{ maxWidth: 120 }}
            />
            <Button variant="contained" onClick={onCreateItem} disabled={saving || !newItem.item_name}>Add Item</Button>
          </Stack>

          <Stack spacing={0.8} sx={{ mt: 1.5 }}>
            {allActiveItems.map((i) => (
              <Stack key={i.id} direction="row" spacing={1} alignItems="center" sx={{ border: "1px solid #e5e7eb", borderRadius: 1.2, p: 0.8 }}>
                <Typography sx={{ minWidth: 220 }}>{i.item_name}</Typography>
                <Typography sx={{ minWidth: 80, color: "#64748b", fontSize: 13 }}>{i.category}</Typography>
                <Typography sx={{ minWidth: 80, color: "#64748b", fontSize: 13 }}>Qty {Number(i.on_hand_qty || 0).toFixed(0)}</Typography>
                <Button size="small" variant="outlined" onClick={() => setEditItem({ ...i })}>Edit</Button>
                <Button size="small" color="error" variant="outlined" onClick={() => onRemoveItem(i.id)}>Remove</Button>
              </Stack>
            ))}
          </Stack>

          {editItem && (
            <Paper sx={{ mt: 1.5, p: 1.2, borderRadius: 1.2, border: "1px solid #e5e7eb" }}>
              <Typography sx={{ fontSize: 16, mb: 1 }}>Edit Item</Typography>
              <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
                <TextField size="small" label="Item Name" value={editItem.item_name || ""} onChange={(e) => setEditItem((p) => ({ ...p, item_name: e.target.value }))} />
                <TextField size="small" select label="Category" value={editItem.category || "SUPPLY"} onChange={(e) => setEditItem((p) => ({ ...p, category: e.target.value }))} sx={{ minWidth: 120 }}>
                  <MenuItem value="SUPPLY">Supply</MenuItem>
                  <MenuItem value="BAG">Bag</MenuItem>
                </TextField>
                <TextField size="small" label="Vendor" value={editItem.vendor_name || ""} onChange={(e) => setEditItem((p) => ({ ...p, vendor_name: e.target.value }))} />
                <TextField size="small" label="Unit" value={editItem.unit_label || ""} onChange={(e) => setEditItem((p) => ({ ...p, unit_label: e.target.value }))} sx={{ maxWidth: 120 }} />
                <TextField size="small" type="number" label="Reorder" value={editItem.reorder_threshold || 0} onChange={(e) => setEditItem((p) => ({ ...p, reorder_threshold: e.target.value }))} sx={{ maxWidth: 120 }} />
                <TextField size="small" type="number" label="On Hand" value={editItem.on_hand_qty || 0} onChange={(e) => setEditItem((p) => ({ ...p, on_hand_qty: e.target.value }))} sx={{ maxWidth: 120 }} />
              </Stack>
              <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ mt: 1 }}>
                <Button onClick={() => setEditItem(null)}>Cancel</Button>
                <Button variant="contained" onClick={onSaveEditItem} disabled={saving}>Save</Button>
              </Stack>
            </Paper>
          )}
        </Paper>
      )}

      {tab === "REPORT" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 400 }}>Inventory Audit Trail</Typography>

          <Stack direction="row" spacing={1} sx={{ mt: 1.2, flexWrap: "wrap" }}>
            <TextField
              size="small"
              type="date"
              label="From"
              InputLabelProps={{ shrink: true }}
              value={reportFilters.start_date}
              onChange={(e) => setReportFilters((p) => ({ ...p, start_date: e.target.value }))}
            />
            <TextField
              size="small"
              type="date"
              label="To"
              InputLabelProps={{ shrink: true }}
              value={reportFilters.end_date}
              onChange={(e) => setReportFilters((p) => ({ ...p, end_date: e.target.value }))}
            />
            <TextField
              size="small"
              select
              label="Product"
              value={reportFilters.item_id}
              onChange={(e) => setReportFilters((p) => ({ ...p, item_id: e.target.value }))}
              sx={{ minWidth: 220 }}
            >
              <MenuItem value="">All Products</MenuItem>
              {allActiveItems.map((i) => (
                <MenuItem key={i.id} value={String(i.id)}>{i.item_name}</MenuItem>
              ))}
            </TextField>
            <Button variant="contained" onClick={onRunReport} disabled={saving}>Apply</Button>
          </Stack>

          <Typography sx={{ fontSize: 14, color: "#64748b", mt: 1.2 }}>
            Bags sold {Number(report?.bag_totals?.total_bags_sold || 0).toFixed(0)} • Sales ${Number(report?.bag_totals?.bags_sales_amount || 0).toFixed(2)}
          </Typography>

          <Stack spacing={0.8} sx={{ mt: 1.2 }}>
            {(report?.activity || []).map((a) => (
              <Stack key={`${a.activity_type}-${a.id}`} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", borderRadius: 1.2, p: 0.8 }}>
                <Typography sx={{ fontSize: 14 }}>
                  {fmtDateTime(a.activity_at)} • {a.activity_type} • {a.item_name || "Bag"}
                </Typography>
                <Typography sx={{ fontSize: 14 }}>
                  Qty {Number(a.qty || 0).toFixed(0)} • {a.actor || "-"}
                </Typography>
              </Stack>
            ))}
            {(!report?.activity || report.activity.length === 0) && (
              <Typography sx={{ fontSize: 14, color: "#64748b" }}>No activity found.</Typography>
            )}
          </Stack>
        </Paper>
      )}
    </Box>
  );
}

export default InventoryPage;
