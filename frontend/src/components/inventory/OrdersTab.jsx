import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  duplicateInventoryOrder,
  createInventoryOrder,
  getInventoryOrders,
  getInventoryOrdersSummary,
  getInventoryWeeklyOrderReport,
  getInventoryReport,
  receiveInventoryOrder,
} from "../../api";
import { AdjustmentsPanel } from "./SettingsTab";
import {
  CategoryAccordion,
  CurrencyField,
  EstimatedLineTotal,
  LoadingBlock,
  OrderStatusBadge,
  QtyStepper,
  SectionCard,
  StatusAlert,
  SummaryStatCard,
} from "./InventoryShared";
import {
  emptyOrderForm,
  formatCurrency,
  formatDate,
  formatDateTime,
  groupItemsByCategory,
  INV_INPUT_SX,
  parseMoneyInput,
} from "../../utils/inventoryHelpers";

function ReorderItemRow({ item, selected, qty, onSelect, onQtyChange }) {
  const unitCost = item.default_unit_cost || 0;
  const suggested = item.suggested_qty ?? item.suggested_order_qty ?? 1;
  return (
    <PaperRow item={item}>
      <Stack direction="row" alignItems="flex-start" spacing={1}>
        <Checkbox checked={selected} onChange={(e) => onSelect(e.target.checked)} sx={{ mt: 0.5 }} />
        <Box sx={{ flex: 1 }}>
          <Typography fontWeight={700}>{item.name || item.item_name}</Typography>
          <Typography variant="body2" color="text.secondary">
            {item.category_name || item.category} · On hand {Number(item.current_on_hand ?? 0)} · Reorder at{" "}
            {Number(item.reorder_level ?? 0)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Suggested: {suggested} {item.unit || "unit"} · {formatCurrency(unitCost)}/unit
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1.5 }}>
            <TextField
              label="Order qty"
              type="number"
              size="small"
              value={qty}
              onChange={(e) => onQtyChange(e.target.value)}
              inputProps={{ min: 0, step: 1 }}
              sx={{ ...INV_INPUT_SX, maxWidth: 140 }}
            />
            <EstimatedLineTotal qty={qty || suggested} unitCost={unitCost} />
          </Stack>
        </Box>
      </Stack>
    </PaperRow>
  );
}

function PaperRow({ item, children }) {
  return (
    <Box
      sx={{
        p: 2,
        mb: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: "divider",
      }}
    >
      {children}
    </Box>
  );
}

