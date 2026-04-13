"""
Match Rinse tag QR / name / service hints to orders_staging rows still at Washpro.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


def normalize_scan_name(value: Any) -> str:
    s = str(value or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return " ".join(s.split())


def name_hint_matches_row(nn: str, name_clean: Any) -> bool:
    """Loose match for tag typing: substring, full string, or every 2+ char token appears in the name."""
    if not nn:
        return True
    rn = normalize_scan_name(name_clean)
    if not rn:
        return False
    if rn == nn:
        return True
    if len(nn) >= 2 and (nn in rn or rn in nn):
        return True
    parts = [p for p in nn.split() if len(p) >= 2]
    if parts and all(p in rn for p in parts):
        return True
    return False


def name_match_score(nn: str, name_clean: Any) -> int:
    if not nn:
        return 0
    rn = normalize_scan_name(name_clean)
    if not rn:
        return 0
    if rn == nn:
        return 120
    if len(nn) >= 2 and (nn in rn or rn in nn):
        return 70
    parts = [p for p in nn.split() if len(p) >= 2]
    if parts and all(p in rn for p in parts):
        return 60
    return 0


def map_service_hint(hint: Any) -> str | None:
    h = str(hint or "").strip().lower()
    if not h:
        return None
    if h in ("hd", "h+d", "h d"):
        return "HD"
    if h in ("wf", "w&f"):
        return "WF"
    if "hang" in h and "dry" in h:
        return "HD"
    if "hang" in h:
        return "HD"
    if "fold" in h or ("wash" in h and "fold" in h):
        return "WF"
    if "wash" in h:
        return "WF"
    return None


def map_service_hint_qr(qr_text: str) -> str | None:
    """Infer WF/HD from URL path/query or short QR blobs (avoid whole-host false positives)."""
    raw = str(qr_text or "").strip()
    if not raw:
        return None
    chunk = raw[:400]
    if "://" in raw:
        try:
            u = urlparse(raw)
            chunk = f"{unquote(u.path or '')} {unquote(u.query or '')}"[:400]
        except Exception:
            chunk = raw[:400]
    return map_service_hint(chunk.replace("+", " "))


def qr_text_name_overlap_score(qr_text: str, name_clean: Any) -> int:
    """When QR is a URL or blob that contains the customer name, score the row without ticket_id match."""
    raw = str(qr_text or "").strip()
    if not raw or len(raw) < 4:
        return 0
    rn = normalize_scan_name(name_clean)
    if not rn:
        return 0
    qn = normalize_scan_name(raw)
    if not qn:
        return 0
    q_words = {w for w in qn.split() if len(w) >= 3}
    n_words = {w for w in rn.split() if len(w) >= 3}
    overlap = q_words & n_words
    if overlap:
        best = max(len(w) for w in overlap)
        return 45 + min(35, best * 2)
    for w in q_words:
        if len(w) >= 4 and w in rn:
            return 42
    for w in n_words:
        if len(w) >= 4 and w in qn:
            return 42
    return 0


def qr_embedded_name_score(qr_text: str, name_clean: Any) -> int:
    """Score when a name token appears inside an opaque URL/path (no word boundaries after normalize)."""
    raw = str(qr_text or "").strip()
    if not raw:
        return 0
    rn = normalize_scan_name(name_clean)
    if not rn:
        return 0
    try:
        dec = unquote(raw)
    except Exception:
        dec = raw
    camel = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", dec)
    blob = " ".join([raw.lower(), dec.lower(), camel.lower()])
    blob = blob.replace("%20", " ").replace("+", " ")
    best = 0
    for w in rn.split():
        if len(w) < 4:
            continue
        if w in blob:
            best = max(best, 40 + min(25, len(w)))
    return best


def _qr_tokens(qr_text: str) -> list[str]:
    raw = str(qr_text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen = set()

    def add(t: str):
        t = str(t or "").strip()
        if not t:
            return
        u = t.upper()
        if u not in seen:
            seen.add(u)
            out.append(t)

    add(raw)
    if "://" in raw or raw.startswith("http"):
        try:
            u = urlparse(raw)
            for seg in u.path.split("/"):
                add(unquote(seg))
            qs = parse_qs(u.query)
            for vals in qs.values():
                for v in vals:
                    add(v)
        except Exception:
            pass
    for part in re.split(r"[\s,;|]+", raw):
        add(part)
    alnum = re.sub(r"[^A-Z0-9]+", "", raw.upper())
    if len(alnum) >= 4:
        add(alnum)
    return out


def run_order_lookup_scan(
    cursor,
    tenant_oid: int,
    active_where_sql: str,
    cap: dict[str, bool],
    body: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return matching staging orders (max 25), newest id last in list for stable UI."""
    from backend.app import orders_logistics_select_sql, orders_processing_select_sql  # noqa: PLC0415

    logistics_sql = orders_logistics_select_sql(cap)
    processing_sql = orders_processing_select_sql(cap)
    has_tid = cap.get("has_ticket_id")
    tid_sel = "o.ticket_id" if has_tid else "NULL AS ticket_id"

    batch_raw = str(body.get("batch_date") or "").strip()[:10]
    batch_date = batch_raw if re.fullmatch(r"\d{4}-\d{2}-\d{2}", batch_raw) else ""
    batch_clause = " AND o.batch_date = %s " if batch_date else ""
    exec_params: list[Any] = [tenant_oid]
    if batch_date:
        exec_params.append(batch_date)

    sql = f"""
        SELECT
            o.id,
            o.date_clean,
            o.batch_date,
            o.name_clean,
            o.weight_num,
            o.service_type,
            {logistics_sql},
            {processing_sql},
            {tid_sel}
        FROM orders_staging o
        WHERE ({active_where_sql})
          AND o.organization_id = %s
          {batch_clause}
        ORDER BY o.id ASC
    """
    cursor.execute(sql, tuple(exec_params))
    candidates = cursor.fetchall() or []
    if not candidates and batch_date:
        sql_wide = f"""
            SELECT
                o.id,
                o.date_clean,
                o.batch_date,
                o.name_clean,
                o.weight_num,
                o.service_type,
                {logistics_sql},
                {processing_sql},
                {tid_sel}
            FROM orders_staging o
            WHERE ({active_where_sql})
              AND o.organization_id = %s
            ORDER BY o.id ASC
        """
        cursor.execute(sql_wide, (tenant_oid,))
        candidates = cursor.fetchall() or []

    qr_text = str(body.get("qr_text") or "").strip()
    name_hint = str(body.get("name_hint") or "").strip()
    service_hint = str(body.get("service_hint") or "").strip()
    tokens = _qr_tokens(qr_text)
    nn = normalize_scan_name(name_hint) if name_hint else ""
    mapped = map_service_hint(service_hint) or map_service_hint_qr(qr_text)

    def row_ok_name(row: dict) -> bool:
        return name_hint_matches_row(nn, row.get("name_clean"))

    def row_ok_service(row: dict) -> bool:
        if not mapped:
            return True
        return str(row.get("service_type") or "").strip().upper() == mapped

    def row_qr_hit(row: dict) -> bool:
        if not tokens:
            return False
        oid = int(row.get("id") or 0)
        tid = str(row.get("ticket_id") or "").strip().upper()
        for t in tokens:
            tu = t.strip().upper()
            if not tu:
                continue
            if tu.isdigit() and int(tu) == oid:
                return True
            if tid and (tid == tu or tu in tid or tid in tu):
                return True
        return False

    scored: list[tuple[int, dict]] = []

    for row in candidates:
        score = 0
        if row_qr_hit(row):
            score += 200
        score += qr_text_name_overlap_score(qr_text, row.get("name_clean"))
        score += qr_embedded_name_score(qr_text, row.get("name_clean"))
        if nn:
            score += name_match_score(nn, row.get("name_clean"))
        if mapped and str(row.get("service_type") or "").strip().upper() == mapped:
            score += 80

        if nn or mapped:
            if not row_ok_name(row) or not row_ok_service(row):
                continue

        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda x: (-x[0], -int(x[1].get("id") or 0)))
    out = [r for _, r in scored[:25]]

    if not out and (nn or mapped):
        for row in candidates:
            if row_ok_name(row) and row_ok_service(row):
                out.append(row)
        out = out[:25]

    if not out and tokens:
        for row in candidates:
            if row_qr_hit(row):
                out.append(row)
        out = out[:25]

    return out
