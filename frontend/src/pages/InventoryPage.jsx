import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
  Chip,
} from "@mui/material";
import {
  createBagSale,
  createInventoryItem,
  getBagSales,
  getInventoryItems,
  getLowStockItems,
  saveInventoryCount,
} from "../api";

function InventoryPage() {
  const [tab, setTab] = useState("ITEMS");
  const [items, setItems] = useState([]);
  const [sales, setSales] = useState([]);
  const [low, setLow] = useState([]);
  const [openItem, setOpenItem] = useState(false);
  const [openCount, setOpenCount] = useState(false);
  const [openSale, setOpenSale] = useState(false);
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [saving, setSaving] = useState(false);

  const [itemForm, setItemForm] = useState({
    item_name: "",
    category: "SUPPLY",
    vendor_name: "",
    unit_label: "unit",
    reorder_threshold: 0,
    on_hand_qty: 0,
    active: true,
  });

  const [countForm, setCountForm] = useState({
    item_id: "",
    counted_qty: "",
    counted_by: "admin",
    notes: "",
  });

  const [saleForm, setSaleForm] = useState({
    sale_date: new Date().toISOString().slice(0, 10),
    customer_name: "",
    sale_type: "DROP_OFF",
    qty: 1,
    amount_paid: "",
    entered_by: "frontdesk",
  });

  const load = async () => {
    try {
      const [i, s, l] = await Promise.all([getInventoryItems(), getBagSales(), getLowStockItems()]);
      setItems(Array.isArray(i.data) ? i.data : []);
      setSales(Array.isArray(s.data) ? s.data : []);
      setLow(Array.isArray(l.data) ? l.data : []);
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: "Failed to load inventory data." });
    }
  };

  useEffect(() => {
    load();
  }, []);

  const bagItem = useMemo(
    () => items.find((x) => String(x.category).toUpperCase() === "BAG"),
    [items]
  );

  const saveItem = async () => {
    try {
      setSaving(true);
      await createInventoryItem(itemForm);
      setOpenItem(false);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Create item failed." });
    } finally {
      setSaving(false);
    }
  };

  const saveCount = async () => {
    try {
      setSaving(true);
      await saveInventoryCount({ ...countForm, counted_qty: Number(countForm.counted_qty) });
      setOpenCount(false);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Save count failed." });
    } finally {
      setSaving(false);
    }
  };

  const saveSale = async () => {
    try {
      setSaving(true);
      await createBagSale({ ...saleForm, qty: Number(saleForm.qty) });
      setOpenSale(false);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Save sale failed." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, minHeight: "100%" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 28 }}>Inventory</Typography>
        <Stack direction="row" spacing={1}>
          <Chip label={`Items ${items.length}`} />
          <Chip label={`Low ${low.length}`} color={low.length ? "error" : "success"} />
        </Stack>
      </Stack>
      {message.text && <Alert severity={message.type} sx={{ mt: 1 }}>{message.text}</Alert>}

      <Paper sx={{ mt: 1.2, borderRadius: 2, overflow: "hidden" }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="fullWidth">
          <Tab value="ITEMS" label="Items" />
          <Tab value="COUNTS" label="Counts" />
          <Tab value="BAGS" label="Bag Sales" />
        </Tabs>
      </Paper>

      {tab === "ITEMS" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography sx={{ fontSize: 20 }}>Item Master</Typography>
            <Button variant="contained" onClick={() => setOpenItem(true)}>Add Item</Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {items.map((i) => (
              <Stack key={i.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", p: 1, borderRadius: 1.5 }}>
                <Box>
                  <Typography>{i.item_name}</Typography>
                  <Typography sx={{ color: "#64748b", fontSize: 13 }}>
                    {i.category} • {i.vendor_name || "No vendor"} • reorder at {i.reorder_threshold}
                  </Typography>
                </Box>
                <Chip label={`${Number(i.on_hand_qty || 0).toFixed(0)} ${i.unit_label || "unit"}`} color={Number(i.on_hand_qty || 0) <= Number(i.reorder_threshold || 0) ? "error" : "default"} />
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      {tab === "COUNTS" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography sx={{ fontSize: 20 }}>Weekly Counts</Typography>
            <Button variant="contained" onClick={() => setOpenCount(true)}>Log Count</Button>
          </Stack>
          {low.length > 0 && (
            <Alert severity="warning" sx={{ mt: 1 }}>
              Low stock: {low.map((x) => x.item_name).join(", ")}
            </Alert>
          )}
        </Paper>
      )}

      {tab === "BAGS" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography sx={{ fontSize: 20 }}>
              Washpro Bag Sales {bagItem ? `(On Hand: ${Number(bagItem.on_hand_qty || 0)})` : ""}
            </Typography>
            <Button variant="contained" onClick={() => setOpenSale(true)}>Record Sale</Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {sales.slice(0, 100).map((s) => (
              <Stack key={s.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", p: 1, borderRadius: 1.5 }}>
                <Box>
                  <Typography>{s.customer_name}</Typography>
                  <Typography sx={{ color: "#64748b", fontSize: 13 }}>
                    {String(s.sale_date).slice(0, 10)} • {s.sale_type} • Qty {s.qty}
                  </Typography>
                </Box>
                <Chip label={s.amount_paid || "NOT CHARGED"} />
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      <Dialog open={openItem} onClose={() => setOpenItem(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add Inventory Item</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField label="Item Name" value={itemForm.item_name} onChange={(e) => setItemForm((p) => ({ ...p, item_name: e.target.value }))} />
            <TextField select label="Category" value={itemForm.category} onChange={(e) => setItemForm((p) => ({ ...p, category: e.target.value }))}>
              <MenuItem value="SUPPLY">SUPPLY</MenuItem>
              <MenuItem value="BAG">BAG</MenuItem>
            </TextField>
            <TextField label="Vendor" value={itemForm.vendor_name} onChange={(e) => setItemForm((p) => ({ ...p, vendor_name: e.target.value }))} />
            <TextField label="Unit Label" value={itemForm.unit_label} onChange={(e) => setItemForm((p) => ({ ...p, unit_label: e.target.value }))} />
            <TextField type="number" label="Reorder Threshold" value={itemForm.reorder_threshold} onChange={(e) => setItemForm((p) => ({ ...p, reorder_threshold: e.target.value }))} />
            <TextField type="number" label="On Hand Qty" value={itemForm.on_hand_qty} onChange={(e) => setItemForm((p) => ({ ...p, on_hand_qty: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenItem(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveItem} disabled={saving || !itemForm.item_name}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={openCount} onClose={() => setOpenCount(false)} fullWidth maxWidth="sm">
        <DialogTitle>Log Inventory Count</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField select label="Item" value={countForm.item_id} onChange={(e) => setCountForm((p) => ({ ...p, item_id: e.target.value }))}>
              {items.map((i) => <MenuItem key={i.id} value={i.id}>{i.item_name}</MenuItem>)}
            </TextField>
            <TextField type="number" label="Counted Qty" value={countForm.counted_qty} onChange={(e) => setCountForm((p) => ({ ...p, counted_qty: e.target.value }))} />
            <TextField label="Counted By" value={countForm.counted_by} onChange={(e) => setCountForm((p) => ({ ...p, counted_by: e.target.value }))} />
            <TextField label="Notes" value={countForm.notes} onChange={(e) => setCountForm((p) => ({ ...p, notes: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenCount(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveCount} disabled={saving || !countForm.item_id || countForm.counted_qty === ""}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={openSale} onClose={() => setOpenSale(false)} fullWidth maxWidth="sm">
        <DialogTitle>Record Bag Sale</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField type="date" label="Date" value={saleForm.sale_date} InputLabelProps={{ shrink: true }} onChange={(e) => setSaleForm((p) => ({ ...p, sale_date: e.target.value }))} />
            <TextField label="Customer Name" value={saleForm.customer_name} onChange={(e) => setSaleForm((p) => ({ ...p, customer_name: e.target.value }))} />
            <TextField select label="Type" value={saleForm.sale_type} onChange={(e) => setSaleForm((p) => ({ ...p, sale_type: e.target.value }))}>
              <MenuItem value="DROP_OFF">Drop Off</MenuItem>
              <MenuItem value="PICKUP_DELIVERY">Pickup/Delivery</MenuItem>
            </TextField>
            <TextField type="number" label="# of Bags" value={saleForm.qty} onChange={(e) => setSaleForm((p) => ({ ...p, qty: e.target.value }))} />
            <TextField label="Amount Paid" value={saleForm.amount_paid} onChange={(e) => setSaleForm((p) => ({ ...p, amount_paid: e.target.value }))} />
            <TextField label="Entered By" value={saleForm.entered_by} onChange={(e) => setSaleForm((p) => ({ ...p, entered_by: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenSale(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveSale} disabled={saving || !saleForm.customer_name || Number(saleForm.qty) <= 0}>Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default InventoryPage;

