/**
 * Standalone Vendor Home dashboard count scrape.
 * Writes JSON summary to OUTPUT_VENDOR_HOME_JSON or stdout.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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
        (val.startsWith('"') && val.endsWith('"'))
        || (val.startsWith("'") && val.endsWith("'"))
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
loadLocalEnvFile();

function navTimeoutMs() {
  return Math.max(
    5000,
    Math.min(120000, parseInt(process.env.RINSE_NAV_TIMEOUT_MS || "90000", 10) || 90000),
  );
}

function firstIntMatch(text, patterns) {
  for (const re of patterns) {
    const m = String(text || "").match(re);
    if (m && m[1] != null) {
      const n = parseInt(m[1], 10);
      if (!Number.isNaN(n)) return n;
    }
  }
  return null;
}

function resolveStorageStatePath() {
  const storageRel = process.env.RINSE_STORAGE_STATE?.trim();
  if (!storageRel) return "";
  const abs = path.isAbsolute(storageRel) ? storageRel : path.resolve(__dirname, storageRel);
  return fs.existsSync(abs) ? abs : "";
}

async function scrapeVendorHomeSummary(page) {
  const enabled = String(process.env.RINSE_SCRAPE_VENDOR_HOME || "1").trim() !== "0";
  if (!enabled) {
    return {
      source: "vendor_home_page",
      scraped_at: new Date().toISOString(),
      error: "RINSE_SCRAPE_VENDOR_HOME=0",
    };
  }
  const url = (process.env.RINSE_VENDOR_HOME_URL || "https://www.rinse.com/vendors/").trim();
  await page.goto(url, {
    waitUntil: "domcontentloaded",
    timeout: Math.max(navTimeoutMs(), 90000),
  });
  const waitMs = Math.max(
    400,
    Math.min(8000, parseInt(process.env.RINSE_VENDOR_HOME_WAIT_MS || "1500", 10) || 1500),
  );
  await page.waitForTimeout(waitMs);
  const text = await page.locator("body").innerText();
  const vendorAtPatterns = [
    /(\d+)\s+orders?\s+at\s+[A-Za-z][\w\s-]*(?!\s+yet)/i,
    /(\d+)\s*\n+\s*orders?\s+at\s+[A-Za-z][\w\s-]*(?!\s+yet)/i,
    /(\d+)\s+orders?\s+at\s+veewash(?!\s+yet)/i,
    /(\d+)\s+orders?\s+at\s+VeeWash(?!\s+yet)/i,
  ];
  const vendorYtpPatterns = [
    /(\d+)\s+orders?\s+at\s+[A-Za-z][\w\s-]*\s+yet\s+to\s+be\s+processed/i,
    /(\d+)\s*\n+\s*orders?\s+at\s+[A-Za-z][\w\s-]*\s+yet\s+to\s+be\s+processed/i,
    /(\d+)\s+orders?\s+at\s+veewash\s+yet\s+to\s+be\s+processed/i,
    /(\d+)\s+orders?\s+at\s+VeeWash\s+yet\s+to\s+be\s+processed/i,
  ];
  return {
    source: "vendor_home_page",
    scraped_at: new Date().toISOString(),
    orders_at_veewash: firstIntMatch(text, vendorAtPatterns),
    orders_at_veewash_yet_to_process: firstIntMatch(text, vendorYtpPatterns),
    due_today: firstIntMatch(text, [
      /(\d+)\s+orders?\s+due\s+today(?!\s+yet)/i,
      /(\d+)\s+due\s+today(?!\s+yet)/i,
    ]),
    due_today_yet_to_process: firstIntMatch(text, [
      /(\d+)\s+orders?\s+due\s+today\s+yet\s+to\s+be\s+processed/i,
      /(\d+)\s+due\s+today\s+yet\s+to\s+be\s+processed/i,
    ]),
  };
}

function writeSummaryOutput(summary) {
  const payload =
    summary && typeof summary === "object"
      ? summary
      : {
          source: "vendor_home_page",
          scraped_at: new Date().toISOString(),
          error: "Vendor Home scrape returned no summary",
        };
  const outPath = (process.env.OUTPUT_VENDOR_HOME_JSON || "").trim();
  const json = `${JSON.stringify(payload, null, 2)}\n`;
  if (outPath) {
    fs.writeFileSync(path.resolve(outPath), json, "utf8");
  } else {
    process.stdout.write(json);
  }
}

async function main() {
  const storageState = resolveStorageStatePath();
  let summary;
  const browser = await chromium.launch({
    headless: true,
    timeout: Math.max(30000, Math.min(180000, navTimeoutMs())),
    args: ["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox"],
  });
  try {
    const context = await browser.newContext(storageState ? { storageState } : {});
    const page = await context.newPage();
    try {
      summary = await scrapeVendorHomeSummary(page);
    } catch (err) {
      summary = {
        source: "vendor_home_page",
        scraped_at: new Date().toISOString(),
        error: String(err.message || err),
      };
    } finally {
      await context.close().catch(() => {});
    }
  } catch (err) {
    summary = {
      source: "vendor_home_page",
      scraped_at: new Date().toISOString(),
      error: String(err.message || err),
    };
  } finally {
    await browser.close().catch(() => {});
  }
  writeSummaryOutput(summary);
}

main().catch((err) => {
  writeSummaryOutput({
    source: "vendor_home_page",
    scraped_at: new Date().toISOString(),
    error: String(err.message || err),
  });
  process.exit(1);
});
