/**
 * Shared Playwright helpers for rinse-cleanertickets scripts.
 * Used by scrape-scan-events.mjs only — production scrape.mjs is unchanged.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const __rinseDir = path.dirname(fileURLToPath(import.meta.url));

export function loadLocalEnvFile() {
  try {
    const p = path.join(__rinseDir, ".env");
    if (!fs.existsSync(p)) return;
    const text = fs.readFileSync(p, "utf8");
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq <= 0) continue;
      const key = trimmed.slice(0, eq).trim();
      let val = trimmed.slice(eq + 1).trim();
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1);
      }
      if (process.env[key] === undefined) {
        process.env[key] = val;
      }
    }
  } catch {
    /* ignore */
  }
}

export function progressLine(msg) {
  const s = typeof msg === "string" ? msg : String(msg);
  const out = s.endsWith("\n") ? s : `${s}\n`;
  try {
    fs.writeSync(1, out);
  } catch {
    console.log(typeof msg === "string" ? msg : String(msg));
  }
}

export function csvEscape(s) {
  const t = String(s ?? "").replace(/"/g, '""');
  return `"${t}"`;
}

export const PORTAL_TICKET_DATE_LINE_RE =
  /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+\d{1,2}\/\d{1,2}(?:\/\d{2,4})?\b/i;

const RINSE_LOGIN_URL = "https://www.rinse.com/accounts/login/";

export function navTimeoutMs() {
  const n = parseInt(process.env.RINSE_NAV_TIMEOUT_MS || "120000", 10);
  return Math.max(15000, Math.min(300000, Number.isFinite(n) ? n : 120000));
}

export function urlForPage(baseUrl, pageNum) {
  const u = String(baseUrl || "").trim();
  if (!u) return `https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=${pageNum}`;
  try {
    const parsed = new URL(u);
    parsed.searchParams.set("page", String(pageNum));
    return parsed.toString();
  } catch {
    if (/[?&]page=\d+/.test(u)) {
      return u.replace(/([?&])page=\d+/, `$1page=${pageNum}`);
    }
    return `${u}${u.includes("?") ? "&" : "?"}page=${pageNum}`;
  }
}

export function pageNumFromUrl(href) {
  try {
    const p = new URL(href).searchParams.get("page");
    if (p == null || p === "") return null;
    const n = parseInt(p, 10);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

export function defaultScanEventsOutputPath() {
  const d = new Date();
  const stamp = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return path.join(__rinseDir, `scan-events-${stamp}.csv`);
}

export function bodyRowsSelector() {
  const base = [
    "main table > tbody > tr",
    "table.sortable > tbody > tr",
    "#content table > tbody > tr",
    "table > tbody > tr",
    "[role='grid'] > [role='rowgroup'] > [role='row']",
  ].join(", ");
  const extra = (process.env.RINSE_EXTRA_ROW_SELECTORS || "").trim();
  return extra ? `${base}, ${extra}` : base;
}

export function ticketTableBodyRows(page) {
  const env = (process.env.RINSE_TICKET_TABLE_SELECTOR || "").trim();
  if (env) {
    return page.locator(env).locator("> tbody > tr");
  }
  const tables = page.getByRole("table").filter({ hasText: /Customer/i });
  const ticketLike = tables.filter({
    hasText: /Estd|Estimated|#\s*WF|WF\s*LBS|#\s*HD/i,
  });
  return ticketLike.first().locator("> tbody > tr");
}

export function isLikelyExpandedDetailSubRow(trimmed) {
  const t0 = String(trimmed || "").trim();
  const headHasListDate = PORTAL_TICKET_DATE_LINE_RE.test(t0.slice(0, 400));
  if (/^scans\b/i.test(t0.slice(0, 80)) && !headHasListDate) return true;
  if (
    /\bmove-bag\b|\bweight-entry\b|\bstart-cleaning\b|\bqc-?hold\b/i.test(t0.slice(0, 2500)) &&
    !headHasListDate
  ) {
    return true;
  }
  const head = trimmed.slice(0, 420);
  const hasPortalDetailLinks =
    /show\s+bag\s+details|hide\s+bag\s+details|show\s+issue\s+details|show\s+qc\s+details/i.test(
      head,
    );
  const hasListRowDateLine = PORTAL_TICKET_DATE_LINE_RE.test(trimmed.slice(0, 240));
  return hasPortalDetailLinks && !hasListRowDateLine;
}

export function isMainListTicketRow(trimmed) {
  return PORTAL_TICKET_DATE_LINE_RE.test(String(trimmed || "").slice(0, 900));
}

export function portalListRowPeekOk(tdTexts, trimmed) {
  if (isMainListTicketRow(trimmed)) return true;
  const cells = Array.isArray(tdTexts) ? tdTexts : [];
  const joined = cells.join(" ");
  return PORTAL_TICKET_DATE_LINE_RE.test(joined.slice(0, 400));
}

export async function readTicketRowTextSnapshot(rowLocator) {
  return (await rowLocator.innerText().catch(() => "")) || "";
}

export async function readTicketRowDirectCells(rowLocator) {
  const n = await rowLocator.locator(":scope > td").count().catch(() => 0);
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push(
      ((await rowLocator.locator(":scope > td").nth(i).innerText().catch(() => "")) || "").trim(),
    );
  }
  return out;
}

export async function isProbablySingleCellDetailRow(rowLocator) {
  const td = await rowLocator.locator(":scope > td").count().catch(() => 0);
  return td <= 1;
}

const BAG_PATTERNS = [
  /Bag:\s*([A-Z0-9]+)\s*\(/i,
  /Bag:\s*([A-Z0-9]+)\b/i,
  /Bag\s*ID\s*[:\s]+\s*([A-Z0-9]{4,})\b/i,
];

export function matchBagInText(text) {
  const t = String(text || "");
  for (const re of BAG_PATTERNS) {
    const m = t.match(re);
    if (m?.[1]) return { bagId: String(m[1]).toUpperCase(), raw: m[0] };
  }
  return { bagId: "", raw: "" };
}

function rowActionTimeoutMs() {
  const n = parseInt(process.env.RINSE_ROW_ACTION_TIMEOUT_MS || "3200", 10);
  return Math.max(1200, Math.min(25000, Number.isFinite(n) ? n : 3200));
}

async function isBagDetailsControl(loc) {
  try {
    const text = ((await loc.innerText().catch(() => "")) || "").trim();
    const blob = text.toLowerCase();
    return /show\s+bag\s+details|hide\s+bag\s+details/.test(blob);
  } catch {
    return false;
  }
}

export async function clickExpandOnRow(rowLocator) {
  const t = rowActionTimeoutMs();
  const firstCell = rowLocator.locator("td").first();
  for (const kind of ["button", '[role="button"]', "a"]) {
    const n = await firstCell.locator(kind).count().catch(() => 0);
    for (let j = 0; j < Math.min(n, 20); j++) {
      const loc = firstCell.locator(kind).nth(j);
      try {
        if (!(await loc.isVisible().catch(() => false))) continue;
        if (kind === "a" && (await isBagDetailsControl(loc))) continue;
        await loc.click({ timeout: t, noWaitAfter: true });
        return true;
      } catch {
        /* next */
      }
    }
  }
  return false;
}

async function ticketExpansionVisible(rowLocator) {
  const showRe = /show\s+bag\s+details/i;
  const hideRe = /hide\s+bag\s+details/i;
  const roots = [rowLocator.locator("xpath=./following-sibling::tr[1]"), rowLocator];
  for (const root of roots) {
    if (await root.getByRole("link", { name: showRe }).first().isVisible().catch(() => false)) {
      return true;
    }
    if (await root.getByRole("link", { name: hideRe }).first().isVisible().catch(() => false)) {
      return true;
    }
    if (await root.locator("text=/\\bScans\\b/i").first().isVisible().catch(() => false)) {
      return true;
    }
  }
  return false;
}

export async function ensureRowExpandedForTicket(rowLocator, page) {
  if (await ticketExpansionVisible(rowLocator)) return true;
  const clicked = await clickExpandOnRow(rowLocator);
  const expandSettle = Math.max(
    200,
    Math.min(12000, parseInt(process.env.RINSE_EXPAND_SETTLE_MS || "450", 10) || 450),
  );
  if (clicked) await page.waitForTimeout(expandSettle);
  const scanSettle = Math.max(
    0,
    Math.min(8000, parseInt(process.env.RINSE_SCAN_TABLE_SETTLE_MS || "600", 10) || 600),
  );
  if (scanSettle > 0) await page.waitForTimeout(scanSettle);
  return clicked || (await ticketExpansionVisible(rowLocator));
}

export async function ensureRowCollapsedAfterTicket(rowLocator, page) {
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(90);
  const v = (process.env.RINSE_SKIP_ROW_COLLAPSE ?? "1").trim().toLowerCase();
  if (v !== "0" && v !== "false" && v !== "off") return;
  if (await ticketExpansionVisible(rowLocator)) {
    await clickExpandOnRow(rowLocator);
    await page.waitForTimeout(400);
  }
}

export async function isLikelyLoginPage(page) {
  const url = page.url().toLowerCase();
  if (url.includes("/accounts/login")) return true;
  const pw = page.locator('input[type="password"]').first();
  return pw.isVisible().catch(() => false);
}

export async function tryLogin(page, cleanerTicketsUrl) {
  const email = process.env.RINSE_EMAIL?.trim();
  const password = process.env.RINSE_PASSWORD?.trim();
  if (!email || !password) return false;
  const loginUrl = buildLoginUrlWithNext(cleanerTicketsUrl);
  await page.goto(loginUrl, { waitUntil: "domcontentloaded", timeout: navTimeoutMs() });
  await page.fill('input[type="email"], input[name="email"]', email).catch(() => {});
  await page.fill('input[type="password"]', password).catch(() => {});
  await page.locator('button[type="submit"], input[type="submit"]').first().click().catch(() => {});
  await page.waitForTimeout(2500);
  return !(await isLikelyLoginPage(page));
}

function buildLoginUrlWithNext(cleanerTicketsFullUrl) {
  const fallback = "https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1";
  let u;
  try {
    u = new URL(String(cleanerTicketsFullUrl || "").trim() || fallback);
  } catch {
    u = new URL(fallback);
  }
  const login = new URL(RINSE_LOGIN_URL);
  login.searchParams.set("next", `${u.pathname}${u.search}`);
  return login.toString();
}

export async function hasNextPageInUi(page, currentPageNum) {
  return page
    .evaluate(({ n }) => {
      const want = n + 1;
      const links = Array.from(document.querySelectorAll("a[href*='page=']"));
      return links.some((a) => {
        try {
          const u = new URL(a.href, window.location.href);
          return parseInt(u.searchParams.get("page") || "0", 10) === want;
        } catch {
          return false;
        }
      });
    }, { n: currentPageNum })
    .catch(() => false);
}

/**
 * Parse the "Scans" mini-table in the expanded ticket detail row.
 * @returns {Promise<Array<{rack,time_scanned,user,purpose,is_last_location,is_last_scan}>>}
 */
export async function extractScansFromExpandedTicket(rowLocator) {
  return rowLocator.evaluate((row) => {
    const norm = (s) => String(s || "").replace(/\s+/g, " ").trim();
    const detail = row.nextElementSibling;
    if (!detail || detail.tagName !== "TR") return [];

    const events = [];
    const tables = detail.querySelectorAll("table");
    for (const table of tables) {
      const headRow =
        table.querySelector("thead tr") ||
        table.querySelector("tr");
      const headText = norm(headRow?.innerText || "");
      if (!/rack/i.test(headText) || !/time\s+scanned/i.test(headText)) continue;

      const bodyRows = table.querySelectorAll("tbody tr");
      const dataRows = bodyRows.length ? bodyRows : table.querySelectorAll("tr");
      for (const tr of dataRows) {
        if (tr === headRow) continue;
        const cells = Array.from(tr.querySelectorAll("td")).map((td) => norm(td.innerText));
        if (cells.length < 2) continue;
        const rowText = norm(tr.innerText);
        if (/^rack$/i.test(cells[0]) && /time\s+scanned/i.test(rowText)) continue;

        let rack = "";
        let timeScanned = "";
        let user = "";
        let purpose = "";
        if (cells.length >= 4) {
          [rack, timeScanned, user, purpose] = cells;
        } else if (cells.length === 3) {
          [rack, timeScanned, user] = cells;
          purpose = "";
        } else {
          continue;
        }
        if (/^rack$/i.test(rack) || /^time\s+scanned$/i.test(timeScanned)) continue;
        if (!timeScanned && !purpose) continue;

        const isLastLocation = /last\s+location/i.test(rowText);
        const isLastScan = /last\s+scan/i.test(rowText);
        events.push({
          rack,
          time_scanned: timeScanned,
          user,
          purpose,
          is_last_location: isLastLocation,
          is_last_scan: isLastScan,
        });
      }
    }
    return events;
  });
}

export function ticketContextFromCollapsedText(collapsedText) {
  const t = String(collapsedText || "").trim();
  const lines = t.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const dateLine = lines.find((l) => PORTAL_TICKET_DATE_LINE_RE.test(l)) || "";
  const customer =
    lines.find(
      (l) =>
        l.length > 2 &&
        !PORTAL_TICKET_DATE_LINE_RE.test(l) &&
        !/^bag:/i.test(l) &&
        !/lbs/i.test(l) &&
        !/^scans$/i.test(l),
    ) || "";
  const bag = matchBagInText(t);
  return {
    date_line: dateLine.slice(0, 120),
    customer_snippet: customer.slice(0, 80),
    bag_id: bag.bagId,
  };
}
