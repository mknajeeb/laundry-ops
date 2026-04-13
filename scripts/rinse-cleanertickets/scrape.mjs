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

async function clickExpandOnRow(rowLocator) {
  const firstCell = rowLocator.locator("td").first();
  const candidates = [
    firstCell.locator("button").first(),
    firstCell.locator("a").first(),
    firstCell.locator('[role="button"]').first(),
    rowLocator.locator("button").first(),
  ];
  for (const loc of candidates) {
    if (await loc.isVisible().catch(() => false)) {
      await loc.click({ timeout: 8000 });
      return true;
    }
  }
  return false;
}

/** Bag line is hidden until this link is clicked (Rinse cleaner tickets expanded row). */
async function clickShowBagDetailsInRow(rowLocator) {
  const page = rowLocator.page();
  const link = rowLocator.getByRole("link", { name: /show\s+bag\s+details/i }).first();
  if (await link.isVisible().catch(() => false)) {
    await link.click({ timeout: 8000 });
    await page.waitForTimeout(700);
    return true;
  }
  return false;
}

async function readBagFromRowBlock(rowLocator) {
  const text = await rowLocator
    .evaluate((el) => {
      const parts = [el.innerText || ""];
      let n = el.nextElementSibling;
      for (let i = 0; i < 8 && n; i++) {
        parts.push(n.innerText || "");
        n = n.nextElementSibling;
      }
      return parts.join("\n");
    })
    .catch(() => "");

  const { bagId, raw: bagRaw } = matchBagInText(text);
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

  return { bagId, raw: bagRaw, customer: customer.slice(0, 80), fullText: text };
}

/** Match the manual “copy from portal” Excel: date, customer, weight, notes, X-columns, bag id. */
function parsePortalFields(collapsedRowText, expandedFullText) {
  const combined = `${String(collapsedRowText || "").trim()}\n${String(expandedFullText || "").trim()}`.trim();
  const firstLine = (collapsedRowText || "").split(/\r?\n/).map((l) => l.trim()).find(Boolean) || "";

  let dateDisplay = "";
  const dm = firstLine.match(
    /\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}\/\d{1,2})\b/i
  );
  if (dm) {
    dateDisplay = `${dm[1]} ${dm[2]}`;
  }

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
    rest = rest.replace(/\?\?\s*LBS/gi, "").replace(/\d+(?:\.\d+)?\s*(?:lbs|lb)\b/gi, "").trim();
    customer = rest.replace(/\s+/g, " ").slice(0, 200);
  }
  if (!customer) {
    customer = (collapsedRowText || "").replace(/\s+/g, " ").trim().slice(0, 200);
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

  return {
    date_display: dateDisplay,
    customer_name: customer,
    weight_display: weight,
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
    "Customer",
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

function portalDataRow(portal, bagId) {
  return [
    portal.date_display,
    portal.customer_name,
    portal.weight_display,
    portal.notes_summary,
    portal.USE_OXIC,
    portal.Use_Hypo,
    portal.USE_FAB,
    portal.Low_DRY,
    portal.NO_SCEN,
    portal.Extra_Scen,
    bagId,
  ];
}

async function expandRowAndReadBag(page, rowLocator, collapsedRowText) {
  const clicked = await clickExpandOnRow(rowLocator);
  if (clicked) {
    await page.waitForTimeout(500);
    await clickShowBagDetailsInRow(rowLocator);
  }
  const r = await readBagFromRowBlock(rowLocator);
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
      return {
        bagId: fromCollapsed.bagId,
        raw: fromCollapsed.raw,
        customer: customer.slice(0, 80),
        fullText: r.fullText || collapsedRowText,
        collapsed: collapsedRowText,
      };
    }
  }
  return { ...r, collapsed: collapsedRowText };
}

async function scrapePage(page, pageLabel, layout) {
  const sel = bodyRowsSelector();
  const rows = page.locator(sel);
  await page.waitForTimeout(2000);
  await page.locator(sel).first().waitFor({ state: "visible", timeout: 25000 }).catch(() => {});
  await page.waitForTimeout(800);
  let n = await rows.count();
  if (n === 0) {
    console.warn("No rows matched row selectors — set RINSE_EXTRA_ROW_SELECTORS from DevTools or inspect page HTML.");
  }

  const out = [];

  for (let i = 0; i < n; i++) {
    const row = rows.nth(i);
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

    const { bagId, raw, customer, fullText, collapsed } = await expandRowAndReadBag(page, row, rowText);
    const base = {
      page: pageLabel,
      row_index: i + 1,
      customer_snippet: customer,
      bag_id: bagId,
      raw_line: raw,
    };
    if (layout === "portal") {
      const portal = parsePortalFields(collapsed || rowText, fullText);
      out.push({ ...base, portal });
    } else {
      out.push(base);
    }

    if (bagId) {
      console.log(`  row ${i + 1}: ${bagId}`);
    }
  }

  if (n > 0 && out.length === 0) {
    const previews = [];
    for (let j = 0; j < Math.min(3, n); j++) {
      const t = (await rows.nth(j).innerText().catch(() => "")) || "";
      previews.push(t.trim().replace(/\s+/g, " ").slice(0, 300));
    }
    console.warn(
      `Table matched ${n} row(s) but 0 became export rows (visibility, <th>-only header rows, short text filter, or expand failed). First rows (truncated):\n---\n${previews.join("\n---\n")}\n---\nTry HEADED=1 to watch the browser, refresh rinse-auth.json, or set RINSE_EXTRA_ROW_SELECTORS to the ticket <tr> from DevTools.`,
    );
  }

  return { rows: out, tableRowCount: n };
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
      await page.waitForTimeout(2500);
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
        portalDataRow(r.portal, r.bag_id)
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
