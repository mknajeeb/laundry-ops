/**
 * Expand Rinse cleaner-ticket rows and extract "Bag: ABCD123456" style bag IDs.
 * Supports multiple list pages (nightly export).
 *
 * See README.md for .env, save-session.mjs, and cron / Task Scheduler.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, ".env") });

/** ---- Tune if needed (DevTools on one ticket row) ---- */
const SELECTORS = {
  bodyRows:
    "main table > tbody > tr, #content table > tbody > tr, .content table > tbody > tr, table.sortable > tbody > tr, article table > tbody > tr",
};

const BAG_RE = /Bag:\s*([A-Z0-9]+)\s*\(/i;

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

async function tryLogin(page) {
  const email = process.env.RINSE_EMAIL?.trim();
  const password = process.env.RINSE_PASSWORD?.trim();
  if (!email || !password) {
    console.warn("RINSE_EMAIL / RINSE_PASSWORD not set — use RINSE_STORAGE_STATE=./rinse-auth.json after save-session.mjs");
    return;
  }

  await page.goto("https://www.rinse.com/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(800);

  const loginLink = page.getByRole("link", { name: /log\s*in|sign\s*in/i }).first();
  if (await loginLink.isVisible().catch(() => false)) {
    await loginLink.click();
  } else {
    await page.goto("https://www.rinse.com/login", { waitUntil: "domcontentloaded" }).catch(() => {});
  }

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

  await page.waitForTimeout(3000);
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

  const m = text.match(BAG_RE);
  const bagId = m ? m[1].toUpperCase() : "";
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

  return { bagId, raw: m ? m[0] : "", customer: customer.slice(0, 80) };
}

async function expandRowAndReadBag(page, rowLocator) {
  const clicked = await clickExpandOnRow(rowLocator);
  if (!clicked) {
    return { bagId: "", raw: "", customer: "" };
  }

  await page.waitForTimeout(500);
  return readBagFromRowBlock(rowLocator);
}

async function scrapePage(page, pageLabel) {
  const rows = page.locator(SELECTORS.bodyRows);
  await page.waitForTimeout(1500);
  const n = await rows.count();
  const out = [];

  if (n === 0) {
    console.warn("No rows matched SELECTORS.bodyRows — update scrape.mjs");
  }

  for (let i = 0; i < n; i++) {
    const row = rows.nth(i);
    if (!(await row.isVisible().catch(() => false))) continue;
    const rowText = (await row.innerText().catch(() => "")) || "";
    if (rowText.length < 8 || /^(scans|rack|time scanned)/i.test(rowText.trim())) {
      continue;
    }

    const { bagId, raw, customer } = await expandRowAndReadBag(page, row);
    out.push({
      page: pageLabel,
      row_index: i + 1,
      customer_snippet: customer,
      bag_id: bagId,
      raw_line: raw,
    });

    if (bagId) {
      console.log(`  row ${i + 1}: ${bagId}`);
    }
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
  const maxPages = Math.min(500, Math.max(1, parseInt(process.env.RINSE_MAX_PAGES || "50", 10) || 50));
  const outCsv =
    (process.env.OUTPUT_CSV && String(process.env.OUTPUT_CSV).trim()) || defaultOutputPath();

  const browser = await chromium.launch({ headless: !headed, slowMo: headed ? 80 : 0 });
  const context = await browser.newContext(storageState ? { storageState } : {});
  const page = await context.newPage();

  try {
    if (!storageState) {
      await tryLogin(page);
    }

    const allRows = [];

    for (let p = pageStart; p < pageStart + maxPages; p++) {
      const url = urlForPage(baseUrl, p);
      console.log(`\nPage ${p}: ${url}`);
      await page.goto(url, { waitUntil: "networkidle", timeout: 90000 });
      await page.waitForTimeout(2000);

      const { rows, tableRowCount } = await scrapePage(page, url);

      if (tableRowCount === 0) {
        console.log(`Stopping: no table rows on page ${p}.`);
        break;
      }

      allRows.push(...rows);

      const withBag = rows.filter((r) => r.bag_id).length;
      if (withBag === 0 && rows.length > 3) {
        console.warn(
          "Many rows but no Bag IDs — selectors or expand control may be wrong; check one row in DevTools."
        );
      }
    }

    const header = "page,row_index,customer_snippet,bag_id,raw_line\n";
    const lines = allRows.map(
      (r) =>
        [
          csvEscape(r.page),
          r.row_index,
          csvEscape(r.customer_snippet),
          csvEscape(r.bag_id),
          csvEscape(r.raw_line),
        ].join(",") + "\n"
    );

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
