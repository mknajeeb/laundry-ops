import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  Grid,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  createBagSale,
  createInventoryAdjustment,
  createInventoryCategory,
  createInventoryItem,
  createInventoryVendor,
  getBagSales,
  getInventoryItemHistory,
  getInventoryItems,
  removeInventoryItem,
  saveInventoryBagPrice,
  saveInventoryVarianceThreshold,
  updateInventoryCategory,
  updateInventoryItem,
  updateInventoryVendor,
} from "../../api";
import {
  ADJUSTMENT_REASON_LABELS,
  STATUS_LEVEL_LABELS,
  TRACKING_MODE_LABELS,
  canManageInventorySettings,
} from "../../utils/inventoryRoleHelpers";
import { CurrencyField, QtyStepper, SectionCard } from "./InventoryShared";
import { emptyItemForm, formatCurrency, formatDateTime, INV_INPUT_SX } from "../../utils/inventoryHelpers";

function CategoriesPanel({ categories, onRefresh, onMessage }) {
  const [form, setForm] = useState({ name: "", sort_order: "", is_active: true });
  const [edit, setEdit] = useState(null);

  const onSave = async () => {
    try {
      const payload = edit
        ? { id: edit.id, name: edit.name, sort_order: Number(edit.sort_order || 0), is_active: edit.is_active }
        : { ...form, sort_order: Number(form.sort_order || 0) };
      if (edit) await updateInventoryCategory(payload);
      else await createInventoryCategory(payload);
      setForm({ name: "", sort_order: "", is_active: true });
      setEdit(null);
      onMessage?.({ type: "success", text: "Category saved." });
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Save failed." });
    }
  };

  return (
    <SectionCard title="Categories">
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        <Grid item xs={12} sm={5}>
          <TextField label="Category name" fullWidth value={edit?.name ?? form.name} onChange={(e) => edit ? setEdit({ ...edit, name: e.target.value }) : setForm((p) => ({ ...p, name: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <TextField label="Sort order" type="number" fullWidth value={edit?.sort_order ?? form.sort_order} onChange={(e) => edit ? setEdit({ ...edit, sort_order: e.target.value }) : setForm((p) => ({ ...p, sort_order: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={6} sm={2}>
          <FormControlLabel
            control={<Checkbox checked={edit?.is_active ?? form.is_active} onChange={(e) => edit ? setEdit({ ...edit, is_active: e.target.checked }) : setForm((p) => ({ ...p, is_active: e.target.checked }))} />}
            label="Active"
          />
        </Grid>
        <Grid item xs={12} sm={2}>
          <Button variant="contained" fullWidth onClick={onSave} sx={{ height: "100%" }}>
            {edit ? "Update" : "Add"}
          </Button>
        </Grid>
      </Grid>
      {edit ? <Button size="small" onClick={() => setEdit(null)} sx={{ mb: 1 }}>Cancel edit</Button> : null}
      {(categories || []).map((c) => (
        <Stack key={c.id} direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 1, borderBottom: "1px solid", borderColor: "divider" }}>
          <Typography variant="body2">{c.name} · sort {c.sort_order} · {c.is_active ? "Active" : "Inactive"}</Typography>
          <Button size="small" onClick={() => setEdit({ ...c, is_active: Boolean(c.is_active) })}>Edit</Button>
        </Stack>
      ))}
    </SectionCard>
  );
}

function VendorsPanel({ vendors, onRefresh, onMessage }) {
  const [form, setForm] = useState({ name: "", phone: "", email: "", payment_method: "", notes: "" });
  const [edit, setEdit] = useState(null);

  const onSave = async () => {
    try {
      const payload = edit ? { ...edit } : { ...form };
      if (edit) await updateInventoryVendor(payload);
      else await createInventoryVendor(payload);
      setForm({ name: "", phone: "", email: "", payment_method: "", notes: "" });
      setEdit(null);
      onMessage?.({ type: "success", text: "Vendor saved." });
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Save failed." });
    }
  };

  return (
    <SectionCard title="Vendors">
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        <Grid item xs={12} sm={4}>
          <TextField label="Vendor name" fullWidth value={edit?.name ?? form.name} onChange={(e) => edit ? setEdit({ ...edit, name: e.target.value }) : setForm((p) => ({ ...p, name: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <TextField label="Phone" fullWidth value={edit?.phone ?? form.phone} onChange={(e) => edit ? setEdit({ ...edit, phone: e.target.value }) : setForm((p) => ({ ...p, phone: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <TextField label="Email" fullWidth value={edit?.email ?? form.email} onChange={(e) => edit ? setEdit({ ...edit, email: e.target.value }) : setForm((p) => ({ ...p, email: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={12} sm={2}>
          <Button variant="contained" fullWidth onClick={onSave} sx={{ height: "100%" }}>
            {edit ? "Update" : "Add"}
          </Button>
        </Grid>
      </Grid>
      {edit ? <Button size="small" onClick={() => setEdit(null)} sx={{ mb: 1 }}>Cancel edit</Button> : null}
      {(vendors || []).map((v) => (
        <Stack key={v.id} direction="row" justifyContent="space-between" sx={{ py: 1, borderBottom: "1px solid", borderColor: "divider" }}>
          <Typography variant="body2">{v.name}{v.phone ? ` · ${v.phone}` : ""}</Typography>
          <Button size="small" onClick={() => setEdit(v)}>Edit</Button>
        </Stack>
      ))}
    </SectionCard>
  );
}

function ItemsPanel({ items, categories, vendors, onRefresh, onMessage }) {
  const [form, setForm] = useState(emptyItemForm());
  const [edit, setEdit] = useState(null);
  const [allItems, setAllItems] = useState(items || []);
  const [showInactive, setShowInactive] = useState(true);

  const loadItems = async () => {
    try {
      const res = await getInventoryItems({ active_only: "0" });
      setAllItems(res?.data || []);
    } catch (e) {
      console.error(e);
      setAllItems(items || []);
    }
  };

  useEffect(() => {
    loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const onSave = async () => {
    try {
      const src = edit || form;
      const isStatus = String(src.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
      const payload = {
        ...src,
        id: edit?.id,
        name: src.name,
        category_id: Number(src.category_id),
        default_vendor_id: src.default_vendor_id || null,
        reorder_level: Number(src.reorder_level || 0),
        suggested_order_qty: Number(src.suggested_order_qty || 0),
        default_unit_cost: Number(src.default_unit_cost || 0),
        current_on_hand: isStatus ? 0 : Number(src.current_on_hand || 0),
        target_stock: Number(src.target_stock || 0),
        pack_size: Number(src.pack_size || 1),
        tracking_mode: isStatus ? "STATUS" : "QUANTITY",
        status_level: isStatus ? (src.status_level || "OK") : null,
        is_active: Boolean(src.is_active !== false),
        track_weekly_check: Boolean(src.track_weekly_check),
        track_retail_sale: Boolean(src.track_retail_sale),
      };
      if (edit) await updateInventoryItem(payload);
      else await createInventoryItem(payload);
      setForm(emptyItemForm());
      setEdit(null);
      onMessage?.({ type: "success", text: "Item saved." });
      await loadItems();
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Save failed." });
    }
  };

  const onRemove = async (id) => {
    try {
      await removeInventoryItem(id);
      onMessage?.({ type: "success", text: "Item deactivated." });
      await loadItems();
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Remove failed." });
    }
  };

  const f = edit || form;
  const setF = edit ? setEdit : setForm;
  const isStatus = String(f.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
  const visibleItems = (allItems || []).filter((i) => showInactive || i.is_active !== false);

  return (
    <SectionCard title="Items">
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        <Grid item xs={12}>
          <TextField label="Item name" fullWidth value={f.name} onChange={(e) => setF((p) => ({ ...p, name: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={12} sm={6}>
          <TextField select label="Category" fullWidth value={f.category_id} onChange={(e) => setF((p) => ({ ...p, category_id: e.target.value }))} sx={INV_INPUT_SX}>
            <MenuItem value="">Select</MenuItem>
            {(categories || []).map((c) => <MenuItem key={c.id} value={String(c.id)}>{c.name}</MenuItem>)}
          </TextField>
        </Grid>
        <Grid item xs={6} sm={3}>
          <TextField label="Unit" fullWidth value={f.unit} onChange={(e) => setF((p) => ({ ...p, unit: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <TextField label="SKU" fullWidth value={f.sku || ""} onChange={(e) => setF((p) => ({ ...p, sku: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={12} sm={6}>
          <TextField select label="Default vendor" fullWidth value={f.default_vendor_id || ""} onChange={(e) => setF((p) => ({ ...p, default_vendor_id: e.target.value }))} sx={INV_INPUT_SX}>
            <MenuItem value="">None</MenuItem>
            {(vendors || []).map((v) => <MenuItem key={v.id} value={String(v.id)}>{v.name}</MenuItem>)}
          </TextField>
        </Grid>
        <Grid item xs={12} sm={6}>
          <TextField
            select
            label="Tracking"
            fullWidth
            value={f.tracking_mode || "QUANTITY"}
            onChange={(e) => setF((p) => ({
              ...p,
              tracking_mode: e.target.value,
              status_level: e.target.value === "STATUS" ? (p.status_level || "OK") : p.status_level,
            }))}
            sx={INV_INPUT_SX}
            helperText={isStatus ? "No count — pick OK / Low / Out on stock check" : "Count on-hand quantity"}
          >
            {Object.entries(TRACKING_MODE_LABELS).map(([k, lbl]) => (
              <MenuItem key={k} value={k}>{lbl}</MenuItem>
            ))}
          </TextField>
        </Grid>

        {isStatus ? (
          <>
            <Grid item xs={12} sm={6}>
              <TextField
                select
                label="Current status"
                fullWidth
                value={f.status_level || "OK"}
                onChange={(e) => setF((p) => ({ ...p, status_level: e.target.value }))}
                sx={INV_INPUT_SX}
              >
                {Object.entries(STATUS_LEVEL_LABELS).map(([k, lbl]) => (
                  <MenuItem key={k} value={k}>{lbl}</MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={6} sm={3}>
              <TextField label="Suggested qty" type="number" fullWidth value={f.suggested_order_qty} onChange={(e) => setF((p) => ({ ...p, suggested_order_qty: e.target.value }))} sx={INV_INPUT_SX} helperText="Used when Low/Out" />
            </Grid>
            <Grid item xs={6} sm={3}>
              <TextField label="Unit cost" type="number" fullWidth value={f.default_unit_cost} onChange={(e) => setF((p) => ({ ...p, default_unit_cost: e.target.value }))} sx={INV_INPUT_SX} />
            </Grid>
          </>
        ) : (
          <>
            <Grid item xs={6} sm={3}>
              <TextField label="Pack size" type="number" fullWidth value={f.pack_size ?? 1} onChange={(e) => setF((p) => ({ ...p, pack_size: e.target.value }))} sx={INV_INPUT_SX} />
            </Grid>
            <Grid item xs={6} sm={3}>
              <TextField label="Target stock" type="number" fullWidth value={f.target_stock ?? ""} onChange={(e) => setF((p) => ({ ...p, target_stock: e.target.value }))} sx={INV_INPUT_SX} />
            </Grid>
            <Grid item xs={6} sm={3}>
              <TextField label="Reorder at" type="number" fullWidth value={f.reorder_level} onChange={(e) => setF((p) => ({ ...p, reorder_level: e.target.value }))} sx={INV_INPUT_SX} />
            </Grid>
            <Grid item xs={6} sm={3}>
              <TextField label="Suggested qty" type="number" fullWidth value={f.suggested_order_qty} onChange={(e) => setF((p) => ({ ...p, suggested_order_qty: e.target.value }))} sx={INV_INPUT_SX} />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Unit cost" type="number" fullWidth value={f.default_unit_cost} onChange={(e) => setF((p) => ({ ...p, default_unit_cost: e.target.value }))} sx={INV_INPUT_SX} />
            </Grid>
            {!edit ? (
              <Grid item xs={12} sm={6}>
                <QtyStepper
                  label="On hand"
                  value={f.current_on_hand === "" || f.current_on_hand == null ? "0" : String(f.current_on_hand)}
                  onChange={(v) => setF((p) => ({ ...p, current_on_hand: v }))}
                />
              </Grid>
            ) : null}
          </>
        )}

        <Grid item xs={12}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <FormControlLabel
              control={<Checkbox checked={f.is_active !== false} onChange={(e) => setF((p) => ({ ...p, is_active: e.target.checked }))} />}
              label="Active"
            />
            <FormControlLabel control={<Checkbox checked={f.track_weekly_check} onChange={(e) => setF((p) => ({ ...p, track_weekly_check: e.target.checked }))} />} label="Weekly check" />
            <FormControlLabel control={<Checkbox checked={f.track_retail_sale} onChange={(e) => setF((p) => ({ ...p, track_retail_sale: e.target.checked }))} />} label="Retail sale" />
          </Stack>
        </Grid>
        <Grid item xs={12}>
          <TextField label="Notes" fullWidth value={f.notes} onChange={(e) => setF((p) => ({ ...p, notes: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={12}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <Button variant="contained" size="large" fullWidth={false} sx={{ minHeight: 48, width: { xs: "100%", sm: "auto" } }} onClick={onSave}>
              {edit ? "Update Item" : "Add Item"}
            </Button>
            {edit ? <Button size="large" sx={{ minHeight: 48 }} onClick={() => setEdit(null)}>Cancel</Button> : null}
          </Stack>
        </Grid>
      </Grid>

      <FormControlLabel
        sx={{ mb: 1 }}
        control={<Checkbox checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />}
        label="Show inactive items"
      />

      {visibleItems.map((i) => {
        const inactive = i.is_active === false;
        const statusMode = String(i.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
        return (
          <Stack
            key={i.id}
            direction={{ xs: "column", sm: "row" }}
            justifyContent="space-between"
            alignItems={{ xs: "stretch", sm: "center" }}
            spacing={1}
            sx={{ py: 1.25, borderBottom: "1px solid", borderColor: "divider", opacity: inactive ? 0.65 : 1 }}
          >
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography variant="body2" fontWeight={600}>{i.name || i.item_name}</Typography>
                {inactive ? <Chip size="small" label="Inactive" /> : null}
                {statusMode ? <Chip size="small" color="info" variant="outlined" label="Status" /> : null}
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {i.category_name} · {i.unit}
                {statusMode
                  ? ` · ${STATUS_LEVEL_LABELS[String(i.status_level || "OK").toUpperCase()] || i.status_level}`
                  : ` · Qty ${Number(i.current_on_hand ?? 0)}`}
                {i.avg_weekly_usage ? ` · ~${i.avg_weekly_usage}/wk` : ""}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button
                size="large"
                sx={{ minHeight: 44, flex: { xs: 1, sm: "none" } }}
                onClick={() => setEdit({
                  ...i,
                  name: i.name || i.item_name,
                  category_id: String(i.category_id || ""),
                  default_vendor_id: i.default_vendor_id ? String(i.default_vendor_id) : "",
                  reorder_level: i.reorder_level ?? "",
                  suggested_order_qty: i.suggested_order_qty ?? "",
                  default_unit_cost: i.default_unit_cost ?? "",
                  current_on_hand: i.current_on_hand ?? "",
                  target_stock: i.target_stock ?? "",
                  pack_size: i.pack_size ?? 1,
                  tracking_mode: i.tracking_mode || "QUANTITY",
                  status_level: i.status_level || "OK",
                  is_active: i.is_active !== false,
                  track_weekly_check: i.track_weekly_check !== false,
                  track_retail_sale: Boolean(i.track_retail_sale),
                })}
              >
                Edit
              </Button>
              {!inactive ? (
                <Button size="large" color="error" sx={{ minHeight: 44, flex: { xs: 1, sm: "none" } }} onClick={() => onRemove(i.id)}>
                  Deactivate
                </Button>
              ) : null}
            </Stack>
          </Stack>
        );
      })}
    </SectionCard>
  );
}

function PricingPanel({ bagPrice, onRefresh, onMessage, user }) {
  const [price, setPrice] = useState(bagPrice ?? 10);
  const [sales, setSales] = useState([]);
  const [saleForm, setSaleForm] = useState({
    sale_date: new Date().toISOString().slice(0, 10),
    customer_name: "",
    sale_type: "DROP_OFF",
    qty: 1,
    amount_paid: "",
  });

  const loadSales = async () => {
    try {
      const res = await getBagSales();
      setSales(res?.data || []);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadSales();
  }, []);

  const onSavePrice = async () => {
    try {
      await saveInventoryBagPrice({ bag_default_price: Number(price || 0) });
      onMessage?.({ type: "success", text: "Bag price saved." });
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Save failed." });
    }
  };

  const onSaveSale = async () => {
    try {
      const payload = {
        ...saleForm,
        qty: Number(saleForm.qty),
        amount_paid: saleForm.amount_paid || (Number(price || 0) * Number(saleForm.qty)).toFixed(2),
      };
      await createBagSale(payload);
      setSaleForm({ sale_date: new Date().toISOString().slice(0, 10), customer_name: "", sale_type: "DROP_OFF", qty: 1, amount_paid: "" });
      onMessage?.({ type: "success", text: "Sale recorded." });
      await loadSales();
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Sale failed." });
    }
  };

  return (
    <Stack spacing={2}>
      <SectionCard title="Bag / Retail Pricing">
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
          <CurrencyField label="Default bag price" value={price} onChange={(e) => setPrice(e.target.value)} sx={{ maxWidth: 200 }} />
          <Button variant="contained" onClick={onSavePrice}>Save Price</Button>
        </Stack>
      </SectionCard>

      <SectionCard title="Retail Bag Sales">
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          <Grid item xs={6} sm={3}>
            <TextField label="Date" type="date" fullWidth InputLabelProps={{ shrink: true }} value={saleForm.sale_date} onChange={(e) => setSaleForm((p) => ({ ...p, sale_date: e.target.value }))} sx={INV_INPUT_SX} />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField label="Customer" fullWidth value={saleForm.customer_name} onChange={(e) => setSaleForm((p) => ({ ...p, customer_name: e.target.value }))} sx={INV_INPUT_SX} />
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField select label="Type" fullWidth value={saleForm.sale_type} onChange={(e) => setSaleForm((p) => ({ ...p, sale_type: e.target.value }))} sx={INV_INPUT_SX}>
              <MenuItem value="DROP_OFF">Drop Off</MenuItem>
              <MenuItem value="PICKUP_DELIVERY">Pickup/Delivery</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={4} sm={1}>
            <TextField label="Qty" type="number" fullWidth value={saleForm.qty} onChange={(e) => setSaleForm((p) => ({ ...p, qty: e.target.value }))} sx={INV_INPUT_SX} />
          </Grid>
          <Grid item xs={8} sm={2}>
            <TextField label="Amount" type="number" fullWidth value={saleForm.amount_paid} placeholder={formatCurrency(Number(price) * Number(saleForm.qty))} onChange={(e) => setSaleForm((p) => ({ ...p, amount_paid: e.target.value }))} sx={INV_INPUT_SX} />
          </Grid>
          <Grid item xs={12} sm={1}>
            <Button variant="contained" fullWidth onClick={onSaveSale} disabled={!saleForm.customer_name} sx={{ height: "100%" }}>Save</Button>
          </Grid>
        </Grid>
        {(sales || []).slice(0, 30).map((s) => (
          <Stack key={s.id} direction="row" justifyContent="space-between" sx={{ py: 0.75, borderBottom: "1px solid", borderColor: "divider" }}>
            <Typography variant="body2">{String(s.sale_date).slice(0, 10)} · {s.customer_name} · Qty {s.qty}</Typography>
            <Typography variant="body2">{s.amount_paid || "NOT CHARGED"}</Typography>
          </Stack>
        ))}
      </SectionCard>
    </Stack>
  );
}

export function AdjustmentsPanel({ items, onMessage, onRefresh }) {
  const [form, setForm] = useState({ item_id: "", qty_change: "", reason_code: "CORRECTION", reason: "" });
  const onSave = async () => {
    try {
      await createInventoryAdjustment({
        item_id: Number(form.item_id),
        qty_change: Number(form.qty_change),
        reason_code: form.reason_code,
        reason: form.reason,
      });
      setForm({ item_id: "", qty_change: "", reason_code: "CORRECTION", reason: "" });
      onMessage?.({ type: "success", text: "Adjustment recorded." });
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Adjustment failed." });
    }
  };
  return (
    <SectionCard title="Inventory Adjustments" subtitle="Managers only — every quantity change is logged">
      <Grid container spacing={1.5}>
        <Grid item xs={12} sm={5}>
          <TextField select label="Item" fullWidth value={form.item_id} onChange={(e) => setForm((p) => ({ ...p, item_id: e.target.value }))} sx={INV_INPUT_SX}>
            <MenuItem value="">Select item</MenuItem>
            {(items || []).map((i) => <MenuItem key={i.id} value={String(i.id)}>{i.name || i.item_name}</MenuItem>)}
          </TextField>
        </Grid>
        <Grid item xs={6} sm={2}>
          <TextField label="Qty change (+/−)" type="number" fullWidth value={form.qty_change} onChange={(e) => setForm((p) => ({ ...p, qty_change: e.target.value }))} sx={INV_INPUT_SX} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <TextField select label="Reason" fullWidth value={form.reason_code} onChange={(e) => setForm((p) => ({ ...p, reason_code: e.target.value }))} sx={INV_INPUT_SX}>
            {Object.entries(ADJUSTMENT_REASON_LABELS).map(([k, lbl]) => <MenuItem key={k} value={k}>{lbl}</MenuItem>)}
          </TextField>
        </Grid>
        <Grid item xs={12} sm={2}>
          <Button variant="contained" fullWidth onClick={onSave} sx={{ height: "100%" }} disabled={!form.item_id || !form.qty_change}>Apply</Button>
        </Grid>
      </Grid>
    </SectionCard>
  );
}

function ItemHistoryPanel({ items }) {
  const [itemId, setItemId] = useState("");
  const [history, setHistory] = useState([]);
  const load = async (id) => {
    if (!id) return;
    const res = await getInventoryItemHistory(id);
    setHistory(res?.data || []);
  };
  return (
    <SectionCard title="Item Purchase & Movement History">
      <TextField select label="Item" fullWidth value={itemId} onChange={(e) => { setItemId(e.target.value); load(e.target.value); }} sx={{ mb: 2, ...INV_INPUT_SX }}>
        <MenuItem value="">Select item</MenuItem>
        {(items || []).map((i) => <MenuItem key={i.id} value={String(i.id)}>{i.name || i.item_name}</MenuItem>)}
      </TextField>
      {history.map((h, idx) => {
        const prev = h.previous_qty;
        const next = h.display_qty;
        const trail = prev != null && next != null ? `${prev} → ${next}` : null;
        return (
          <Typography key={idx} variant="body2" sx={{ py: 0.75, borderBottom: "1px solid", borderColor: "divider" }}>
            {formatDateTime(h.event_at)} · {h.actor || "Someone"} · {h.event_label}
            {trail ? ` · ${trail}` : (h.qty_change != null ? ` · ${h.qty_change > 0 ? "+" : ""}${h.qty_change}` : "")}
            {h.note ? ` · ${h.note}` : ""}
          </Typography>
        );
      })}
    </SectionCard>
  );
}

export default function SettingsTab({ items, categories, vendors, bagPrice, varianceThreshold, roleTier, onRefresh, onMessage, user, hasPerm }) {
  const [subTab, setSubTab] = useState(0);
  const [threshold, setThreshold] = useState(varianceThreshold ?? 5);
  const isAdmin = canManageInventorySettings(roleTier, hasPerm);

  const onSaveThreshold = async () => {
    try {
      await saveInventoryVarianceThreshold({ variance_threshold: Number(threshold) });
      onMessage?.({ type: "success", text: "Variance threshold saved." });
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Save failed." });
    }
  };

  return (
    <Box>
      <Tabs value={subTab} onChange={(_, v) => setSubTab(v)} variant="scrollable" sx={{ mb: 2 }}>
        {isAdmin ? <Tab label="Items" /> : null}
        {isAdmin ? <Tab label="Categories" /> : null}
        {isAdmin ? <Tab label="Vendors" /> : null}
        {isAdmin ? <Tab label="Pricing & Retail" /> : null}
        <Tab label="Adjustments" />
        <Tab label="Item History" />
        {isAdmin ? <Tab label="Operational" /> : null}
      </Tabs>

      {isAdmin && subTab === 0 ? <ItemsPanel items={items} categories={categories} vendors={vendors} onRefresh={onRefresh} onMessage={onMessage} /> : null}
      {isAdmin && subTab === 1 ? <CategoriesPanel categories={categories} onRefresh={onRefresh} onMessage={onMessage} /> : null}
      {isAdmin && subTab === 2 ? <VendorsPanel vendors={vendors} onRefresh={onRefresh} onMessage={onMessage} /> : null}
      {isAdmin && subTab === 3 ? <PricingPanel bagPrice={bagPrice} onRefresh={onRefresh} onMessage={onMessage} user={user} /> : null}
      {subTab === (isAdmin ? 4 : 0) ? <AdjustmentsPanel items={items} onRefresh={onRefresh} onMessage={onMessage} /> : null}
      {subTab === (isAdmin ? 5 : 1) ? <ItemHistoryPanel items={items} /> : null}
      {isAdmin && subTab === 6 ? (
        <SectionCard title="Operational Settings">
          <TextField label="Count variance threshold" type="number" value={threshold} onChange={(e) => setThreshold(e.target.value)} sx={{ maxWidth: 200, ...INV_INPUT_SX }} helperText="Require reason when count differs by more than this amount" />
          <Button variant="contained" sx={{ mt: 1 }} onClick={onSaveThreshold}>Save Threshold</Button>
        </SectionCard>
      ) : null}
    </Box>
  );
}
