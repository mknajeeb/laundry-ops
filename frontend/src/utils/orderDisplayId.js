/**
 * Shared order display identifier: BAGID-OI-MMDDYYYY (EDD).
 * Display / search only. Action payloads must use order_instance_id.
 *
 * Fallback when EDD unavailable (do not invent a date):
 *   {BAG_ID}-OI-{order_instance_id}
 */

const DISPLAY_ID_RE = /^([A-Za-z0-9]+)-OI-(\d{8})$/i;
const FALLBACK_ID_RE = /^([A-Za-z0-9]+)-OI-(\d{1,18})$/i;

function parseEdd(raw) {
  if (raw == null || raw === "") return null;
  if (raw instanceof Date && !Number.isNaN(raw.getTime())) {
    return new Date(raw.getFullYear(), raw.getMonth(), raw.getDate());
  }
  const s = String(raw).trim();
  if (!s) return null;
  if (/^\d{8}$/.test(s)) {
    const mm = Number(s.slice(0, 2));
    const dd = Number(s.slice(2, 4));
    const yyyy = Number(s.slice(4, 8));
    const d = new Date(yyyy, mm - 1, dd);
    if (d.getFullYear() === yyyy && d.getMonth() === mm - 1 && d.getDate() === dd) {
      return d;
    }
    return null;
  }
  const iso = s.slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    if (dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d) return dt;
  }
  return null;
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

export function formatOrderDisplayId(bagId, orderInstanceId, edd = null) {
  const bag = String(bagId || "")
    .trim()
    .toUpperCase();
  const oi = Number(orderInstanceId);
  if (!bag || !Number.isFinite(oi) || oi <= 0) return null;
  const eddDate = parseEdd(edd);
  if (eddDate) {
    return `${bag}-OI-${pad2(eddDate.getMonth() + 1)}${pad2(eddDate.getDate())}${eddDate.getFullYear()}`;
  }
  return `${bag}-OI-${oi}`;
}

export function parseOrderDisplayId(raw) {
  const s = String(raw || "").trim();
  if (!s || !/-OI-/i.test(s)) return null;
  const m = DISPLAY_ID_RE.exec(s);
  if (m) {
    const edd = parseEdd(m[2]);
    return {
      bagId: m[1].toUpperCase(),
      eddMmddyyyy: m[2],
      estimatedDeliveryDate: edd,
      orderInstanceId: null,
      form: "edd",
    };
  }
  const m2 = FALLBACK_ID_RE.exec(s);
  if (!m2) return null;
  const bag = m2[1].toUpperCase();
  const token = m2[2];
  if (token.length === 8) {
    const edd = parseEdd(token);
    if (edd) {
      return {
        bagId: bag,
        eddMmddyyyy: token,
        estimatedDeliveryDate: edd,
        orderInstanceId: null,
        form: "edd",
      };
    }
  }
  const oi = Number(token);
  if (!Number.isFinite(oi) || oi <= 0) return null;
  return {
    bagId: bag,
    eddMmddyyyy: null,
    estimatedDeliveryDate: null,
    orderInstanceId: oi,
    form: "oi_fallback",
  };
}

/** Prefer server-provided order_display_id; else format from row fields. */
export function orderDisplayIdFromRow(row) {
  if (!row || typeof row !== "object") return null;
  if (row.order_display_id) return String(row.order_display_id);
  return formatOrderDisplayId(
    row.bag_id,
    row.order_instance_id,
    row.estimated_delivery_date || row.edd || row.date_clean || null,
  );
}
