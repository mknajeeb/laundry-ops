export function formatCurrency(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 10);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function parseQtyInput(val) {
  if (val === "" || val === null || val === undefined) return "";
  const n = parseFloat(String(val).replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : "";
}

export function parseMoneyInput(val) {
  if (val === "" || val === null || val === undefined) return 0;
  const n = Number(String(val).replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

export const INV_NAV_SX = {
  position: "sticky",
  top: 0,
  zIndex: 10,
  bgcolor: "background.paper",
  borderBottom: "1px solid",
  borderColor: "divider",
  mb: 2,
};

export const INV_INPUT_SX = {
  "& .MuiInputBase-input": {
    fontSize: { xs: "1.1rem", sm: "1rem" },
    py: { xs: 1.5, sm: 1 },
  },
};

export const INV_STICKY_ACTION_SX = {
  position: "fixed",
  bottom: 0,
  left: 0,
  right: 0,
  zIndex: 1100,
  p: 2,
  pb: "calc(16px + env(safe-area-inset-bottom))",
  bgcolor: "background.paper",
  borderTop: "1px solid",
  borderColor: "divider",
  boxShadow: "0 -4px 12px rgba(0,0,0,0.08)",
};

export const INV_SECTION_CARD_SX = {
  borderRadius: 2,
  p: { xs: 2, sm: 2.5 },
  mb: 2,
  border: "1px solid",
  borderColor: "divider",
};

export function groupItemsByCategory(items, categories) {
  const catMap = {};
  (categories || []).forEach((c) => {
    catMap[c.id] = c;
  });
  const groups = {};
  (items || []).forEach((item) => {
    const cid = item.category_id || "uncategorized";
    const catName = item.category_name || catMap[cid]?.name || "Other";
    const sort = catMap[cid]?.sort_order ?? 999;
    if (!groups[cid]) {
      groups[cid] = { id: cid, name: catName, sort_order: sort, items: [] };
    }
    groups[cid].items.push(item);
  });
  return Object.values(groups).sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
}

export function emptyItemForm() {
  return {
    name: "",
    category_id: "",
    unit: "unit",
    default_vendor_id: "",
    reorder_level: "",
    suggested_order_qty: "",
    default_unit_cost: "",
    current_on_hand: "",
    target_stock: "",
    pack_size: 1,
    sku: "",
    tracking_mode: "QUANTITY",
    status_level: "OK",
    track_weekly_check: true,
    track_retail_sale: false,
    is_active: true,
    notes: "",
  };
}

export function emptyOrderForm() {
  return {
    vendor_id: "",
    vendor_name: "",
    order_date: new Date().toISOString().slice(0, 10),
    expected_date: "",
    status: "ORDERED",
    tax: "",
    shipping_charge: "",
    additional_charge: "",
    discount: "",
    notes: "",
    lines: [],
  };
}
