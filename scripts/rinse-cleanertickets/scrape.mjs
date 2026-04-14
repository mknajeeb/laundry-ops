/**
 * Expand Rinse cleaner-ticket rows and extract "Bag: ABCD123456" style bag IDs.
 * Supports multiple list pages (nightly export).
 *
 * See README.md for .env, save-session.mjs, and cron / Task Scheduler.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Optional .env next to this script (no npm `dotenv` — Azure App Service injects env vars). */
function loadLocalEnvFile() {
  try {
    const p = path.join(__dirname, ".env");
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
    // ignore
  }
}
loadLocalEnvFile();

/**
 * Ticket list rows. Rinse has changed layout before; we use several patterns.
 * Optional: RINSE_EXTRA_ROW_SELECTORS=comma-separated CSS appended to this list (DevTools → Copy → selector).
 */
function bodyRowsSelector() {
  const base = [
    "main table tbody tr",
    "main table > tbody > tr",
    "table tbody tr",
    "table > tbody > tr",
    "#content table tbody tr",
    ".content table tbody tr",
    "article table tbody tr",
    "table.sortable tbody tr",
    "[role='grid'] tbody tr",
    "[role='grid'] [role='row']",
    "div[role='table'] [role='row']",
    "[role='table'] [role='row']",
  ].join(", ");
  const extra = (process.env.RINSE_EXTRA_ROW_SELECTORS || "").trim();
  return extra ? `${base}, ${extra}` : base;
}

