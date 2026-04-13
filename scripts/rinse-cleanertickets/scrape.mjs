/**
 * Expand Rinse cleaner-ticket rows and extract "Bag: ABCD123456" style bag IDs.
 *
 * 1. Adjust SELECTORS below if your DOM differs (use DevTools on a row).
 * 2. Set RINSE_EMAIL / RINSE_PASSWORD and RINSE_TICKETS_URL in .env
 * 3. First run: HEADED=1 npm run scrape — complete any MFA/captcha, confirm login selectors.
 *
 * To reuse a logged-in session: log in once with HEADED=1, then in scrape temporarily
 * call await context.storageState({ path: 'rinse-auth.json' }) and set RINSE_STORAGE_STATE.
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
  /** Main ticket rows in the big table (not inner “Scans” tables) */
  bodyRows: "main table > tbody > tr, #content table > tbody > tr, .content table > tbody > tr, table.sortable > tbody > tr, article table > tbody > tr",
};

const BAG_RE = /Bag:\s*([A-Z0-9]+)\s*\(/i;

function csvEscape(s) {
  const t = String(s ?? "").replace(/"/g, '""');
  return `"${t}"`;
}

async function tryLogin(page) {
  const email = process.env.RINSE_EMAIL?.trim();
  const password = process.env.RINSE_PASSWORD?.trim();
  if (!email || !password) {
    console.warn("RINSE_EMAIL / RINSE_PASSWORD not set — expecting you to already be logged in or using RINSE_STORAGE_STATE.");
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

/** Rinse often injects detail rows or siblings below the header row — grab several following elements’ text. */
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
    console.warn("No rows matched SELECTORS.bodyRows — open DevTools, pick the tickets <table> tbody > tr, update scrape.mjs");
  }

  for (let i = 0; i < n; i++) {
    const row = rows.nth(i);
    if (!(await row.isVisible().catch(() => false))) continue;
    const rowText = (await row.innerText().catch(() => "")) || "";
    if (rowText.length < 8 || /^(scans|rack|time scanned)/i.test(rowText.trim())) {
      continue;
    }

    const { bagId, raw, customer } = await expandRowAndReadBag(page, row);
    out.push({ page: pageLabel, row_index: i + 1, customer_snippet: customer, bag_id: bagId, raw_line: raw });

    if (bagId) {
      console.log(`Row ${i + 1}: ${bagId}  (${customer.slice(0, 40)})`);
    } else {
      console.log(`Row ${i + 1}: (no Bag: match — check expanded HTML or SELECTORS.bodyRows)`);
    }
  }

  return out;
}

async function main() {
  const ticketsUrl =
    process.env.RINSE_TICKETS_URL?.trim() ||
    "https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1";
  const headed = process.env.HEADED === "1" || process.env.HEADED === "true";
  const storageState = process.env.RINSE_STORAGE_STATE?.trim();

  const browser = await chromium.launch({ headless: !headed, slowMo: headed ? 80 : 0 });
  const context = await browser.newContext(
    storageState && fs.existsSync(path.resolve(__dirname, storageState))
      ? { storageState: path.resolve(__dirname, storageState) }
      : {}
  );
  const page = await context.newPage();

  try {
    if (!storageState || !fs.existsSync(path.resolve(__dirname, storageState))) {
      await tryLogin(page);
    }

    await page.goto(ticketsUrl, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForTimeout(2000);

    const allRows = await scrapePage(page, ticketsUrl);

    const header = "page,row_index,customer_snippet,bag_id,raw_line\n";
    const lines = allRows.map(
      (r) =>
        [csvEscape(r.page), r.row_index, csvEscape(r.customer_snippet), csvEscape(r.bag_id), csvEscape(r.raw_line)].join(
          ","
        ) + "\n"
    );
    const outPath = path.join(__dirname, "bag-ids.csv");
    fs.writeFileSync(outPath, header + lines.join(""), "utf8");
    console.log(`\nWrote ${allRows.length} rows → ${outPath}`);
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
