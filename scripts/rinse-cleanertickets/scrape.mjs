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

/** First thing on stderr so Windows CMD / double-click runs never look “silent” if something fails early. */
console.error("[rinse-scrape] scrape.mjs loaded — starting…");

/**
 * Write one log line to fd 1 so piped subprocess output updates promptly for server-side UI monitors.
 */
function progressLine(msg) {
  const s = typeof msg === "string" ? msg : String(msg);
  const out = s.endsWith("\n") ? s : `${s}\n`;
  try {
    fs.writeSync(1, out);
  } catch {
    console.log(typeof msg === "string" ? msg : String(msg));
  }
}

/**
 * Ticket list rows. Rinse has changed layout before; we use several patterns.
 * Optional: RINSE_EXTRA_ROW_SELECTORS=comma-separated CSS appended to this list (DevTools → Copy → selector).
 */
function bodyRowsSelector() {
  /* IMPORTANT: `tbody tr` matches nested <tr> inside “Scans” mini-tables — wrong order & dupes.
   * Prefer only direct children of tbody / rowgroup. */
  const base = [
    "main table > tbody > tr",
    "table.sortable > tbody > tr",
    "#content table > tbody > tr",
    ".content table > tbody > tr",
    "article table > tbody > tr",
    "table > tbody > tr",
    "[role='grid'] > [role='rowgroup'] > [role='row']",
    "[role='grid'] tbody > tr",
    "div[role='table'] > [role='rowgroup'] > [role='row']",
    "[role='table'] > [role='rowgroup'] > [role='row']",
    "[role='grid'] [role='row']",
    "div[role='table'] [role='row']",
    "[role='table'] [role='row']",
  ].join(", ");
  const extra = (process.env.RINSE_EXTRA_ROW_SELECTORS || "").trim();
  return extra ? `${base}, ${extra}` : base;
}

/**
 * Only `<tr>` in the big cleaner-tickets grid (avoids other `table > tbody > tr` on the page).
 * Override with RINSE_TICKET_TABLE_SELECTOR=CSS to a specific `<table>` if needed.
 */