/** Rinse copy varies ("Bag: ABC123 (", "Bag: ABC123", "Bag ID: …"); try in order. */
const BAG_PATTERNS = [
  /Bag:\s*([A-Z0-9]+)\s*\(/i,
  /Bag:\s*([A-Z0-9]+)\b/i,
  /Bag\s*ID\s*[:\s]+\s*([A-Z0-9]{4,})\b/i,
  /\bBag\s*[:\s#]+\s*([A-Z0-9]{6,})\b/i,
];

function matchBagInText(text) {
  const t = String(text || "");
  for (const re of BAG_PATTERNS) {
    const m = t.match(re);
    if (m?.[1]) return { bagId: String(m[1]).toUpperCase(), raw: m[0] };
  }
  return { bagId: "", raw: "" };
}

/** Bag line for CSV: `CODE (Service) (Sub…)` after `Bag:`; `bagId` is the code only. */
function matchBagDisplayInText(text) {
  const t = String(text || "");
  const mline = t.match(/Bag:\s*([^\n]+)/i);
  if (mline) {
    const rest = mline[1].trim().replace(/\s+/g, " ");
    const idm = rest.match(/^([A-Z0-9]+)/i);
    return {
      bagId: idm ? idm[1].toUpperCase() : "",
      bagDisplay: rest,
      raw: mline[0].trim().replace(/\s+/g, " "),
    };
  }
  const b = matchBagInText(t);
  return { bagId: b.bagId, bagDisplay: b.bagId || "", raw: b.raw };
}

/** Rinse email/password form (avoid homepage hop). */
const RINSE_LOGIN_URL = "https://www.rinse.com/accounts/login/";

/**
 * Same redirect the browser uses: visiting cleanertickets while logged out sends you to
 * /accounts/login/?next=%2Fcleanertickets%2F%3F... so post-login returns to the list.
 */
function buildLoginUrlWithNext(cleanerTicketsFullUrl) {
  const fallback = "https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1";
  let u;
  try {
    u = new URL(String(cleanerTicketsFullUrl || "").trim() || fallback);
  } catch {
    u = new URL(fallback);
  }
  const host = u.hostname.toLowerCase().replace(/^www\./, "");
  if (host !== "rinse.com") {
    u = new URL(fallback);
  }
  const next = `${u.pathname}${u.search}`;
  const login = new URL(RINSE_LOGIN_URL);
  login.searchParams.set("next", next);
  return login.toString();
}

/** Default 120s — Azure egress to rinse.com is often slower than a laptop; override with RINSE_NAV_TIMEOUT_MS. */
function navTimeoutMs() {
  const n = parseInt(process.env.RINSE_NAV_TIMEOUT_MS || "120000", 10);
  return Math.max(15000, Math.min(300000, Number.isFinite(n) ? n : 120000));
}

function navGotoOpts(waitUntil = "domcontentloaded") {
  return { waitUntil, timeout: navTimeoutMs() };
}

function csvEscape(s) {
  const t = String(s ?? "").replace(/"/g, '""');
  return `"${t}"`;
}

/** Build cleanertickets URL with a given page= (preserves other query params). */
function urlForPage(baseUrl, pageNum) {
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

function defaultOutputPath() {
  const stamp = new Date().toISOString().slice(0, 10);
  return path.join(__dirname, `bag-ids-${stamp}.csv`);
}

async function isLikelyLoginPage(page) {
  const u = page.url() || "";
  if (/\/accounts\/login/i.test(u) || /\/login/i.test(u)) return true;
  const pw = page.locator('input[type="password"]').first();
  if (await pw.isVisible().catch(() => false)) {
    const em = page.locator('input[type="email"], input[name*="email" i]').first();
    if (await em.isVisible().catch(() => false)) return true;
  }
  return false;
}

async function tryLogin(page, cleanerTicketsUrlForNext) {
  const email = process.env.RINSE_EMAIL?.trim();
  const password = process.env.RINSE_PASSWORD?.trim();
  if (!email || !password) {
    console.warn("RINSE_EMAIL / RINSE_PASSWORD not set — use RINSE_STORAGE_STATE=./rinse-auth.json after save-session.mjs");
    return;
  }

  const loginUrl = buildLoginUrlWithNext(cleanerTicketsUrlForNext);
  console.log("Opening Rinse login with return path (next=) matching RINSE_TICKETS_URL");
  await page.goto(loginUrl, navGotoOpts("domcontentloaded"));
  await page.waitForTimeout(1200);

  const emailField = page.locator('input[type="email"], input[name*="email" i], input[id*="email" i]').first();
  const passField = page.locator('input[type="password"]').first();

  if (await emailField.isVisible().catch(() => false)) {
    await emailField.fill(email);
  }
  if (await passField.isVisible().catch(() => false)) {
    await passField.fill(password);
  }

  const submit = page.getByRole("button", { name: /log\s*in|sign\s*in|continue/i }).first();
  if (await submit.isVisible().catch(() => false)) {
    await submit.click();
  }

  try {
    await page.waitForURL(
      (url) => !/\/accounts\/login/i.test(url.pathname) && /rinse\.com/i.test(url.hostname),
      { timeout: 45000 },
    );
  } catch {
    /* MFA or slow redirect — continue; first cleanertickets goto may still work */
  }
  await page.waitForTimeout(2000);
}

/** Keep clicks bounded so one bad control cannot block the whole export (Playwright default can be 30s+). */
function rowActionTimeoutMs() {
  const n = parseInt(process.env.RINSE_ROW_ACTION_TIMEOUT_MS || "5000", 10);
  return Math.max(1500, Math.min(25000, Number.isFinite(n) ? n : 5000));
}

/** Row chevron vs “Show/Hide bag details” — first <a> in the cell is often bag details; clicking it never collapses the ticket. */
async function isBagDetailsControl(loc) {
  try {
    const text = ((await loc.innerText().catch(() => "")) || "").trim();
    const al = ((await loc.getAttribute("aria-label").catch(() => "")) || "").trim();
    const title = ((await loc.getAttribute("title").catch(() => "")) || "").trim();
    const blob = `${text} ${al} ${title}`.toLowerCase();
    return /show\s+bag\s+details|hide\s+bag\s+details/.test(blob);
  } catch {
    return false;
  }
}

/**
 * Click the ticket row expand/collapse control (first cell), skipping bag-details links.
 */
async function clickExpandOnRow(rowLocator) {
  const t = rowActionTimeoutMs();
  const firstCell = rowLocator.locator("td").first();
  const kinds = ["button", '[role="button"]', "a"];
  for (const kind of kinds) {
    const n = await firstCell.locator(kind).count().catch(() => 0);
    for (let j = 0; j < Math.min(n, 20); j++) {
      const loc = firstCell.locator(kind).nth(j);
      try {
        if (!(await loc.isVisible().catch(() => false))) continue;
        if (kind === "a" && (await isBagDetailsControl(loc))) continue;
        await loc.click({ timeout: t, noWaitAfter: true });
        return true;
      } catch {
        /* try next */
      }
    }
  }
  /* Rare layouts: control not in first td */
  const rowBtn = rowLocator.locator("> td button, > td [role='button']").first();
  try {
    if (await rowBtn.isVisible().catch(() => false)) {
      await rowBtn.click({ timeout: t, noWaitAfter: true });
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

/** True if this ticket row already has an expansion row with bag UI (Show or Hide bag details). */
async function ticketExpansionHasBagLinks(rowLocator) {
  const tr1 = rowLocator.locator("xpath=./following-sibling::tr[1]");
  const show1 = tr1.getByRole("link", { name: /show\s+bag\s+details/i });
  const hide1 = tr1.getByRole("link", { name: /hide\s+bag\s+details/i });
  if (await show1.first().isVisible().catch(() => false)) return true;
  if (await hide1.first().isVisible().catch(() => false)) return true;
  const show0 = rowLocator.getByRole("link", { name: /show\s+bag\s+details/i });
  const hide0 = rowLocator.getByRole("link", { name: /hide\s+bag\s+details/i });
  if (await show0.first().isVisible().catch(() => false)) return true;
  if (await hide0.first().isVisible().catch(() => false)) return true;
  return false;
}

async function ensureRowExpandedForTicket(rowLocator, page) {
  if (await ticketExpansionHasBagLinks(rowLocator)) return true;
  const clicked = await clickExpandOnRow(rowLocator);
  const expandSettle = Math.max(
    400,
    Math.min(12000, parseInt(process.env.RINSE_EXPAND_SETTLE_MS || "1200", 10) || 1200),
  );
  if (clicked) await page.waitForTimeout(expandSettle);
  return clicked || (await ticketExpansionHasBagLinks(rowLocator));
}

async function hideBagDetailsIfVisible(rowLocator, page) {
  const t = rowActionTimeoutMs();
  for (const loc of bagDetailsToggleLocators(rowLocator, "hide")) {
    const first = loc.first();
    try {
      if (await first.isVisible().catch(() => false)) {
        await first.click({ timeout: t, noWaitAfter: true });
        await page.waitForTimeout(250);
        return true;
      }
    } catch {
      /* ignore */
    }
  }
  return false;
}

async function ensureRowCollapsedAfterTicket(rowLocator, page) {
  if ((process.env.RINSE_SKIP_ROW_COLLAPSE || "").trim() === "1") {
    return;
  }
  const maxMs = Math.max(
    1500,
    Math.min(45000, parseInt(process.env.RINSE_COLLAPSE_MAX_MS || "6000", 10) || 6000),
  );
  const ms = Math.max(
    200,
    Math.min(5000, parseInt(process.env.RINSE_COLLAPSE_SETTLE_MS || "450", 10) || 450),
  );
  const maxIters = Math.max(2, Math.min(40, parseInt(process.env.RINSE_COLLAPSE_MAX_ITERS || "12", 10) || 12));
  const deadline = Date.now() + maxMs;

  await hideBagDetailsIfVisible(rowLocator, page);
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(120);

  let iter = 0;
  while (
    iter < maxIters &&
    Date.now() < deadline &&
    (await ticketExpansionHasBagLinks(rowLocator))
  ) {
    iter += 1;
    try {
      await clickExpandOnRow(rowLocator);
    } catch (e) {
      console.warn("  row collapse click:", (e && e.message) || e);
    }
    await page.waitForTimeout(ms);
    await hideBagDetailsIfVisible(rowLocator, page);
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(120);
  }

  if (await ticketExpansionHasBagLinks(rowLocator)) {
    console.warn(
      "  Ticket row still expanded after collapse — continuing. Set RINSE_SKIP_ROW_COLLAPSE=1 if the scrape stalls here.",
    );
  }
}

/**
 * Skip tbody <tr> that are the *expanded detail* row for a ticket (not a new ticket).
 * Those rows show portal links (Show bag details) but not the list “Estd. delivery + date” pattern.
 */
function isLikelyExpandedDetailSubRow(trimmed) {
  const head = trimmed.slice(0, 420);
  const hasPortalDetailLinks =
    /show\s+bag\s+details|hide\s+bag\s+details|show\s+issue\s+details|show\s+qc\s+details/i.test(
      head,
    );
  const hasListRowDateLine = /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b.+\d{1,2}\/\d{1,2}/i.test(
    trimmed.slice(0, 200),
  );
  return hasPortalDetailLinks && !hasListRowDateLine;
}

/** Top-level cleaner-ticket row (not a nested <tr> inside an expanded ticket). */
function isMainListTicketRow(trimmed) {
  const t = trimmed.slice(0, 500);
  return /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\/\d{1,2}/i.test(t);
}

async function isProbablySingleCellDetailRow(rowLocator) {
  const tdCount = await rowLocator.locator("td").count().catch(() => 0);
  if (tdCount !== 1) return false;
  const colspan = await rowLocator.locator("td").first().getAttribute("colspan").catch(() => null);
  const n = colspan ? parseInt(colspan, 10) : 0;
  return Number.isFinite(n) && n >= 3;
}

/**
 * Bag line is hidden until this link is clicked (per ticket). Rinse puts the link in the main <tr>
 * or in the *next* sibling <tr>.
 * If the section is already open, Rinse shows “Hide bag details” instead — treat as OK.
 */
function bagDetailsToggleLocators(rowLocator, mode) {
  const nameRe =
    mode === "hide" ? /hide\s+bag\s+details/i : /show\s+bag\s+details/i;
  const out = [];
  out.push(rowLocator.getByRole("link", { name: nameRe }));
  for (let k = 1; k <= 6; k++) {
    out.push(
      rowLocator
        .locator(`xpath=./following-sibling::tr[${k}]`)
        .getByRole("link", { name: nameRe }),
    );
  }
  return out;
}

async function ensureShowBagDetailsForTicketRow(rowLocator) {
  const page = rowLocator.page();
  const settleMs = Math.max(
    400,
    Math.min(15000, parseInt(process.env.RINSE_BAG_DETAILS_SETTLE_MS || "1200", 10) || 1200),
  );
  const pollMs = 200;
  const deadline =
    Date.now() +
    Math.max(8000, parseInt(process.env.RINSE_SHOW_BAG_WAIT_MS || "14000", 10) || 14000);
  const clickT = rowActionTimeoutMs();

  for (const loc of bagDetailsToggleLocators(rowLocator, "hide")) {
    const first = loc.first();
    if (await first.isVisible().catch(() => false)) {
      await page.waitForTimeout(settleMs);
      return true;
    }
  }

  while (Date.now() < deadline) {
    for (const loc of bagDetailsToggleLocators(rowLocator, "show")) {
      const first = loc.first();
      if (await first.isVisible().catch(() => false)) {
        await first.click({ timeout: clickT, noWaitAfter: true });
        await page.waitForTimeout(settleMs);
        return true;
      }
    }
    await page.waitForTimeout(pollMs);
  }
  return false;
}

/**
 * After row expand, Rinse injects detail HTML (often after vendorinline). `.bag-details` may exist
 * but stay hidden until “Show bag details”; `textContent` still includes that subtree for Bag:/weight.
 */
async function readBagFromRowBlock(rowLocator) {
  const text = await rowLocator
    .evaluate((el) => {
      const chunks = [];
      const appendNode = (node) => {
        if (!node) return;
        chunks.push(node.innerText || "");
        const bd = node.querySelector && node.querySelector(".bag-details");
        if (bd) {
          const tc = bd.textContent || "";
          if (tc.trim()) chunks.push(tc);
        }
      };
      appendNode(el);
      let n = el.nextElementSibling;
      for (let i = 0; i < 8 && n; i++) {
        appendNode(n);
        n = n.nextElementSibling;
      }
      return chunks.join("\n");
    })
    .catch(() => "");

  const { bagId, raw: bagRaw, bagDisplay } = matchBagDisplayInText(text);
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const customer =
    lines.find(
      (l) =>
        l.length > 2 &&
        !/^bag:/i.test(l) &&
        !/hide\s+bag/i.test(l) &&
        !/estd\.?/i.test(l) &&
        !/lbs/i.test(l) &&
        !/^scans$/i.test(l)
    ) || "";

  return {
    bagId,
    bagDisplay: bagDisplay || bagId,
    raw: bagRaw,
    customer: customer.slice(0, 80),
    fullText: text,
  };
}

/**
 * List row often starts with status (“AT VENDOR”, chevrons) before “Tue 4/14 … Name …”.
 * Using only the first non-empty line drops Date/Customer into empty while Bag still parses.
 */
function pickPortalListLine(collapsedRowText, expandedFullText) {
  const dateRe =
    /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)\b/i;
  for (const block of [collapsedRowText, expandedFullText]) {
    const lines = String(block || "")
      .split(/\r?\n/)
      .map((l) => l.trim().replace(/\t+/g, " "))
      .filter((l) => l.length > 2);
    for (const line of lines) {
      if (dateRe.test(line)) return line;
    }
  }
  return (
    String(collapsedRowText || "")
      .split(/\r?\n/)
      .map((l) => l.trim().replace(/\t+/g, " "))
      .find((l) => l.length > 0) || ""
  );
}

/** Match the manual “copy from portal” Excel: date, customer, weight, notes, X-columns, bag id. */
function parsePortalFields(collapsedRowText, expandedFullText) {
  const combined = `${String(collapsedRowText || "").trim()}\n${String(expandedFullText || "").trim()}`.trim();
  const listLine = pickPortalListLine(collapsedRowText, expandedFullText);

  let dateDisplay = "";
  // Include optional /year so "Tue 04/14/2026" is one match — otherwise rest becomes "/2026 Name …".
  const dm = listLine.match(
    /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)\b/i
  );
  if (dm) {
    dateDisplay = `${dm[1]} ${dm[2]}`;
  }
  if (!dateDisplay) {
    const dm2 = combined.match(
      /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)\b/i
    );
    if (dm2) dateDisplay = `${dm2[1]} ${dm2[2]}`;
  }

  const firstLine = listLine;

  let weight = "?? LBS";
  if (/\?\?\s*LBS/i.test(firstLine) || /\?\?\s*LBS/i.test(combined)) {
    weight = "?? LBS";
  } else {
    const wm = combined.match(/(\d+(?:\.\d+)?)\s*(?:lbs|lb)\b/i);
    if (wm) weight = wm[0].replace(/\s+/g, " ").toUpperCase();
  }

  let customer = "";
  if (dm) {
    let rest = firstLine.slice(dm.index + dm[0].length).trim();
    rest = rest.replace(/^\/?\d{4}\b\s*/, "").trim();
    rest = rest.replace(/\?\?\s*LBS/gi, "").replace(/\d+(?:\.\d+)?\s*(?:lbs|lb)\b/gi, "").trim();
    rest = rest
      .replace(/^\s*(at\s+vendor|at\s+customer|in\s+process|pending|picked\s*up|delivered)\b\s*/gi, "")
      .trim();
    customer = rest.replace(/\s+/g, " ").slice(0, 200);
  }
  if (!customer) {
    customer = String(collapsedRowText || combined)
      .replace(/\t/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 200);
  }
  if ((!customer || customer.length < 2) && dateDisplay) {
    const parts = combined.split(
      new RegExp(dateDisplay.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"),
    );
    const tail = parts.length > 1 ? parts[1] : "";
    const one = tail.trim().split(/\r?\n/)[0] || "";
    const c2 = one
      .replace(/\?\?\s*LBS/gi, "")
      .replace(/\d+(?:\.\d+)?\s*(?:lbs|lb)\b/gi, "")
      .replace(/^\s*(at\s+vendor|at\s+customer|in\s+process|pending)\b\s*/gi, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 200);
    if (c2.length >= 2) customer = c2;
  }

  const t = combined;
  const tl = t.toLowerCase();
  const flags = {
    USE_OXIC: /oxic|oxi\s*clean/i.test(t) ? "X" : "",
    Use_Hypo: /\bhypo\b/i.test(t) && !/hypochlor/i.test(tl) ? "X" : "",
    USE_FAB: /fab(?:ric)?|softener|soft\s*ener/i.test(tl) ? "X" : "",
    Low_DRY: /low\s*dry/i.test(tl) ? "X" : "",
    NO_SCEN: /no\s*scen|no\s*scent|unscented/i.test(tl) ? "X" : "",
    Extra_Scen: /extra\s*scen|extra\s*scent/i.test(tl) ? "X" : "",
  };

  const skipLine = (l) =>
    !l ||
    /^bag:/i.test(l) ||
    /hide\s+bag/i.test(l) ||
    /^scans$/i.test(l) ||
    /estd\.?/i.test(l) ||
    /^rack\b/i.test(l) ||
    /^time\s+scanned/i.test(l);

  const noteLines = t
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 1 && !skipLine(l) && !/^\d+$/.test(l));
  let notes = noteLines
    .filter((l) => /use |dry|scen|hypo|fab|oxic|wash|fold|hang/i.test(l) || l.length > 12)
    .slice(0, 6)
    .join("; ");
  if (!notes) notes = noteLines.slice(0, 3).join("; ");
  notes = notes.slice(0, 500);

  let estd_delivery = dateDisplay;
  const em = combined.match(/\bEstd\.?\s*Del(?:ivery)?\s*:?\s*([^\n]+)/i);
  if (em) {
    estd_delivery = em[1].trim().replace(/\s+/g, " ").slice(0, 120);
  }

  let wf_lbs = "";
  const wfLbsM =
    combined.match(/#\s*WF\s*LBS\s*:?\s*(\d+\.?\d*)\b/i) ||
    combined.match(/\bWF\s*LBS\s*:?\s*(\d+\.?\d*)\b/i);
  if (wfLbsM) wf_lbs = wfLbsM[1];
  if (!wf_lbs && weight) {
    const wn = String(weight).match(/(\d+\.\d+)/);
    if (wn) wf_lbs = wn[1];
  }

  let wf_count = "";
  const wfCntM =
    combined.match(/#\s*WF\s*COUNT\s*:?\s*(\d+)\b/i) ||
    combined.match(/\bWF\s*COUNT\s*:?\s*(\d+)\b/i);
  if (wfCntM) wf_count = wfCntM[1];

  /** Shown on the portal only when the list page includes at least one Hang Dry–style order. */
  let wf_items = "";
  const wfItemsM =
    combined.match(/#\s*WF\s*ITEMS\s*:?\s*(\d+)\b/i) ||
    combined.match(/\bWF\s*ITEMS\s*:?\s*(\d+)\b/i);
  if (wfItemsM) wf_items = wfItemsM[1];

  return {
    date_display: dateDisplay,
    estd_delivery,
    customer_name: customer,
    weight_display: weight,
    wf_lbs,
    wf_count,
    wf_items,
    notes_summary: notes,
    ...flags,
  };
}

function csvLayout() {
  const raw = (process.env.RINSE_CSV_LAYOUT || "legacy").trim().toLowerCase();
  if (raw === "portal" || raw === "sheet" || raw === "excel") return "portal";
  return "legacy";
}

function portalHeaderRow() {
  return [
    "Date",
    "Estd. Delivery",
    "Customer",
    "# WF LBS",
    "# WF COUNT",
    "# WF ITEMS",
    "Weight",
    "Notes",
    "USE OXIC",
    "Use Hypo",
    "USE FAB",
    "Low DRY",
    "NO SCEN",
    "Extra Scen",
    "Bag ID",
  ];
}

function portalDataRow(portal, bagDisplay) {
  const bd = bagDisplay || "";
  return [
    portal.date_display,
    portal.estd_delivery || portal.date_display,
    portal.customer_name,
    portal.wf_lbs || "",
    portal.wf_count || "",
    portal.wf_items || "",
    portal.weight_display,
    portal.notes_summary,
    portal.USE_OXIC,
    portal.Use_Hypo,
    portal.USE_FAB,
    portal.Low_DRY,
    portal.NO_SCEN,
    portal.Extra_Scen,
    bd,
  ];
}

async function expandRowAndReadBag(page, rowLocator, collapsedRowText) {
  await ensureRowExpandedForTicket(rowLocator, page);
  const inlineSettle = Math.max(
    0,
    Math.min(5000, parseInt(process.env.RINSE_VENDORINLINE_SETTLE_MS || "800", 10) || 800),
  );
  if (inlineSettle > 0) await page.waitForTimeout(inlineSettle);

  let r = await readBagFromRowBlock(rowLocator);
  const skipShow =
    (process.env.RINSE_SKIP_SHOW_BAG_DETAILS || "").trim() === "1";

  if (!r.bagId && !skipShow) {
    const bagOk = await ensureShowBagDetailsForTicketRow(rowLocator);
    if (!bagOk) {
      const hint = (collapsedRowText || "").trim().replace(/\s+/g, " ").slice(0, 80);
      console.warn(
        `  Show bag details not found or not clickable for a ticket row${hint ? ` (${hint})` : ""} — bag/weight may be wrong.`,
      );
    }
    const r2 = await readBagFromRowBlock(rowLocator);
    const merged = `${r.fullText}\n${r2.fullText}`.trim();
    const bagMatch = matchBagDisplayInText(merged);
    const lines = merged.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const custLine =
      lines.find(
        (l) =>
          l.length > 2 &&
          !/^bag:/i.test(l) &&
          !/hide\s+bag/i.test(l) &&
          !/estd\.?/i.test(l) &&
          !/lbs/i.test(l) &&
          !/^scans$/i.test(l),
      ) || "";
    r = {
      bagId: bagMatch.bagId || r2.bagId || r.bagId,
      bagDisplay: bagMatch.bagDisplay || r2.bagDisplay || r.bagDisplay,
      raw: bagMatch.raw || r2.raw || r.raw,
      customer: (custLine || r2.customer || r.customer || "").slice(0, 80),
      fullText: merged,
    };
  } else if (!r.bagId && skipShow) {
    const hint = (collapsedRowText || "").trim().replace(/\s+/g, " ").slice(0, 80);
    console.warn(
      `  No bag id after expand (RINSE_SKIP_SHOW_BAG_DETAILS=1)${hint ? ` (${hint})` : ""}.`,
    );
  }
  if (!r.bagId && collapsedRowText) {
    const fromCollapsed = matchBagInText(collapsedRowText);
    if (fromCollapsed.bagId) {
      const lines = collapsedRowText.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      const customer =
        lines.find(
          (l) =>
            l.length > 2 &&
            !/^bag:/i.test(l) &&
            !/hide\s+bag/i.test(l) &&
            !/estd\.?/i.test(l) &&
            !/lbs/i.test(l) &&
            !/^scans$/i.test(l)
        ) || "";
      const bd = matchBagDisplayInText(collapsedRowText);
      return {
        bagId: fromCollapsed.bagId,
        bagDisplay: bd.bagDisplay || fromCollapsed.bagId,
        raw: fromCollapsed.raw,
        customer: customer.slice(0, 80),
        fullText: r.fullText || collapsedRowText,
        collapsed: collapsedRowText,
      };
    }
  }
  const outR = { ...r, collapsed: collapsedRowText };
  if (!outR.bagDisplay) outR.bagDisplay = outR.bagId || "";
  const c0 = String(collapsedRowText || "").trim();
  const f0 = String(outR.fullText || "").trim();
  if (c0 && f0 && !/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\/\d{1,2}/i.test(f0)) {
    outR.fullText = `${c0}\n${f0}`.trim();
  } else if (c0 && !f0) {
    outR.fullText = c0;
  }
  return outR;
}

async function scrapePage(page, pageLabel, layout) {
  const sel = bodyRowsSelector();
  await page.waitForTimeout(2000);
  await page.locator(sel).first().waitFor({ state: "visible", timeout: 25000 }).catch(() => {});
  await page.waitForTimeout(800);
  const initialRowCount = await page.locator(sel).count();
  if (initialRowCount === 0) {
    console.warn("No rows matched row selectors — set RINSE_EXTRA_ROW_SELECTORS from DevTools or inspect page HTML.");
  }

  const out = [];
  let recordIndex = 0;
  const rowsAll = page.locator(sel);

  // Re-count rows each index: expanding a ticket can insert <tr> nodes; a fixed `n` can skip rows
  // or pair the wrong locator with the wrong ticket after the DOM shifts.
  for (let i = 0; ; i++) {
    const n = await rowsAll.count();
    if (i >= n) break;
    const row = rowsAll.nth(i);
    await row.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(100);
    if (!(await row.isVisible().catch(() => false))) continue;
    const tdCount = await row.locator("td").count().catch(() => 0);
    const thOnly =
      (await row.locator("th").count().catch(() => 0)) > 0 && tdCount === 0;
    if (thOnly) continue;

    const rowText = (await row.innerText().catch(() => "")) || "";
    const trimmed = rowText.trim();
    if (trimmed.length < 6 || /^(scans|rack|time scanned)/i.test(trimmed)) {
      continue;
    }
    if (await isProbablySingleCellDetailRow(row)) continue;
    if (isLikelyExpandedDetailSubRow(trimmed)) continue;
    if (!isMainListTicketRow(trimmed)) continue;

    recordIndex += 1;
    const { bagId, bagDisplay, raw, customer, fullText, collapsed } = await expandRowAndReadBag(
      page,
      row,
      rowText,
    );
    const base = {
      page: pageLabel,
      row_index: recordIndex,
      customer_snippet: customer,
      bag_id: bagId,
      bag_display: bagDisplay || bagId,
      raw_line: raw,
    };
    if (layout === "portal") {
      const portal = parsePortalFields(collapsed || rowText, fullText);
      out.push({ ...base, portal });
    } else {
      out.push(base);
    }

    if (bagId) {
      console.log(`  ticket ${recordIndex}: ${bagId}`);
    }

    await ensureRowCollapsedAfterTicket(row, page);
  }

  if (initialRowCount > 0 && out.length === 0) {
    const rows = page.locator(sel);
    const previews = [];
    for (let j = 0; j < Math.min(3, initialRowCount); j++) {
      const t = (await rows.nth(j).innerText().catch(() => "")) || "";
      previews.push(t.trim().replace(/\s+/g, " ").slice(0, 300));
    }
    console.warn(
      `Table matched ${initialRowCount} row(s) but 0 became export rows (visibility, <th>-only header rows, short text filter, or expand failed). First rows (truncated):\n---\n${previews.join("\n---\n")}\n---\nTry HEADED=1 to watch the browser, refresh rinse-auth.json, or set RINSE_EXTRA_ROW_SELECTORS to the ticket <tr> from DevTools.`,
    );
  }

  return { rows: out, tableRowCount: initialRowCount };
}

async function main() {
  const baseUrl =
    process.env.RINSE_TICKETS_URL?.trim() ||
    "https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1";
  const headed = process.env.HEADED === "1" || process.env.HEADED === "true";
  const storageRel = process.env.RINSE_STORAGE_STATE?.trim();
  const storageState =
    storageRel && fs.existsSync(path.resolve(__dirname, storageRel))
      ? path.resolve(__dirname, storageRel)
      : "";

  const pageStart = Math.max(1, parseInt(process.env.RINSE_PAGE_START || "1", 10) || 1);
  // Default 20 so a missed “end of pagination” signal does not run 50 slow pages; override with RINSE_MAX_PAGES.
  const maxPages = Math.min(500, Math.max(1, parseInt(process.env.RINSE_MAX_PAGES || "20", 10) || 20));
  const pageSettleMs = Math.max(
    600,
    Math.min(30000, parseInt(process.env.RINSE_PAGE_SETTLE_MS || "3500", 10) || 3500),
  );
  const outCsv =
    (process.env.OUTPUT_CSV && String(process.env.OUTPUT_CSV).trim()) || defaultOutputPath();
  const layout = csvLayout();
  if (layout === "portal") {
    console.log("CSV layout: portal (Excel-style columns + Bag ID). Set RINSE_CSV_LAYOUT=legacy for the compact debug CSV.");
  }

  const browser = await chromium.launch({
    headless: !headed,
    slowMo: headed ? 80 : 0,
    args: ["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox"],
  });
  const context = await browser.newContext(storageState ? { storageState } : {});
  const page = await context.newPage();
  const pwTimeout = Math.max(5000, Math.min(120000, navTimeoutMs()));
  page.setDefaultTimeout(pwTimeout);
  page.setDefaultNavigationTimeout(Math.max(pwTimeout, navTimeoutMs()));

  try {
    if (!storageState) {
      await tryLogin(page, baseUrl);
    }

    const allRows = [];
    /** Fingerprint of visible ticket rows so we stop when Rinse keeps serving the last page for page=3,4,… */
    let prevPageRowFingerprint = null;
    /** Sorted bag IDs on the previous page — Rinse often repeats the last page with the same tickets. */
    let prevPageBagSig = null;

    function normFingerprint(s) {
      return String(s || "")
        .replace(/\s+/g, " ")
        .trim();
    }

    for (let p = pageStart; p < pageStart + maxPages; p++) {
      const url = urlForPage(baseUrl, p);
      console.log(`\nPage ${p}: ${url}`);
      // "networkidle" often never settles on SPAs; domcontentloaded + fixed wait is more reliable on Azure.
      await page.goto(url, {
        waitUntil: "domcontentloaded",
        timeout: Math.max(navTimeoutMs(), 90000),
      });
      await page.waitForTimeout(pageSettleMs);
      await page
        .waitForSelector("table tbody tr", { timeout: 20000 })
        .catch(() => {});

      if (await isLikelyLoginPage(page)) {
        console.error(
          "\nNot logged in: Rinse showed a login page. Refresh session: upload a valid rinse-auth.json and set RINSE_STORAGE_STATE, or set RINSE_EMAIL + RINSE_PASSWORD on the API.",
        );
        await browser.close();
        process.exit(3);
      }

      const { rows, tableRowCount } = await scrapePage(page, url, layout);

      if (tableRowCount === 0) {
        const title = await page.title().catch(() => "");
        console.error(
          `\nStopping: no table rows on page ${p} (title: ${JSON.stringify(title)}). Either there are no tickets for this filter, or row selectors need updating — try RINSE_EXTRA_ROW_SELECTORS from DevTools (see scrape.mjs bodyRowsSelector).`,
        );
        break;
      }

      const rowFingerprint = await page
        .evaluate(() => {
          let trs = Array.from(document.querySelectorAll("table tbody tr")).filter((tr) =>
            tr.querySelector("td"),
          );
          if (trs.length === 0) {
            trs = Array.from(
              document.querySelectorAll("[role='grid'] [role='row'], [role='table'] [role='row']"),
            );
          }
          return trs
            .slice(0, 120)
            .map((tr) =>
              (tr.innerText || "")
                .trim()
                .replace(/\s+/g, " ")
                .slice(0, 140),
            )
            .join("\u241e");
        })
        .catch(() => "");

      const nf = normFingerprint(rowFingerprint);
      const np = prevPageRowFingerprint != null ? normFingerprint(prevPageRowFingerprint) : null;
      if (np != null && nf.length > 24 && nf === np) {
        console.log(
          `Stopping: page ${p} table text matches the previous page (pagination past the end).`,
        );
        break;
      }
      prevPageRowFingerprint = rowFingerprint;

      if (p > pageStart && rows.length === 0) {
        console.log(`Stopping: page ${p} had no extractable ticket rows after filtering.`);
        break;
      }

      const pageBagSig = [
        ...new Set(
          rows.map((r) => String(r.bag_id || "").trim().toUpperCase()).filter(Boolean),
        ),
      ]
        .sort()
        .join("\u241e");

      if (
        p > pageStart &&
        pageBagSig.length > 0 &&
        prevPageBagSig != null &&
        pageBagSig === prevPageBagSig
      ) {
        console.log(
          `Stopping: page ${p} has the same bag IDs as the previous page (no new tickets — stop pagination).`,
        );
        break;
      }
      if (pageBagSig.length > 0) {
        prevPageBagSig = pageBagSig;
      }

      allRows.push(...rows);

      const withBag = rows.filter((r) => r.bag_id).length;
      if (withBag === 0 && rows.length > 3) {
        console.warn(
          "Many rows but no Bag IDs — selectors or expand control may be wrong; check one row in DevTools."
        );
      }
    }

    if (allRows.length === 0) {
      console.error(
        "\nExport produced zero data rows. Fix auth (rinse-auth.json + RINSE_STORAGE_STATE), confirm RINSE_TICKETS_URL, or set RINSE_EXTRA_ROW_SELECTORS / update bodyRowsSelector() in scrape.mjs — see messages above.",
      );
      await browser.close();
      process.exit(2);
    }

    let header;
    let lines;
    if (layout === "portal") {
      header = portalHeaderRow().map(csvEscape).join(",") + "\n";
      lines = allRows.map((r) =>
        portalDataRow(r.portal, r.bag_display || r.bag_id)
          .map(csvEscape)
          .join(",") + "\n"
      );
    } else {
      header = "page,row_index,customer_snippet,bag_id,raw_line\n";
      lines = allRows.map(
        (r) =>
          [
            csvEscape(r.page),
            r.row_index,
            csvEscape(r.customer_snippet),
            csvEscape(r.bag_id),
            csvEscape(r.raw_line),
          ].join(",") + "\n"
      );
    }

    const dir = path.dirname(path.resolve(outCsv));
    if (dir && !fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(path.resolve(outCsv), header + lines.join(""), "utf8");
    console.log(`\nWrote ${allRows.length} row records → ${path.resolve(outCsv)}`);
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
