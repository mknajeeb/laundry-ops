/** Group HD orders by delivery date for compact operational lists. */

function todayEtIso() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function parseIsoDate(iso) {
  const parts = String(iso || "").split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
  return new Date(parts[0], parts[1] - 1, parts[2]);
}

export function friendlyDeliveryGroupLabel(iso, today = todayEtIso()) {
  if (!iso) return "NO DELIVERY DATE";
  const d = parseIsoDate(iso);
  if (!d) return "NO DELIVERY DATE";
  const dayName = d
    .toLocaleDateString("en-US", { weekday: "short", timeZone: "America/New_York" })
    .toUpperCase();
  const monthDay = d
    .toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" })
    .toUpperCase();
  if (iso === today) return `TODAY · ${dayName} ${monthDay}`;
  return `${dayName} ${monthDay}`;
}

export function groupOrdersByDeliveryDate(orders = [], today = todayEtIso()) {
  const buckets = new Map();
  const noDate = [];
  for (const order of orders || []) {
    const key = order?.delivery_date_et || null;
    if (!key) {
      noDate.push(order);
      continue;
    }
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(order);
  }
  const dated = [...buckets.entries()].sort(([a], [b]) => String(a).localeCompare(String(b)));
  const groups = dated.map(([deliveryDateEt, items]) => ({
    delivery_date_et: deliveryDateEt,
    label: friendlyDeliveryGroupLabel(deliveryDateEt, today),
    count: items.length,
    orders: items.sort((a, b) =>
      String(a.customer_name || a.bag_id || "").localeCompare(
        String(b.customer_name || b.bag_id || ""),
      ),
    ),
  }));
  if (noDate.length) {
    groups.push({
      delivery_date_et: null,
      label: "NO DELIVERY DATE",
      count: noDate.length,
      orders: noDate.sort((a, b) =>
        String(a.customer_name || a.bag_id || "").localeCompare(
          String(b.customer_name || b.bag_id || ""),
        ),
      ),
    });
  }
  return groups;
}