function CreateOrderDialog({ open, onClose, vendors, suggestions, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState(() => ({
    ...emptyOrderForm(),
    order_date: today,
    lines: (suggestions || []).map((s) => ({
      item_id: s.id,
      item_name: s.name || s.item_name,
      qty_ordered: s.suggested_qty ?? s.suggested_order_qty ?? 1,
      unit_cost: s.default_unit_cost ?? 0,
    })),
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setForm({
        ...emptyOrderForm(),
        order_date: today,
        lines: (suggestions || []).map((s) => ({
          item_id: s.id,
          item_name: s.name || s.item_name,
          qty_ordered: s.suggested_qty ?? s.suggested_order_qty ?? 1,
          unit_cost: s.default_unit_cost ?? 0,
        })),
      });
      setError("");
    }
  }, [open, suggestions, today]);

  const subtotal = useMemo(
    () => form.lines.reduce((sum, ln) => sum + Number(ln.qty_ordered || 0) * Number(ln.unit_cost || 0), 0),
    [form.lines]
  );

  const grandTotal =
    subtotal +
    parseMoneyInput(form.tax) +
    parseMoneyInput(form.shipping_charge) +
    parseMoneyInput(form.additional_charge) -
    parseMoneyInput(form.discount);

  const onSubmit = async () => {
    if (!form.lines.length) {
      setError("Add at least one item.");
      return;
    }
    try {
      setSaving(true);
      await createInventoryOrder({
        vendor_id: form.vendor_id || null,
        vendor_name: form.vendor_name || null,
        order_date: form.order_date,
        expected_date: form.expected_date || null,
        status: form.status,
        tax: parseMoneyInput(form.tax),
        shipping_charge: parseMoneyInput(form.shipping_charge),
        additional_charge: parseMoneyInput(form.additional_charge),
        discount: parseMoneyInput(form.discount),
        notes: form.notes,
        lines: form.lines.map((ln) => ({
          item_id: ln.item_id,
          qty_ordered: Number(ln.qty_ordered),
          unit_cost: Number(ln.unit_cost),
        })),
      });
      onSaved?.();
      onClose();
    } catch (e) {
      setError(e?.response?.data?.error || "Order failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Create Order</DialogTitle>
      <DialogContent>
        {error ? <StatusAlert message={{ type: "error", text: error }} /> : null}
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Grid item xs={12} sm={6}>
            <TextField
              select
              label="Vendor"
              fullWidth
              value={form.vendor_id}
              onChange={(e) => {
                const v = vendors.find((x) => String(x.id) === e.target.value);
                setForm((p) => ({ ...p, vendor_id: e.target.value, vendor_name: v?.name || "" }));
              }}
              sx={INV_INPUT_SX}
            >
              <MenuItem value="">Select vendor</MenuItem>
              {vendors.map((v) => (
                <MenuItem key={v.id} value={String(v.id)}>{v.name}</MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              label="Order date"
              type="date"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={form.order_date}
              onChange={(e) => setForm((p) => ({ ...p, order_date: e.target.value }))}
              sx={INV_INPUT_SX}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField
              label="Expected delivery"
              type="date"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={form.expected_date}
              onChange={(e) => setForm((p) => ({ ...p, expected_date: e.target.value }))}
              sx={INV_INPUT_SX}
            />
          </Grid>
          <Grid item xs={12} sm={4}>
            <TextField
              select
              label="Status"
              fullWidth
              value={form.status}
              onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}
              sx={INV_INPUT_SX}
            >
              <MenuItem value="DRAFT">Draft</MenuItem>
              <MenuItem value="ORDERED">Ordered</MenuItem>
            </TextField>
          </Grid>
        </Grid>

        <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
          Items
        </Typography>
        {form.lines.map((ln, idx) => (
          <Stack key={ln.item_id} direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }}>
            <TextField label="Item" value={ln.item_name} disabled fullWidth size="small" />
            <TextField
              label="Qty"
              type="number"
              size="small"
              value={ln.qty_ordered}
              onChange={(e) => {
                const next = [...form.lines];
                next[idx] = { ...ln, qty_ordered: e.target.value };
                setForm((p) => ({ ...p, lines: next }));
              }}
              sx={{ maxWidth: 100 }}
            />
            <TextField
              label="Unit cost"
              type="number"
              size="small"
              value={ln.unit_cost}
              onChange={(e) => {
                const next = [...form.lines];
                next[idx] = { ...ln, unit_cost: e.target.value };
                setForm((p) => ({ ...p, lines: next }));
              }}
              sx={{ maxWidth: 120 }}
            />
          </Stack>
        ))}

        <Grid container spacing={2} sx={{ mt: 1 }}>
          <Grid item xs={6} sm={3}><CurrencyField label="Tax" value={form.tax} onChange={(e) => setForm((p) => ({ ...p, tax: e.target.value }))} /></Grid>
          <Grid item xs={6} sm={3}><CurrencyField label="Shipping" value={form.shipping_charge} onChange={(e) => setForm((p) => ({ ...p, shipping_charge: e.target.value }))} /></Grid>
          <Grid item xs={6} sm={3}><CurrencyField label="Other" value={form.additional_charge} onChange={(e) => setForm((p) => ({ ...p, additional_charge: e.target.value }))} /></Grid>
          <Grid item xs={6} sm={3}><CurrencyField label="Discount" value={form.discount} onChange={(e) => setForm((p) => ({ ...p, discount: e.target.value }))} /></Grid>
        </Grid>
        <Typography variant="body2" sx={{ mt: 2 }}>
          Subtotal {formatCurrency(subtotal)} · Grand total <strong>{formatCurrency(grandTotal)}</strong>
        </Typography>
        <TextField
          label="Notes"
          fullWidth
          multiline
          minRows={2}
          value={form.notes}
          onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))}
          sx={{ mt: 2, ...INV_INPUT_SX }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={onSubmit} disabled={saving}>
          Create Order
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function ReceiveOrderDialog({ order, open, onClose, onSaved, onMessage }) {
  const [lines, setLines] = useState([]);
  const [receivedDate, setReceivedDate] = useState(new Date().toISOString().slice(0, 10));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (order?.lines) {
      setLines(
        order.lines.map((ln) => ({
          line_id: ln.id,
          item_name: ln.item_name,
          qty_ordered: ln.qty_ordered,
          qty_received: ln.qty_ordered,
          current_on_hand: Number(ln.current_on_hand ?? 0),
          notes: "",
        }))
      );
    }
  }, [order]);

  const onSubmit = async () => {
    try {
      setSaving(true);
      await receiveInventoryOrder(order.id, {
        received_date: receivedDate,
        lines: lines.map((ln) => ({
          line_id: ln.line_id,
          qty_received: Number(ln.qty_received),
          notes: ln.notes || null,
        })),
      });
      onMessage?.({ type: "success", text: "Order received." });
      onSaved?.();
      onClose();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Receive failed." });
    } finally {
      setSaving(false);
    }
  };

  if (!order) return null;

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Receive Order #{order.id}</DialogTitle>
      <DialogContent>
        <TextField
          label="Received date"
          type="date"
          fullWidth
          InputLabelProps={{ shrink: true }}
          value={receivedDate}
          onChange={(e) => setReceivedDate(e.target.value)}
          sx={{ mb: 2, ...INV_INPUT_SX }}
        />
        {lines.map((ln, idx) => {
          const received = Number(ln.qty_received || 0);
          const current = Number(ln.current_on_hand || 0);
          const next = current + received;
          return (
            <Stack key={ln.line_id} spacing={1.25} sx={{ mb: 2, p: 1.75, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
              <Typography fontWeight={700}>{ln.item_name}</Typography>
              <Typography variant="body2" color="text.secondary">Ordered: {ln.qty_ordered}</Typography>
              <Grid container spacing={1}>
                <Grid item xs={4}>
                  <Typography variant="caption" color="text.secondary">Current</Typography>
                  <Typography fontWeight={700}>{current}</Typography>
                </Grid>
                <Grid item xs={4}>
                  <Typography variant="caption" color="text.secondary">Received</Typography>
                  <Typography fontWeight={700} color="success.main">+{received}</Typography>
                </Grid>
                <Grid item xs={4}>
                  <Typography variant="caption" color="text.secondary">New</Typography>
                  <Typography fontWeight={800}>{next}</Typography>
                </Grid>
              </Grid>
              <QtyStepper
                label="Qty received"
                value={String(ln.qty_received ?? "")}
                onChange={(v) => {
                  const nextLines = [...lines];
                  nextLines[idx] = { ...ln, qty_received: v };
                  setLines(nextLines);
                }}
              />
              <Button
                size="small"
                variant="outlined"
                onClick={() => {
                  const nextLines = [...lines];
                  nextLines[idx] = { ...ln, qty_received: String(ln.qty_ordered) };
                  setLines(nextLines);
                }}
              >
                Receive full order qty ({ln.qty_ordered})
              </Button>
              <TextField
                label="Note (optional)"
                value={ln.notes}
                onChange={(e) => {
                  const nextLines = [...lines];
                  nextLines[idx] = { ...ln, notes: e.target.value };
                  setLines(nextLines);
                }}
                sx={INV_INPUT_SX}
              />
            </Stack>
          );
        })}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={onSubmit} disabled={saving}>
          Mark Received
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function HistoryReportsPanel() {
  const [report, setReport] = useState(null);
  const [weekly, setWeekly] = useState(null);
  const [activity, setActivity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ start_date: "", end_date: "", item_id: "" });

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [weeklyRes, activityRes] = await Promise.all([
        getInventoryWeeklyOrderReport(),
        getInventoryReport(filters),
      ]);
      setWeekly(weeklyRes?.data);
      setActivity(activityRes?.data);
      setReport(activityRes?.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <LoadingBlock message="Loading reports…" />;

  return (
    <Stack spacing={2}>
      {weekly ? (
        <SectionCard
          title={`Last Week: ${formatDate(weekly.start_date)} – ${formatDate(weekly.end_date)}`}
          subtitle={`Total ordered: ${formatCurrency(weekly.total_ordered)} · ${weekly.order_count} orders`}
        >
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>Vendors</Typography>
          {(weekly.vendors || []).map((v) => (
            <Stack key={v.vendor_name} direction="row" justifyContent="space-between" sx={{ py: 0.5 }}>
              <Typography variant="body2">{v.vendor_name}</Typography>
              <Typography variant="body2" fontWeight={600}>{formatCurrency(v.total)}</Typography>
            </Stack>
          ))}
          <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>Items</Typography>
          {(weekly.items || []).map((it) => (
            <Stack key={it.item_name} direction="row" justifyContent="space-between" sx={{ py: 0.5 }}>
              <Typography variant="body2">{it.item_name}: {it.qty}</Typography>
              <Typography variant="body2" fontWeight={600}>{formatCurrency(it.total)}</Typography>
            </Stack>
          ))}
        </SectionCard>
      ) : null}

      <SectionCard title="Activity Log">
        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: "wrap" }}>
          <TextField
            label="From"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={filters.start_date}
            onChange={(e) => setFilters((p) => ({ ...p, start_date: e.target.value }))}
          />
          <TextField
            label="To"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={filters.end_date}
            onChange={(e) => setFilters((p) => ({ ...p, end_date: e.target.value }))}
          />
          <Button variant="outlined" onClick={load}>Apply</Button>
        </Stack>
        {(activity?.activity || []).slice(0, 50).map((a) => (
          <Stack
            key={`${a.activity_type}-${a.id}`}
            direction="row"
            justifyContent="space-between"
            sx={{ py: 1, borderBottom: "1px solid", borderColor: "divider" }}
          >
            <Typography variant="body2">
              {formatDateTime(a.activity_at)} · {a.activity_type} · {a.item_name}
            </Typography>
            <Typography variant="body2">Qty {a.qty} · {a.actor || "—"}</Typography>
          </Stack>
        ))}
        {(!activity?.activity || activity.activity.length === 0) ? (
          <Typography variant="body2" color="text.secondary">No activity found.</Typography>
        ) : null}
        {report?.bag_totals ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            Bags sold {report.bag_totals.total_bags_sold} · Sales {formatCurrency(report.bag_totals.bags_sales_amount)}
          </Typography>
        ) : null}
      </SectionCard>
    </Stack>
  );
}

export default function PurchaseOrdersTab({ suggestions, vendors, categories, items, onRefresh, onMessage }) {
  const [subTab, setSubTab] = useState(0);
  const [summary, setSummary] = useState(null);
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState({});
  const [qty, setQty] = useState({});
  const [createOpen, setCreateOpen] = useState(false);
  const [receiveOrder, setReceiveOrder] = useState(null);

  const grouped = useMemo(
    () => groupItemsByCategory(suggestions || [], categories),
    [suggestions, categories]
  );

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [summaryRes, ordersRes] = await Promise.all([
        getInventoryOrdersSummary(),
        getInventoryOrders(),
      ]);
      setSummary(summaryRes?.data);
      setOrders(ordersRes?.data || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedSuggestions = useMemo(() => {
    return (suggestions || [])
      .filter((s) => selected[s.id])
      .map((s) => ({
        ...s,
        qty_ordered: qty[s.id] || s.suggested_qty || s.suggested_order_qty || 1,
      }));
  }, [suggestions, selected, qty]);

  const onCreateFromSelected = () => {
    if (selectedSuggestions.length === 0) {
      onMessage?.({ type: "error", text: "Select items to order." });
      return;
    }
    setCreateOpen(true);
  };

  if (loading && !summary) return <LoadingBlock />;

  return (
    <Box>
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        <Grid item xs={6} sm={4} md={2.4}>
          <SummaryStatCard label="Need reorder" value={summary?.items_needing_reorder ?? 0} color="warning.main" />
        </Grid>
        <Grid item xs={6} sm={4} md={2.4}>
          <SummaryStatCard label="Last week $" value={formatCurrency(summary?.last_week_ordered_total)} />
        </Grid>
        <Grid item xs={6} sm={4} md={2.4}>
          <SummaryStatCard label="This week $" value={formatCurrency(summary?.this_week_ordered_total)} />
        </Grid>
        <Grid item xs={6} sm={4} md={2.4}>
          <SummaryStatCard label="Pending" value={summary?.pending_orders ?? 0} />
        </Grid>
        <Grid item xs={6} sm={4} md={2.4}>
          <SummaryStatCard label="Received (wk)" value={summary?.received_this_week ?? 0} color="success.main" />
        </Grid>
      </Grid>

      <Tabs value={subTab} onChange={(_, v) => setSubTab(v)} variant="scrollable" sx={{ mb: 2 }}>
        <Tab label="Suggested Reorder" />
        <Tab label="Purchase Orders" />
        <Tab label="Adjustments" />
      </Tabs>

      {subTab === 0 ? (
        <SectionCard
          title="Suggested Reorder"
          subtitle="Items at or below reorder level"
          action={
            <Stack direction="row" spacing={1}>
              <Button variant="outlined" size="small" onClick={() => setCreateOpen(true)}>
                New Order
              </Button>
              <Button variant="contained" size="small" onClick={onCreateFromSelected}>
                Order Selected
              </Button>
            </Stack>
          }
        >
          {grouped.length === 0 ? (
            <Typography variant="body2" color="text.secondary">All items above reorder level.</Typography>
          ) : (
            grouped.map((cat, idx) => (
              <CategoryAccordion key={cat.id} category={cat} defaultExpanded={idx === 0}>
                {cat.items.map((item) => (
                  <ReorderItemRow
                    key={item.id}
                    item={item}
                    selected={Boolean(selected[item.id])}
                    qty={qty[item.id] ?? item.suggested_qty ?? ""}
                    onSelect={(v) => setSelected((p) => ({ ...p, [item.id]: v }))}
                    onQtyChange={(v) => setQty((p) => ({ ...p, [item.id]: v }))}
                  />
                ))}
              </CategoryAccordion>
            ))
          )}
        </SectionCard>
      ) : null}

      {subTab === 1 ? (
        <SectionCard title="Purchase Orders" subtitle="Create, receive, and duplicate orders">
          <Button variant="contained" sx={{ mb: 2 }} onClick={() => setCreateOpen(true)}>Create Purchase Order</Button>
          {(orders || []).map((o) => (
            <Box key={o.id} sx={{ p: 2, mb: 1.5, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1}>
                <Box>
                  <Typography fontWeight={700}>#{o.id} · {o.vendor_display_name || o.vendor_name || "No vendor"}</Typography>
                  <Typography variant="body2" color="text.secondary">{formatDate(o.order_date)} · {formatCurrency(o.grand_total)}</Typography>
                  <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
                    <OrderStatusBadge status={o.status} />
                    {o.qty_outstanding_total > 0 ? (
                      <Chip size="small" label={`Outstanding ${o.qty_outstanding_total}`} variant="outlined" />
                    ) : null}
                  </Stack>
                </Box>
                <Stack direction="row" spacing={1}>
                  <Button size="small" variant="outlined" onClick={async () => {
                    try {
                      await duplicateInventoryOrder(o.id);
                      onMessage?.({ type: "success", text: "Order duplicated as draft." });
                      await load();
                    } catch (e) {
                      onMessage?.({ type: "error", text: e?.response?.data?.error || "Duplicate failed." });
                    }
                  }}>Duplicate</Button>
                  {o.status === "ORDERED" || o.status === "PARTIALLY_RECEIVED" ? (
                    <Button size="small" variant="contained" onClick={() => setReceiveOrder(o)}>Receive</Button>
                  ) : null}
                </Stack>
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
                Subtotal {formatCurrency(o.subtotal)} · Tax {formatCurrency(o.tax)} · Shipping {formatCurrency(o.shipping_charge)} · Grand {formatCurrency(o.grand_total)}
                · Received {o.qty_received_total ?? 0} / {o.qty_ordered_total ?? 0}
              </Typography>
              {(o.lines || []).map((ln) => (
                <Typography key={ln.id} variant="body2" sx={{ mt: 0.5 }}>
                  {ln.item_name}: ordered {ln.qty_ordered}, received {ln.qty_received} @ {formatCurrency(ln.unit_cost)}
                </Typography>
              ))}
            </Box>
          ))}
        </SectionCard>
      ) : null}

      {subTab === 2 ? <AdjustmentsPanel items={items} onRefresh={onRefresh} onMessage={onMessage} /> : null}

      <CreateOrderDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        vendors={vendors}
        suggestions={selectedSuggestions.length ? selectedSuggestions : suggestions}
        onSaved={async () => {
          onMessage?.({ type: "success", text: "Order created." });
          await load();
          onRefresh?.();
        }}
      />

      <ReceiveOrderDialog
        order={receiveOrder}
        open={Boolean(receiveOrder)}
        onClose={() => setReceiveOrder(null)}
        onMessage={onMessage}
        onSaved={async () => {
          await load();
          onRefresh?.();
        }}
      />
    </Box>
  );
}
