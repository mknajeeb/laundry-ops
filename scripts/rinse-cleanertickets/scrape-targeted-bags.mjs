#!/usr/bin/env node
/**
 * Targeted bag scan proof scrape — read-only export to stdout JSON.
 * Does NOT import to DB. Uses Rinse portal search (?q=BAGID) to find off-list tickets.
 *
 * Usage:
 *   RINSE_STORAGE_STATE=tenants/veewash/rinse-auth.json \
 *   node scrape-targeted-bags.mjs BAG1 BAG2 ...
 *   # or
 *   TARGET_BAG_IDS=bag1,bag2 node scrape-targeted-bags.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import {
  ticketTableBodyRows,
  readTicketRowTextSnapshot,
  readTicketRowDirectCells,
  portalListRowPeekOk,
  isProbablySingleCellDetailRow,
  isLikelyExpandedDetailSubRow,
  isMainListTicketRow,
  expandRowAndReadBag,
  ensureRowCollapsedAfterTicket,
} from "./scrape.mjs";
import {
  __rinseDir,
  loadLocalEnvFile,
  progressLine,
  navTimeoutMs,
  ticketIdFromBag,
  extractScansFromExpandedTicket,
  extractPrePostCleanWeightsFromExpandedTicket,
  assignAuthoritativeWeightsToScans,
  isLikelyLoginPage,
  tryLogin,
} from "./rinse-playwright-lib.mjs";

loadLocalEnvFile();

const __dir = path.dirname(fileURLToPath(import.meta.url));

function normalizeBagCode(raw) {
  return String(raw || "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function searchUrlForBag(bagId) {
  const q = encodeURIComponent(bagId);
  return `https://www.rinse.com/cleanertickets/?q=${q}&page=1`;
}

async function findBagOnPage(page, targetCode) {
  const rowsAll = ticketTableBodyRows(page);
  const rowCount = await rowsAll.count();
  for (let j = 0; j < rowCount; j += 1) {
    const cand = rowsAll.nth(j);
    await cand.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    const tdCount = await cand.locator("td").count().catch(() => 0);
    if (tdCount < 2) continue;
    const rt = await readTicketRowTextSnapshot(cand);
    const trimmed = rt.trim();
    if (trimmed.length < 6) continue;
    if (await isProbablySingleCellDetailRow(cand)) continue;
    if (isLikelyExpandedDetailSubRow(trimmed)) continue;
    const tdTexts = await readTicketRowDirectCells(cand);
    if (!isMainListTicketRow(trimmed) && !portalListRowPeekOk(tdTexts, trimmed)) continue;

    const { bagId, bagDisplay } = await expandRowAndReadBag(page, cand, rt);
    const code = normalizeBagCode(ticketIdFromBag(bagId, bagDisplay || bagId));
    const scansRaw = await extractScansFromExpandedTicket(cand);
    const cleanWeights = await extractPrePostCleanWeightsFromExpandedTicket(cand);
    const assigned = assignAuthoritativeWeightsToScans(scansRaw, cleanWeights);
    const scans = assigned.scans;
    await ensureRowCollapsedAfterTicket(page, cand).catch(() => {});
    if (code === targetCode || normalizeBagCode(bagDisplay).includes(targetCode)) {
      return {
        found: true,
        bag_id: code,
        bag_display: bagDisplay || bagId,
        row_preview: trimmed.slice(0, 120),
        pre_clean_weight_lbs: assigned.pre_lbs,
        post_weight_lbs: assigned.post_lbs,
        workitem_wf_lbs: assigned.workitem_wf_lbs,
        weight_capture: cleanWeights,
        scans: scans.map((ev, idx) => ({
          scan_index: idx + 1,
          rack: ev.rack || "",
          time_scanned: ev.time_scanned || "",
          user: ev.user || "",
          purpose: ev.purpose || "",
          last_location: ev.is_last_location ? "Y" : "",
          last_scan: ev.is_last_scan ? "Y" : "",
          weight: ev.weight != null ? ev.weight : "",
          weight_source: ev.weight_source || "",
          weight_role: ev.weight_role || "",
        })),
      };
    }
  }
  return { found: false, scans: [] };
}

async function scrapeBag(page, bagId) {
  const targetCode = normalizeBagCode(bagId);
  const url = searchUrlForBag(targetCode);
  progressLine(`[targeted] ${targetCode} → ${url}`);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: navTimeoutMs() });
  await page.waitForTimeout(800);
  if (await isLikelyLoginPage(page)) {
    const ok = await tryLogin(page);
    if (!ok) {
      return { bag_id: targetCode, error: "login_failed", portal_scan_count: 0, scans: [] };
    }
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: navTimeoutMs() });
    await page.waitForTimeout(800);
  }
  let hit = await findBagOnPage(page, targetCode);
  if (!hit.found) {
    // Retry without filters — all statuses
    const broad = `https://www.rinse.com/cleanertickets/?q=${encodeURIComponent(targetCode)}`;
    await page.goto(broad, { waitUntil: "domcontentloaded", timeout: navTimeoutMs() });
    await page.waitForTimeout(800);
    hit = await findBagOnPage(page, targetCode);
  }
  if (!hit.found) {
    return {
      bag_id: targetCode,
      found: false,
      lookup_method: "cleanertickets?q=",
      portal_scan_count: 0,
      scans: [],
      search_url: url,
    };
  }
  return {
    bag_id: targetCode,
    found: true,
    lookup_method: "cleanertickets?q=",
    bag_display: hit.bag_display,
    row_preview: hit.row_preview,
    portal_scan_count: hit.scans.length,
    pre_clean_weight_lbs: hit.pre_clean_weight_lbs,
    post_weight_lbs: hit.post_weight_lbs,
    workitem_wf_lbs: hit.workitem_wf_lbs,
    weight_capture: hit.weight_capture,
    scans: hit.scans,
    search_url: url,
  };
}

async function main() {
  const fromEnv = String(process.env.TARGET_BAG_IDS || "")
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const fromArgv = process.argv.slice(2).map((s) => s.trim()).filter(Boolean);
  const bagIds = [...new Set([...fromArgv, ...fromEnv].map(normalizeBagCode).filter(Boolean))];
  if (!bagIds.length) {
    console.error("Usage: node scrape-targeted-bags.mjs BAG1 BAG2 ...");
    process.exit(2);
  }

  const storageRel = process.env.RINSE_STORAGE_STATE?.trim() || "./rinse-auth.json";
  const storageState = fs.existsSync(path.resolve(__rinseDir, storageRel))
    ? path.resolve(__rinseDir, storageRel)
    : fs.existsSync(path.resolve(__dir, storageRel))
      ? path.resolve(__dir, storageRel)
      : "";

  const browser = await chromium.launch({
    headless: process.env.HEADED !== "1" && process.env.HEADED !== "true",
    timeout: Math.max(
      30000,
      Math.min(180000, parseInt(process.env.RINSE_NAV_TIMEOUT_MS || "120000", 10) || 120000),
    ),
  });
  const context = await browser.newContext(
    storageState ? { storageState } : {},
  );
  const page = await context.newPage();
  const results = [];
  try {
    for (const bid of bagIds) {
      try {
        results.push(await scrapeBag(page, bid));
      } catch (e) {
        results.push({
          bag_id: bid,
          found: false,
          error: String(e?.message || e),
          portal_scan_count: 0,
          scans: [],
        });
      }
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ bags: results }, null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