function ticketTableBodyRows(page) {
  const env = (process.env.RINSE_TICKET_TABLE_SELECTOR || "").trim();
  if (env) {
    return page.locator(env).locator("> tbody > tr");
  }
  const tables = page.getByRole("table").filter({
    hasText: /Customer/i,
  });
  const ticketLike = tables.filter({
    hasText: /Estd|Estimated|#\s*WF|WF\s*LBS|#\s*HD/i,
  });
  return ticketLike.first().locator("> tbody > tr");
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

/** “Tue 4/14” or “Monday 04/14/2026” style list marker on cleaner-ticket rows. */
const PORTAL_TICKET_DATE_LINE_RE =
  /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+\d{1,2}\/\d{1,2}(?:\/\d{2,4})?\b/i;

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

/**
 * Whether pagination UI shows there is another page after `currentPageNum`.
 *
 * Prefer real `page=` links (avoids false positives from any control whose text is "2" or "3").
 * Legacy loose matching (old behavior) is opt-in: RINSE_PAGINATION_LOOSE=1
 */
async function hasNextPageInUi(page, currentPageNum) {
  const loose =
    String(process.env.RINSE_PAGINATION_LOOSE || "").trim() === "1" ||
    String(process.env.RINSE_PAGINATION_LOOSE || "").toLowerCase() === "true";

  return page
    .evaluate(
      ({ n, loose: looseMode }) => {
        const want = n + 1;
        const here = window.location.href;

        const looksDisabled = (el) => {
          if (!el) return true;
          const ar = String(el.getAttribute("aria-disabled") || "").toLowerCase();
          if (ar === "true") return true;
          const cls = String(el.className || "").toLowerCase();
          if (cls.includes("disabled")) return true;
          return false;
        };

        const hrefPageNum = (a) => {
          if (!(a instanceof HTMLAnchorElement) || !a.getAttribute("href")) return null;
          try {
            const u = new URL(a.href, here);
            const raw = u.searchParams.get("page");
            const p = parseInt(raw || "", 10);
            return Number.isFinite(p) && p > 0 ? p : null;
          } catch {
            return null;
          }
        };

        /** Strong signal: any non-disabled link with page=want */
        const pageLinks = Array.from(document.querySelectorAll('a[href*="page="]'));
        for (const a of pageLinks) {
          if (looksDisabled(a)) continue;
          const pn = hrefPageNum(a);
          if (pn === want) return true;
        }

        /** rel=next — only trust if href resolves to the next page index */
        for (const a of document.querySelectorAll('a[rel="next"], a[rel~="next"], link[rel="next"]')) {
          if (looksDisabled(a)) continue;
          const pn = hrefPageNum(a);
          if (pn === want) return true;
        }

        if (!looseMode) {
          return false;
        }

        /* --- Legacy (loose) fallbacks — can false-positive on last page; opt-in only --- */
        const nextLike = Array.from(
          document.querySelectorAll(
            "a[rel='next'], button[rel='next'], [aria-label*='next' i], .next a, .pagination-next a",
          ),
        );
        for (const el of nextLike) {
          const cls = String(el.className || "").toLowerCase();
          const ariaDisabled = String(el.getAttribute("aria-disabled") || "").toLowerCase();
          if (ariaDisabled === "true") continue;
          if (cls.includes("disabled")) continue;
          if (el instanceof HTMLAnchorElement && !el.href) continue;
          return true;
        }
        const scope =
          document.querySelector(".pagination, [class*='pagination'], nav[aria-label*='page' i]") ||
          document.body;
        return Array.from(scope.querySelectorAll("a[href], button, [role='button']")).some((el) => {
          const txt = (el.textContent || "").trim();
          if (txt !== String(want)) return false;
          const cls = String(el.className || "").toLowerCase();
          if (cls.includes("disabled")) return false;
          return true;
        });
      },
      { n: currentPageNum, loose },
    )
    .catch(() => false);
}

function pageNumFromUrl(u) {
  try {
    const parsed = new URL(String(u || ""));
    const n = parseInt(parsed.searchParams.get("page") || "", 10);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
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
  const n = parseInt(process.env.RINSE_ROW_ACTION_TIMEOUT_MS || "3200", 10);
  return Math.max(1200, Math.min(25000, Number.isFinite(n) ? n : 3200));
}

/** Notes column: `none` (default) = empty — ops use X-columns; `full` = legacy long text. */
function portalNotesMode() {
  const v = (process.env.RINSE_PORTAL_NOTES || "none").trim().toLowerCase();
  if (v === "full" || v === "1" || v === "yes" || v === "true") return "full";
  return "none";
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
  const showRe = /show\s+bag\s+details/i;
  const hideRe = /hide\s+bag\s+details/i;
  const roots = [rowLocator.locator("xpath=./following-sibling::tr[1]"), rowLocator];
  for (const root of roots) {
    for (const role of ["link", "button"]) {
      if (await root.getByRole(role, { name: showRe }).first().isVisible().catch(() => false)) return true;
      if (await root.getByRole(role, { name: hideRe }).first().isVisible().catch(() => false)) return true;
    }
    if (
      await root
        .locator("a, button, [role='button']")
        .filter({ hasText: showRe })
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      return true;
    }
    if (
      await root
        .locator("a, button, [role='button']")
        .filter({ hasText: hideRe })
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      return true;
    }
  }
  return false;
}

async function ensureRowExpandedForTicket(rowLocator, page) {
  if (await ticketExpansionHasBagLinks(rowLocator)) return true;
  const clicked = await clickExpandOnRow(rowLocator);
  const expandSettle = Math.max(
    200,
    Math.min(12000, parseInt(process.env.RINSE_EXPAND_SETTLE_MS || "450", 10) || 450),
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
  /* Default OFF for full row collapse: that path often stalls (wrong control / DOM).
   * Still always try to hide "bag details" so heavy detail DOM does not stack for every
   * prior ticket (otherwise Playwright slows sharply after ~10–20 rows on long lists). */
  await hideBagDetailsIfVisible(rowLocator, page);
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(90);

  const v = (process.env.RINSE_SKIP_ROW_COLLAPSE ?? "1").trim().toLowerCase();
  if (v !== "0" && v !== "false" && v !== "off") {
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

/** Top-level cleaner-ticket row (not a nested <tr> inside an expanded ticket). */
function isMainListTicketRow(trimmed) {
        return PORTAL_TICKET_DATE_LINE_RE.test(String(trimmed || "").slice(0, 900));
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
  const pushScoped = (root) => {
    out.push(root.getByRole("link", { name: nameRe }));
    out.push(root.getByRole("button", { name: nameRe }));
    out.push(
      root.locator("a, button, [role='button']").filter({ hasText: nameRe }),
    );
  };
  pushScoped(rowLocator);
  /* Large “Scans” expansions can push the bag-details link into a deeper following <tr>. */
  for (let k = 1; k <= 8; k++) {
    const sib = rowLocator.locator(`xpath=./following-sibling::tr[${k}]`);
    pushScoped(sib);
  }
  return out;
}

/** When Playwright role/name matching misses (icon-only, odd ARIA), click by visible text in the row block. */
async function tryClickShowBagDetailsDom(rowLocator) {
  return rowLocator
    .evaluate((el) => {
      const wantShow = (blob) => /show\s+bag\s+details/i.test(blob);
      const wantHide = (blob) => /hide\s+bag\s+details/i.test(blob);
      const tryClick = (root) => {
        if (!root || !root.querySelectorAll) return false;
        const cand = root.querySelectorAll("a, button, [role='button'], [role='link']");
        for (const node of cand) {
          const blob = `${node.textContent || ""} ${node.getAttribute("aria-label") || ""} ${node.getAttribute("title") || ""}`;
          if (wantShow(blob)) {
            (node).click();
            return true;
          }
        }
        return false;
      };
      if (tryClick(el)) return true;
      let n = el.nextElementSibling;
      for (let i = 0; i < 8 && n && n.tagName === "TR"; i++) {
        if (tryClick(n)) return true;
        n = n.nextElementSibling;
      }
      return false;
    })
    .catch(() => false);
}

async function ensureShowBagDetailsForTicketRow(rowLocator) {
  const page = rowLocator.page();
  const settleMs = Math.max(
    200,
    Math.min(15000, parseInt(process.env.RINSE_BAG_DETAILS_SETTLE_MS || "350", 10) || 350),
  );
  const pollMs = Math.max(40, Math.min(500, parseInt(process.env.RINSE_BAG_DETAILS_POLL_MS || "75", 10) || 75));
  const deadline =
    Date.now() +
    Math.max(1000, parseInt(process.env.RINSE_SHOW_BAG_WAIT_MS || "3200", 10) || 3200);
  const clickT = rowActionTimeoutMs();

  await rowLocator.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
  await rowLocator
    .locator("xpath=./following-sibling::tr[1]")
    .scrollIntoViewIfNeeded({ timeout: 4000 })
    .catch(() => {});

  for (const loc of bagDetailsToggleLocators(rowLocator, "hide")) {
    const first = loc.first();
    if (await first.isVisible().catch(() => false)) {
      await page.waitForTimeout(settleMs);
      return true;
    }
  }

  while (Date.now() < deadline) {
    await rowLocator.scrollIntoViewIfNeeded({ timeout: 4000 }).catch(() => {});
    for (const loc of bagDetailsToggleLocators(rowLocator, "show")) {
      const first = loc.first();
      if (await first.isVisible().catch(() => false)) {
        try {
          await first.click({ timeout: clickT, noWaitAfter: true });
        } catch {
          try {
            await first.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
            await first.click({ timeout: clickT, noWaitAfter: true, force: true });
          } catch {
            await tryClickShowBagDetailsDom(rowLocator);
          }
        }
        await page.waitForTimeout(settleMs);
        return true;
      }
    }
    if (await tryClickShowBagDetailsDom(rowLocator)) {
      await page.waitForTimeout(settleMs);
      return true;
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
  for (const block of [collapsedRowText, expandedFullText]) {
    const lines = String(block || "")
      .split(/\r?\n/)
      .map((l) => l.trim().replace(/\t+/g, " "))
      .filter((l) => l.length > 2);
    for (const line of lines) {
      if (PORTAL_TICKET_DATE_LINE_RE.test(line)) return line;
    }
  }
  return (
    String(collapsedRowText || "")
      .split(/\r?\n/)
      .map((l) => l.trim().replace(/\t+/g, " "))
      .find((l) => l.length > 0) || ""
  );
}

/**
 * Rinse often puts the date in one <td> and name/weight/# HD on the next lines. Using only the
 * date line makes every ticket on the same calendar day share one fingerprint → scrape stops after 1.
 */
function buildPortalRowSummary(collapsedRowText, expandedFullText) {
  for (const block of [collapsedRowText, expandedFullText]) {
    const lines = String(block || "")
      .split(/\r?\n/)
      .map((l) => l.trim().replace(/\t+/g, " "))
      .filter((l) => l.length > 1);
    const idx = lines.findIndex((l) => PORTAL_TICKET_DATE_LINE_RE.test(l));
    if (idx >= 0) {
      return lines
        .slice(idx, Math.min(idx + 12, lines.length))
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
    }
  }
  return "";
}

/**
 * Same row as one space-joined blob (many portals put date/name/lbs/#HD in one innerText line).
 */
function parsePortalListRowFlat(blob) {
  const flat = String(blob || "").replace(/\s+/g, " ").trim();
  const dm0 = flat.match(
    /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)\b/i,
  );
  if (!dm0) return null;
  const dateDisplay = `${dm0[1]} ${dm0[2]}`;
  let after = flat.slice(dm0.index + dm0[0].length).trim();
  after = after.replace(/\b(TODAY|RUSH|NON-?\s*RUSH|⚡)\b/gi, " ").replace(/\s+/g, " ").trim();
  const lbsRe = /(\?\?\s*LBS|\d+(?:\.\d+)?\s*LBS)\b/i;
  const lm = after.match(lbsRe);
  if (!lm) return null;
  const custRaw = after.slice(0, lm.index).trim();
  const customer_name = cleanPortalCustomerName(custRaw);
  const lbsTok = lm[1].replace(/\s+/g, " ").toUpperCase();
  const weight_display = /\?\?/i.test(lbsTok) ? "?? LBS" : lbsTok;
  const wn = lbsTok.match(/(\d+(?:\.\d+)?)/);
  const wf_lbs = wn && !/\?\?/i.test(lbsTok) ? wn[1] : "";
  const tail = after.slice(lm.index + lm[0].length).trim();
  let hd_count = "";
  const hdM = tail.match(/^(\d{1,3})\b/);
  if (hdM) hd_count = hdM[1];
  if (!dateDisplay || !customer_name) return null;
  return { dateDisplay, customer_name, weight_display, wf_lbs, hd_count };
}

/**
 * Cleaner-ticket list row: 1st cell block = date, 2nd = customer, 3rd = LBS (?? or n.n LBS),
 * 4th = # HD (1–3 digits) **when that column exists** on the page; if there is no # HD column,
 * the 4th line is often special instructions (text) → hd_count stays empty.
 */
function parsePortalListRowOrdered(collapsedRowText) {
  const lines = String(collapsedRowText || "")
    .split(/\r?\n/)
    .map((l) => l.trim().replace(/\t+/g, " "))
    .filter((l) => l.length > 0);
  if (!lines.length) return null;
  const d = lines.findIndex((l) => PORTAL_TICKET_DATE_LINE_RE.test(l));
  if (d < 0) return null;

  const dateLine = lines[d];
  const dm = dateLine.match(
    /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)\b/i,
  );
  const dateDisplay = dm ? `${dm[1]} ${dm[2]}` : "";
  const nameLine = (lines[d + 1] || "").trim();
  const lbsLine = (lines[d + 2] || "").trim();
  const fourth = (lines[d + 3] || "").trim();
  let hd_count = "";
  if (fourth && /^\d{1,3}$/.test(fourth)) {
    hd_count = fourth;
  }
  let weight_display = "?? LBS";
  const L = lbsLine;
  if (/\?\?\s*LBS/i.test(L)) {
    weight_display = "?? LBS";
  } else {
    const wm = L.match(/(\d+(?:\.\d+)?)\s*LBS/i);
    if (wm) weight_display = `${wm[1]} LBS`.replace(/\s+/g, " ").toUpperCase();
    else if (/LBS/i.test(L)) weight_display = L.replace(/\s+/g, " ").toUpperCase();
  }
  let wf_lbs = "";
  const wn = L.match(/(\d+\.\d+)/);
  if (wn) wf_lbs = wn[1];
  const customer_name = cleanPortalCustomerName(nameLine);

  const fromFlat = () => parsePortalListRowFlat(lines.slice(d).join("\n"));

  if (!dateDisplay) return fromFlat();
  if (!customer_name || customer_name.length < 2) {
    const f = fromFlat();
    if (f) return f;
    return null;
  }
  const lbsOk =
    L &&
    (/\?\?\s*LBS/i.test(L) || /\d+(?:\.\d+)?\s*LBS/i.test(L) || /\bLBS\b/i.test(L));
  if (!lbsOk) {
    const f = fromFlat();
    if (f) return f;
  }
  return {
    dateDisplay,
    customer_name,
    weight_display,
    wf_lbs,
    hd_count,
  };
}

function parseBagLineDecorationsFromCombined(combined) {
  const m = String(combined || "").match(/Bag:\s*([^\n]+)/i);
  if (!m) return { bag_service: "", bag_subservice: "" };
  const rest = m[1].trim().replace(/\s+/g, " ");
  const dm = rest.match(/^([A-Z0-9]{4,})\s*\(\s*([^)]*?)\s*\)\s*\(\s*([^)]*?)\s*\)/i);
  if (dm) return { bag_service: dm[2].trim(), bag_subservice: dm[3].trim() };
  const one = rest.match(/^([A-Z0-9]{4,})\s*\(\s*([^)]*?)\s*\)/i);
  if (one) return { bag_service: one[2].trim(), bag_subservice: "" };
  return { bag_service: "", bag_subservice: "" };
}

function cleanPortalCustomerName(name) {
  let s = String(name || "").trim();
  s = s.replace(/\b(TODAY|RUSH|NON-?\s*RUSH)\b/gi, " ");
  s = s.replace(/\b#?\s*HD\s*:?\s*\d+\b/gi, " ");
  s = s.replace(/\b#?\s*WF\s*(?:LBS|COUNT|ITEMS)\s*:?\s*[\d.]+\b/gi, " ");
  s = s.replace(/\b\d+\.?\d*\s*LBS\b/gi, " ");
  s = s.replace(/\buse\s+hypoallergenic\s+soap\b/gi, " ");
  s = s.replace(/\buse\s+fabric\s+softener\b/gi, " ");
  s = s.replace(/\buse\s+oxiclean\b/gi, " ");
  s = s.replace(/\s+/g, " ").trim();
  s = s.replace(/\s+0\s*$/i, "").trim();
  s = s.replace(/^\d+\s+/,"").trim();
  return s.slice(0, 200);
}

/**
 * Lines after the date **only from the list-row snapshot** (pre-expand).
 * Never walk expanded/vendor HTML — it contains labels like “Service Type”, “Description”, … that
 * look like names and break customer + fingerprints.
 */
function linesAfterPortalDateInListRow(collapsedRowText) {
  const lines = String(collapsedRowText || "")
    .split(/\r?\n/)
    .map((l) => l.trim().replace(/\t+/g, " "))
    .filter((l) => l.length > 0);
  const idx = lines.findIndex((l) => PORTAL_TICKET_DATE_LINE_RE.test(l));
  if (idx >= 0) return lines.slice(idx + 1);
  return [];
}

function pickCustomerFromPortalLines(lines) {
  for (const line of lines) {
    const L = String(line || "").trim();
    if (L.length < 2 || L.length > 88) continue;
    if (PORTAL_TICKET_DATE_LINE_RE.test(L)) continue;
    if (/^\?\?\s*LBS|^\d+\.?\d*\s*LBS$/i.test(L)) continue;
    if (/^#?\s*HD\b|^#\s*HD\b|^HD\s*:/i.test(L)) continue;
    if (/^#\s*WF\b|^WF\s*LBS/i.test(L)) continue;
    if (/^\d{1,4}$/.test(L)) continue;
    if (/^use\s+/i.test(L)) continue;
    if (
      /fabric\s+softener|oxiclean|hypoallergenic|unscented|low\s+dry|wash\s*&\s*fold|hang\s+dry|extra\s+scented|no\s+scent/i.test(
        L,
      )
    ) {
      continue;
    }
    if (/assembled|bagged|sent\s+to\s+vendor|processed\s+by|received\s+from|show\s+|hide\s+bag/i.test(L)) {
      continue;
    }
    if (
      /^(service\s*type|description|type|special\s*instructions|vendor\s*notes|vendor\s*price|vendor\b|add\s+new|save\b|processed\b)/i.test(
        L,
      )
    ) {
      continue;
    }
    if (/\bservice\s+type\b.*\bdescription\b/i.test(L)) continue;
    if (!/[a-zA-Z]{2,}/.test(L)) continue;
    const digits = (L.match(/\d/g) || []).length;
    if (digits / Math.max(L.length, 1) > 0.35) continue;
    if (L.split(/\s+/).length > 10) continue;
    return L;
  }
  return "";
}

/** Rinse often packs columns into <td>s; innerText on <tr> can omit the date line — stitch cells. */
async function readTicketRowTextSnapshot(rowLocator) {
  const fromCells = await rowLocator
    .evaluate((el) => {
      let tds = Array.from(el.querySelectorAll(":scope > td"));
      if (!tds.length) tds = Array.from(el.querySelectorAll(":scope > [role='gridcell']"));
      if (!tds.length) return (el.innerText || "").trim();
      const first = (tds[0].innerText || "").trim();
      if (tds.length > 1 && first.length <= 2 && !/\d{1,2}\/\d{1,2}/.test(first)) {
        tds = tds.slice(1);
      }
      const normLines = (s) => {
        if (!s) return "";
        return String(s)
          .replace(/\u00a0/g, " ")
          .replace(/\r\n/g, "\n")
          .split("\n")
          .map((line) => line.replace(/[ \t\f\v]+/g, " ").trim())
          .filter(Boolean)
          .join("\n");
      };
      const parts = [];
      for (const td of tds) {
        let chunk = normLines(td.innerText || "");
        if (td.querySelector("table")) {
          const c = td.cloneNode(true);
          c.querySelectorAll("table").forEach((t) => t.remove());
          const stripped = normLines(c.innerText || "");
          if (stripped.length) chunk = stripped;
        }
        if (chunk) parts.push(chunk);
      }
      return parts.join("\n");
    })
    .catch(() => "");

  const t1 = ((await rowLocator.innerText().catch(() => "")) || "").trim();
  const fc = (fromCells || "").trim();
  if (fc && PORTAL_TICKET_DATE_LINE_RE.test(fc)) return fc;
  if (t1 && PORTAL_TICKET_DATE_LINE_RE.test(t1)) return fc || t1;
  if (fc) return fc;
  return t1 || fc;
}

/** One string per direct list cell (`<td>` or `[role=gridcell]`), before expand. */
async function readTicketRowDirectCells(rowLocator) {
  const arr = await rowLocator
    .evaluate((el) => {
      let tds = Array.from(el.querySelectorAll(":scope > td"));
      if (!tds.length) tds = Array.from(el.querySelectorAll(":scope > [role='gridcell']"));
      if (tds.length > 1) {
        const first = (tds[0].innerText || "").trim();
        if (first.length <= 2 && !/\d{1,2}\/\d{1,2}/.test(first)) {
          tds = tds.slice(1);
        }
      }
      const normLines = (s) => {
        if (!s) return "";
        return String(s)
          .replace(/\u00a0/g, " ")
          .replace(/\r\n/g, "\n")
          .split("\n")
          .map((line) => line.replace(/[ \t\f\v]+/g, " ").trim())
          .filter(Boolean)
          .join("\n");
      };
      return tds.map((td) => normLines(td.innerText || td.textContent || ""));
    })
    .catch(() => []);
  return Array.isArray(arr) ? arr : [];
}

/**
 * List row as date + customer + weight + fourth column, from stitched row text.
 * Rinse may insert # WF LBS / # HD / other numbers *before* the `?? LBS` / `n.n LBS` line — fixed
 * [+1],[+2],[+3] indexing puts that number into the weight slot and hides LBS in the fourth slot.
 */
function rawFourFromStitchedText(text) {
  const lines = String(text || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((l) => l.replace(/[ \t\f\v]+/g, " ").trim())
    .filter(
      (l) =>
        l.length > 0 &&
        !/^show\s+(bag|issue|qc)/i.test(l) &&
        !/^hide\s+bag/i.test(l),
    );
  let start = lines.findIndex(
    (l) =>
      PORTAL_TICKET_DATE_LINE_RE.test(l) ||
      /\btoday\b/i.test(l) ||
      /\b\d{1,2}\/\d{1,2}\b/.test(l),
  );
  if (start < 0) {
    start = 0;
    if (lines[0] && lines[0].length <= 2 && !/\d/.test(lines[0])) start = 1;
  }
  const dateLine = lines[start] || "";
  const afterDate = lines.slice(start + 1);
  const looksLikeListWeight = (s) =>
    /\?\?\s*LBS|\d+(?:\.\d+)?\s*LBS|\bLBS\b/i.test(String(s || ""));
  const looksLikeHdDigits = (s) => /^\d{1,3}$/.test(String(s || "").trim());

  const wi = afterDate.findIndex((l) => looksLikeListWeight(l));
  if (wi < 0) {
    return [
      dateLine,
      afterDate[0] || "",
      afterDate[1] || "",
      afterDate[2] || "",
    ];
  }
  const weightLine = afterDate[wi].trim();
  const customerLine = afterDate.slice(0, wi).join(" ").trim();
  const afterWeight = afterDate.slice(wi + 1);
  let fourthLine = "";
  const di = afterWeight.findIndex((l) => looksLikeHdDigits(l));
  if (di >= 0) fourthLine = afterWeight[di].trim();
  else if (afterWeight.length) fourthLine = afterWeight[0].trim();

  return [dateLine, customerLine, weightLine, fourthLine];
}

/**
 * First four list columns as plain text (Estd / Customer / WF LBS / fourth). No guessing —
 * upload code can normalize dates, HD digits vs notes, etc.
 */
function splitPortalListRawFour(tdTexts) {
  const out = ["", "", "", ""];
  if (!Array.isArray(tdTexts) || tdTexts.length === 0) return out;
  const cells = tdTexts.map((x) =>
    String(x || "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim(),
  );
  if (cells.length >= 4) {
    return [cells[0], cells[1], cells[2], cells[3]];
  }
  const lines = [];
  for (const c of cells) {
    for (const line of c.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)) {
      if (/^show\s+(bag|issue|qc)/i.test(line) || /^hide\s+bag/i.test(line)) continue;
      lines.push(line.replace(/\s+/g, " ").trim());
    }
  }
  out[0] = lines[0] || "";
  out[1] = lines[1] || "";
  out[2] = lines[2] || "";
  out[3] = lines[3] || "";
  return out;
}

/** Row is a ticket list row if we have real cell text or the stitched snapshot looks like a ticket. */
function portalListRowPeekOk(tdTexts, trimmed) {
  const four = splitPortalListRawFour(tdTexts);
  if (four.filter((x) => String(x).trim().length > 0).length >= 2) return true;
  const fromLines = rawFourFromStitchedText(trimmed);
  if (fromLines.filter((x) => String(x).trim().length > 0).length >= 2) return true;
  const t = String(trimmed || "");
  if (PORTAL_TICKET_DATE_LINE_RE.test(t.slice(0, 900))) return true;
  if (/\btoday\b/i.test(t) && t.length > 8) return true;
  if (/\d{1,2}\/\d{1,2}/.test(t) && /\b(lbs|vendor|fold|wash|rinse)\b/i.test(t)) return true;
  return false;
}

/** Bag line: first/second `(...)` after bag code → service type & sub-service (Rinse `Bag:` row). */
function parseBagLineRawParts(combined) {
  const empty = {
    bag_service: "",
    bag_subservice: "",
    service_type: "",
    sub_service: "",
  };
  const src = String(combined || "").trim();
  if (!src) return empty;
  const m = src.match(/Bag:\s*([^\n]+)/i);
  const rest = (m ? m[1] : src).trim().replace(/\s+/g, " ");
  if (!rest) return empty;
  const idm = rest.match(/^([A-Za-z0-9]{4,})\b\s*/);
  if (!idm) return empty;
  const afterId = rest.slice(idm[0].length).trim();
  const paren = [];
  let s = afterId;
  for (let k = 0; k < 4 && s.length; k++) {
    const open = s.indexOf("(");
    if (open < 0) break;
    let depth = 0;
    let i = open;
    for (; i < s.length; i++) {
      if (s[i] === "(") depth++;
      else if (s[i] === ")") {
        depth--;
        if (depth === 0) {
          paren.push(s.slice(open + 1, i).trim());
          s = s.slice(i + 1).trim();
          break;
        }
      }
    }
    if (depth !== 0) break;
  }
  /** First paren = service type (e.g. Hang Dry vs Wash & Fold). Second paren = WF-style add-on (e.g. Rush), not HD. */
  const st = paren[0] || "";
  const sub = paren[1] || "";
  return {
    bag_service: st || afterId || "",
    bag_subservice: sub,
    service_type: st,
    sub_service: sub,
  };
}

/**
 * # HD is only meaningful for Hang Dry bags (list may omit the # HD column entirely on some pages).
 * Never take WF COUNT or other integers as # HD. Use explicit `# HD: n` in expanded text, else
 * a 1–3 digit fourth list column only when service is Hang Dry; otherwise `NA`.
 */
function finalizePortalHd({ rawFourth, combined, serviceType }) {
  const bagm = combined.match(/Bag:\s*[^\n]+/i);
  const bagLine = bagm ? bagm[0] : "";
  const hangRe = /\bhang[\s-]*dry\b/i;
  /** Sub-Service paren is WF-oriented; HD comes from service type or the literal `Bag:` line only. */
  const hang = hangRe.test(String(serviceType || "")) || hangRe.test(bagLine);
  if (!hang) return "NA";
  const labeled = combined.match(/#\s*HD\s*:?\s*(\d+)\b/i);
  if (labeled) return labeled[1];
  const fourth = String(rawFourth || "").trim();
  if (/^\d{1,3}$/.test(fourth)) return fourth;
  return "NA";
}

/** Portal CSV: first four `<td>`s (or first four logical lines) go out raw; bag parens raw. */
function parsePortalFields(collapsedRowText, expandedFullText, directCellTexts = null, bagDisplay = "") {
  let combined = `${String(collapsedRowText || "").trim()}\n${String(expandedFullText || "").trim()}`.trim();
  if (!/Bag:\s*[^\n]+/i.test(combined) && String(bagDisplay || "").trim()) {
    combined = `${combined}\nBag: ${String(bagDisplay).trim()}`.trim();
  }
  const cellFour = splitPortalListRawFour(Array.isArray(directCellTexts) ? directCellTexts : []);
  const lineFour = rawFourFromStitchedText(collapsedRowText);
  /** Prefer stitched lines first (they anchor on the date row); cells only fill gaps. */
  const rawFour = [0, 1, 2, 3].map(
    (i) => (lineFour[i] || "").trim() || (cellFour[i] || "").trim(),
  );
  let date_display = rawFour[0].trim();
  let customer_name = rawFour[1].trim();
  let weight_display = rawFour[2].trim();
  const fourthListRaw = rawFour[3].trim();
  /** Stray `# WF` / count cells without `LBS` are not weight — let expanded text fill. */
  if (
    weight_display &&
    !/\?\?\s*LBS/i.test(weight_display) &&
    !/\d+(?:\.\d+)?\s*LBS/i.test(weight_display) &&
    /^\d{1,4}$/.test(weight_display)
  ) {
    weight_display = "";
  }

  const collapsedLines = String(collapsedRowText || "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  if (!date_display && collapsedLines[0]) date_display = collapsedLines[0];
  if (!customer_name && collapsedLines[1]) customer_name = collapsedLines[1];
  if (!weight_display && collapsedLines[2]) weight_display = collapsedLines[2];

  const dateRe =
    /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)\b/i;
  if (!date_display) {
    const dm = combined.match(dateRe);
    if (dm) date_display = `${dm[1]} ${dm[2]}`;
  }

  if (!customer_name) {
    customer_name = pickCustomerFromPortalLines(
      linesAfterPortalDateInListRow(collapsedRowText),
    );
  }
  if (!customer_name) {
    customer_name = pickCustomerFromPortalLines(collapsedLines);
  }
  customer_name = customer_name.replace(/\s+/g, " ").trim();

  if (!weight_display) {
    const wfW = combined.match(/#\s*WF\s*LBS\s*:?\s*(\d+\.?\d*)\b/i);
    if (wfW) weight_display = `${wfW[1]} LBS`;
  }
  if (!weight_display) {
    const wm = combined.match(/(\d+(?:\.\d+)?)\s*(?:lbs|lb)\b/i);
    if (wm) weight_display = wm[0].replace(/\s+/g, " ").toUpperCase();
  }

  let wf_lbs = "";
  const wdec = weight_display.match(/(\d+\.\d+)/);
  if (wdec) wf_lbs = wdec[1];
  const wfLbsM =
    combined.match(/#\s*WF\s*LBS\s*:?\s*(\d+\.?\d*)\b/i) ||
    combined.match(/\bWF\s*LBS\s*:?\s*(\d+\.?\d*)\b/i);
  if (!wf_lbs && wfLbsM) wf_lbs = wfLbsM[1];

  const t = combined;
  const tl = t.toLowerCase();
  const flags = {
    USE_OXIC: /oxic|oxi\s*clean/i.test(t) ? "X" : "",
    Use_Hypo: /hypoallergenic|\bhypo\b/i.test(t) && !/hypochlor/i.test(tl) ? "X" : "",
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

  let notes = "";
  if (portalNotesMode() === "full") {
    const noteLines = t
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l.length > 1 && !skipLine(l) && !/^\d+$/.test(l));
    notes = noteLines
      .filter((l) => /use |dry|scen|hypo|fab|oxic|wash|fold|hang/i.test(l) || l.length > 12)
      .slice(0, 6)
      .join("; ");
    if (!notes) notes = noteLines.slice(0, 3).join("; ");
    notes = notes.slice(0, 500);
  }

  let estd_delivery = date_display;
  const em =
    combined.match(/\bEstd\.?\s*Del(?:ivery)?\s*:?\s*([^\n]+)/i) ||
    combined.match(/\bEst\.?\s*(?:imated)?\s*Del(?:ivery)?\s*:?\s*([^\n]+)/i);
  if (em) {
    estd_delivery = em[1].trim().replace(/\s+/g, " ").slice(0, 120);
  }

  if (!wf_lbs && weight_display) {
    const wnx = String(weight_display).match(/(\d+\.\d+)/);
    if (wnx) wf_lbs = wnx[1];
  }

  const bagParts = parseBagLineRawParts(combined);
  const hd_count = finalizePortalHd({
    rawFourth: fourthListRaw || (collapsedLines[3] || "").trim(),
    combined,
    serviceType: bagParts.service_type,
  });

  /** Shown on the portal only when the list page includes at least one Hang Dry–style order. */
  let wf_items = "";
  const wfItemsM =
    combined.match(/#\s*WF\s*ITEMS\s*:?\s*(\d+)\b/i) ||
    combined.match(/\bWF\s*ITEMS\s*:?\s*(\d+)\b/i);
  if (wfItemsM) wf_items = wfItemsM[1];

  return {
    date_display,
    estd_delivery,
    customer_name,
    weight_display,
    wf_lbs,
    hd_count,
    wf_items,
    notes_summary: notes,
    bag_service: bagParts.bag_service,
    bag_subservice: bagParts.bag_subservice,
    service_type: bagParts.service_type,
    sub_service: bagParts.sub_service,
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
    "# HD",
    "# WF ITEMS",
    "Weight",
    "Notes",
    "USE OXIC",
    "Use Hypo",
    "USE FAB",
    "Low DRY",
    "NO SCEN",
    "Extra Scen",
    "Service Type",
    "Sub-Service",
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
    portal.hd_count === undefined || portal.hd_count === null ? "" : String(portal.hd_count),
    portal.wf_items || "",
    portal.weight_display,
    portal.notes_summary,
    portal.USE_OXIC,
    portal.Use_Hypo,
    portal.USE_FAB,
    portal.Low_DRY,
    portal.NO_SCEN,
    portal.Extra_Scen,
    portal.service_type || portal.bag_service || "",
    portal.sub_service || portal.bag_subservice || "",
    bd,
  ];
}

async function expandRowAndReadBag(page, rowLocator, collapsedRowText) {
  await rowLocator.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(70);
  await ensureRowExpandedForTicket(rowLocator, page);
  const inlineSettle = Math.max(
    0,
    Math.min(5000, parseInt(process.env.RINSE_VENDORINLINE_SETTLE_MS || "120", 10) || 120),
  );
  if (inlineSettle > 0) await page.waitForTimeout(inlineSettle);

  let r = await readBagFromRowBlock(rowLocator);
  const skipShow =
    (process.env.RINSE_SKIP_SHOW_BAG_DETAILS || "").trim() === "1";

  if (!r.bagId && !skipShow) {
    const pollMs = Math.max(30, Math.min(200, parseInt(process.env.RINSE_BAG_DOM_POLL_MS || "60", 10) || 60));
    const maxDom = Math.max(
      0,
      Math.min(2500, parseInt(process.env.RINSE_BAG_DOM_WAIT_MS || "900", 10) || 900),
    );
    const tEnd = Date.now() + maxDom;
    while (!r.bagId && Date.now() < tEnd) {
      await page.waitForTimeout(pollMs);
      r = await readBagFromRowBlock(rowLocator);
    }
    const bagOk = await ensureShowBagDetailsForTicketRow(rowLocator);
    if (!bagOk) {
      const hint = (collapsedRowText || "").trim().replace(/\s+/g, " ").slice(0, 80);
      console.warn(
        `  Show bag details not found or not clickable for a ticket row${hint ? ` (${hint})` : ""} — ` +
          `Rinse may still be rendering the link, it may be off-screen under another expanded ticket, or the click was blocked. ` +
          `Not a geography issue. Try RINSE_SHOW_BAG_WAIT_MS=10000 RINSE_EXPAND_SETTLE_MS=900 on the API, or HEADED=1 locally.`,
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
    const ordCust = parsePortalListRowOrdered(String(collapsedRowText || ""))?.customer_name || "";
    const custStructured = pickCustomerFromPortalLines(
      linesAfterPortalDateInListRow(collapsedRowText),
    );
    r = {
      bagId: bagMatch.bagId || r2.bagId || r.bagId,
      bagDisplay: bagMatch.bagDisplay || r2.bagDisplay || r.bagDisplay,
      raw: bagMatch.raw || r2.raw || r.raw,
      customer: (ordCust || custStructured || custLine || r2.customer || r.customer || "").slice(0, 80),
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
  if (c0 && f0 && !PORTAL_TICKET_DATE_LINE_RE.test(f0)) {
    outR.fullText = `${c0}\n${f0}`.trim();
  } else if (c0 && !f0) {
    outR.fullText = c0;
  }
  return outR;
}

async function scrapePage(page, pageLabel, layout) {
  const sel = bodyRowsSelector();
  const tableWait = Math.max(250, Math.min(8000, parseInt(process.env.RINSE_TABLE_WAIT_MS || "450", 10) || 450));
  const tableAfter = Math.max(0, Math.min(5000, parseInt(process.env.RINSE_TABLE_AFTER_MS || "180", 10) || 180));
  await page.waitForTimeout(tableWait);
  await page.locator(sel).first().waitFor({ state: "visible", timeout: 25000 }).catch(() => {});
  await page.waitForTimeout(tableAfter);
  await page
    .evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight);
    })
    .catch(() => {});
  await page.waitForTimeout(350);
  await page
    .evaluate(() => {
      window.scrollTo(0, 0);
    })
    .catch(() => {});
  await page.waitForTimeout(200);
  const broadCount = await page.locator(sel).count();
  let rowsAll = ticketTableBodyRows(page);
  let ticketTableCount = await rowsAll.count();
  if (ticketTableCount === 0) {
    rowsAll = page.locator(sel);
    ticketTableCount = await rowsAll.count();
    console.warn(
      `Scoped ticket table matched 0 <tr>; falling back to broad selector (count=${ticketTableCount}). Set RINSE_TICKET_TABLE_SELECTOR to the tickets <table> from DevTools if needed.`,
    );
  }
  const initialRowCount = ticketTableCount;
  if (initialRowCount === 0) {
    console.warn("No rows matched row selectors — set RINSE_EXTRA_ROW_SELECTORS from DevTools or inspect page HTML.");
  } else {
    progressLine(`  Ticket table rows: ${initialRowCount} (broad locator count was ${broadCount}).`);
  }

  const wheelSteps = Math.max(
    0,
    Math.min(80, parseInt(process.env.RINSE_TABLE_WHEEL_STEPS || "7", 10) || 7),
  );
  for (let w = 0; w < wheelSteps; w++) {
    await page.mouse.wheel(0, 240);
    await page.waitForTimeout(22);
  }
  await page.evaluate(() => window.scrollTo(0, 0)).catch(() => {});
  await page.waitForTimeout(100);

  const out = [];
  let recordIndex = 0;
  /* # HD column is omitted when there are no hang-dry rows on the page — allow fewer <td>. */
  const minListTd = Math.max(2, Math.min(12, parseInt(process.env.RINSE_MIN_LIST_TD || "2", 10) || 2));

  /*
   * Expanding a ticket inserts a sibling <tr> for details, so tbody grows. A fixed `for (j < n)`
   * where `n` was snapshotted at the start stops early (e.g. 6 of 25). Re-read count each step.
   */
  let j = 0;
  while (true) {
    const rowCount = await rowsAll.count();
    if (j >= rowCount) break;

    const cand = rowsAll.nth(j);
    await cand.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    const rowGap = Math.max(0, Math.min(400, parseInt(process.env.RINSE_ROW_GAP_MS || "25", 10) || 25));
    await page.waitForTimeout(rowGap);
    const tdCount = await cand.locator("td").count().catch(() => 0);
    const thOnly =
      (await cand.locator("th").count().catch(() => 0)) > 0 && tdCount === 0;
    if (thOnly) {
      j += 1;
      continue;
    }

    const directTd = await cand.locator(":scope > td").count().catch(() => 0);
    const directGrid = await cand.locator(":scope > [role='gridcell']").count().catch(() => 0);
    const nListCells = Math.max(directTd, directGrid);
    if (nListCells < minListTd) {
      j += 1;
      continue;
    }

    const tdTexts = await readTicketRowDirectCells(cand);
    const rt = await readTicketRowTextSnapshot(cand);
    const trimmed = rt.trim();
    const fromTdsPeek = portalListRowPeekOk(tdTexts, trimmed);
    if (trimmed.length < 6 || /^(scans|rack|time scanned)/i.test(trimmed)) {
      j += 1;
      continue;
    }
    if (await isProbablySingleCellDetailRow(cand)) {
      j += 1;
      continue;
    }
    if (isLikelyExpandedDetailSubRow(trimmed)) {
      j += 1;
      continue;
    }
    if (!isMainListTicketRow(trimmed) && !fromTdsPeek) {
      j += 1;
      continue;
    }

    recordIndex += 1;
    /* Single progress line per ticket; rowCount can grow as expanded detail <tr> siblings are inserted. */
    const rowHint = `${j + 1}/${rowCount}`;
    const preview = trimmed.replace(/\s+/g, " ").slice(0, 72);
    const { bagId, bagDisplay, raw, customer, fullText, collapsed } = await expandRowAndReadBag(
      page,
      cand,
      rt,
    );

    const base = {
      page: pageLabel,
      row_index: recordIndex,
      customer_snippet: customer,
      bag_id: bagId,
      bag_display: bagDisplay || bagId,
      raw_line: raw,
    };
    let portal = null;
    if (layout === "portal") {
      portal = parsePortalFields(collapsed || rt, fullText, tdTexts, bagDisplay || bagId);
      out.push({ ...base, portal });
    } else {
      out.push(base);
    }

    const pn = (portal && portal.customer_name) || customer || "";
    const bits =
      layout === "portal" && portal
        ? ` | ${String(portal.date_display || "").slice(0, 32)} | svc:${String(portal.service_type || "").slice(0, 22)} | sub:${String(portal.sub_service || "").slice(0, 14)} | lbs:${String(portal.weight_display || "").slice(0, 18)} | #HD:${String(portal.hd_count ?? "").slice(0, 8)}`
        : "";
    if (bagId) {
      progressLine(
        `  ticket ${recordIndex} (list tr ${rowHint}): ${bagId}${pn ? ` — ${String(pn).slice(0, 48)}` : ""}${bits}`,
      );
    } else {
      progressLine(
        `  ticket ${recordIndex} (list tr ${rowHint}): ${preview}… — no bag id (row may need session or UI changed)`,
      );
    }

    await ensureRowCollapsedAfterTicket(cand, page);
    await page
      .evaluate(() => {
        window.scrollBy(0, Math.min(420, Math.floor(window.innerHeight * 0.4)));
      })
      .catch(() => {});

    j += 1;
  }

  if (initialRowCount > 0 && out.length > 0) {
    const tailCount = await rowsAll.count().catch(() => initialRowCount);
    progressLine(
      `  Scraped ${out.length} ticket row(s) (~${initialRowCount} list <tr> before run, ${tailCount} <tr> in tbody after).`,
    );
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
  console.error("[rinse-scrape] entering main() — Node", process.version);
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
  /* Cap only; we stop much earlier on empty table, duplicate fingerprint, or duplicate bag set. */
  const maxPages = Math.min(500, Math.max(1, parseInt(process.env.RINSE_MAX_PAGES || "500", 10) || 500));
  const pageSettleMs = Math.max(
    400,
    Math.min(30000, parseInt(process.env.RINSE_PAGE_SETTLE_MS || "1100", 10) || 1100),
  );
  const outCsv =
    (process.env.OUTPUT_CSV && String(process.env.OUTPUT_CSV).trim()) || defaultOutputPath();
  const outCsvAbsolute = path.resolve(outCsv);
  console.error("[rinse-scrape] OUTPUT_CSV (absolute):", outCsvAbsolute);
  const layout = csvLayout();
  if (layout === "portal") {
    progressLine(
      "CSV layout: portal (Excel-style columns + Bag ID). Set RINSE_CSV_LAYOUT=legacy for the compact debug CSV.",
    );
  }

  progressLine(
    "Launching Chromium (headless) — first process start can take 30–120s while the browser binary loads.",
  );
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
    /** Any earlier page’s table fingerprint — Rinse may repeat page 1 (or another page) after the real last page. */
    const seenRowFingerprints = new Set();
    /** Any earlier page’s sorted bag-id signature — same as fingerprint but keyed on exported IDs. */
    const seenBagSigs = new Set();

    function normFingerprint(s) {
      return String(s || "")
        .replace(/\s+/g, " ")
        .trim();
    }

    for (let p = pageStart; p < pageStart + maxPages; p++) {
      const url = urlForPage(baseUrl, p);
      progressLine(`\nPage ${p}: ${url}`);
      // "networkidle" often never settles on SPAs; domcontentloaded + fixed wait is more reliable on Azure.
      await page.goto(url, {
        waitUntil: "domcontentloaded",
        timeout: Math.max(navTimeoutMs(), 90000),
      });
      await page.waitForTimeout(pageSettleMs);
      await page
        .waitForSelector("table tbody tr", { timeout: 20000 })
        .catch(() => {});

      const landedPageNum = pageNumFromUrl(page.url());
      if (landedPageNum != null && landedPageNum !== p) {
        progressLine(
          `Stopping: requested page ${p} but landed on page ${landedPageNum} (pagination wrapped/redirected).`,
        );
        break;
      }

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
      if (nf.length > 24 && seenRowFingerprints.has(nf)) {
        progressLine(
          `Stopping: page ${p} matches an earlier page’s table (pagination wrapped or duplicate list — end of data).`,
        );
        break;
      }
      if (nf.length > 24) seenRowFingerprints.add(nf);

      if (p > pageStart && rows.length === 0) {
        progressLine(`Stopping: page ${p} had no extractable ticket rows after filtering.`);
        break;
      }

      const pageBagSig = [
        ...new Set(
          rows.map((r) => String(r.bag_id || "").trim().toUpperCase()).filter(Boolean),
        ),
      ]
        .sort()
        .join("\u241e");

      if (pageBagSig.length > 0 && seenBagSigs.has(pageBagSig)) {
        progressLine(
          `Stopping: page ${p} has the same bag ID set as an earlier page (no new tickets — end of pagination).`,
        );
        break;
      }
      if (pageBagSig.length > 0) seenBagSigs.add(pageBagSig);

      allRows.push(...rows);

      const withBag = rows.filter((r) => r.bag_id).length;
      if (withBag === 0 && rows.length > 3) {
        console.warn(
          "Many rows but no Bag IDs — selectors or expand control may be wrong; check one row in DevTools."
        );
      }
      const hasNextUi = await hasNextPageInUi(page, p);
      if (!hasNextUi) {
        progressLine(`Stopping: pagination UI shows no next page after page ${p}.`);
        break;
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

    const dir = path.dirname(outCsvAbsolute);
    if (dir && !fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(outCsvAbsolute, header + lines.join(""), "utf8");
    console.error("[rinse-scrape] wrote CSV:", outCsvAbsolute, `(${allRows.length} rows)`);
    progressLine(`\nWrote ${allRows.length} row records → ${outCsvAbsolute}`);
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
