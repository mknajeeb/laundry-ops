/**
 * Rinse cleaner-tickets — export per-ticket "Scans" event table (Rack, Time Scanned, User, Purpose).
 * Separate from production scrape.mjs (bag / portal CSV). Run locally; apply logic via Python after export.
 *
 * See README_SCAN_EVENTS.md
 */

import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";
import {
  __rinseDir,
  loadLocalEnvFile,
  progressLine,
  csvEscape,
  navTimeoutMs,
  urlForPage,
  pageNumFromUrl,
  defaultScanEventsOutputPath,
  bodyRowsSelector,
  ticketTableBodyRows,
  isLikelyExpandedDetailSubRow,
  isMainListTicketRow,
  portalListRowPeekOk,
  readTicketRowTextSnapshot,
  readTicketRowDirectCells,
  isProbablySingleCellDetailRow,
  ensureRowExpandedForTicket,
  ensureRowCollapsedAfterTicket,
  extractScansFromExpandedTicket,
  ticketContextFromCollapsedText,
  isLikelyLoginPage,
  tryLogin,
  hasNextPageInUi,
} from "./rinse-playwright-lib.mjs";

loadLocalEnvFile();
console.error("[rinse-scan-events] loaded — starting…");

const SCAN_EVENTS_HEADER = [
  "page",
  "ticket_row_index",
  "customer_snippet",
  "bag_id",
  "date_line",
  "scan_index",
  "rack",
  "time_scanned",
  "user",
  "purpose",
  "is_last_location",
  "is_last_scan",
].join(",");

async function scrapeScanEventsOnPage(page, pageLabel) {
  const sel = bodyRowsSelector();
  const tableWait = Math.max(250, Math.min(8000, parseInt(process.env.RINSE_TABLE_WAIT_MS || "450", 10) || 450));
  await page.waitForTimeout(tableWait);
  await page.locator(sel).first().waitFor({ state: "visible", timeout: 25000 }).catch(() => {});

  let rowsAll = ticketTableBodyRows(page);
  let ticketTableCount = await rowsAll.count();
  if (ticketTableCount === 0) {
    rowsAll = page.locator(sel);
    ticketTableCount = await rowsAll.count();
  }

  const out = [];
  let ticketIndex = 0;
  const minListTd = Math.max(2, Math.min(12, parseInt(process.env.RINSE_MIN_LIST_TD || "2", 10) || 2));

  let j = 0;
  while (true) {
    const rowCount = await rowsAll.count();
    if (j >= rowCount) break;

    const cand = rowsAll.nth(j);
    await cand.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(Math.max(0, parseInt(process.env.RINSE_ROW_GAP_MS || "25", 10) || 25));

    const tdCount = await cand.locator("td").count().catch(() => 0);
    if ((await cand.locator("th").count().catch(() => 0)) > 0 && tdCount === 0) {
      j += 1;
      continue;
    }
    const directTd = await cand.locator(":scope > td").count().catch(() => 0);
    if (directTd < minListTd) {
      j += 1;
      continue;
    }

    const tdTexts = await readTicketRowDirectCells(cand);
    const rt = await readTicketRowTextSnapshot(cand);
    const trimmed = rt.trim();
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
    if (!isMainListTicketRow(trimmed) && !portalListRowPeekOk(tdTexts, trimmed)) {
      j += 1;
      continue;
    }

    ticketIndex += 1;
    const ctx = ticketContextFromCollapsedText(trimmed);
    await ensureRowExpandedForTicket(cand, page);
    const scans = await extractScansFromExpandedTicket(cand);

    if (scans.length === 0) {
      progressLine(
        `  ticket ${ticketIndex} (tr ${j + 1}/${rowCount}): ${ctx.customer_snippet || trimmed.slice(0, 48)} — 0 scan rows`,
      );
      out.push({
        page: pageLabel,
        ticket_row_index: ticketIndex,
        customer_snippet: ctx.customer_snippet,
        bag_id: ctx.bag_id,
        date_line: ctx.date_line,
        scan_index: 0,
        rack: "",
        time_scanned: "",
        user: "",
        purpose: "",
        is_last_location: "",
        is_last_scan: "",
        _empty: true,
      });
    } else {
      scans.forEach((ev, idx) => {
        out.push({
          page: pageLabel,
          ticket_row_index: ticketIndex,
          customer_snippet: ctx.customer_snippet,
          bag_id: ctx.bag_id,
          date_line: ctx.date_line,
          scan_index: idx + 1,
          rack: ev.rack,
          time_scanned: ev.time_scanned,
          user: ev.user,
          purpose: ev.purpose,
          is_last_location: ev.is_last_location ? "Y" : "",
          is_last_scan: ev.is_last_scan ? "Y" : "",
        });
      });
      progressLine(
        `  ticket ${ticketIndex}: ${ctx.bag_id || "no-bag"} — ${scans.length} scan event(s) — ${ctx.customer_snippet || ""}`,
      );
    }

    await ensureRowCollapsedAfterTicket(cand, page);
    j += 1;
  }

  return { events: out, tableRowCount: ticketTableCount };
}

function rowToCsvLine(r) {
  return [
    csvEscape(r.page),
    r.ticket_row_index,
    csvEscape(r.customer_snippet),
    csvEscape(r.bag_id),
    csvEscape(r.date_line),
    r.scan_index,
    csvEscape(r.rack),
    csvEscape(r.time_scanned),
    csvEscape(r.user),
    csvEscape(r.purpose),
    csvEscape(r.is_last_location),
    csvEscape(r.is_last_scan),
  ].join(",");
}

async function main() {
  const baseUrl =
    process.env.RINSE_TICKETS_URL?.trim() ||
    "https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1";
  const headed = process.env.HEADED === "1" || process.env.HEADED === "true";
  const storageRel = process.env.RINSE_STORAGE_STATE?.trim();
  const storageState =
    storageRel && fs.existsSync(path.resolve(__rinseDir, storageRel))
      ? path.resolve(__rinseDir, storageRel)
      : "";

  const pageStart = Math.max(1, parseInt(process.env.RINSE_PAGE_START || "1", 10) || 1);
  const maxPages = Math.min(500, Math.max(1, parseInt(process.env.RINSE_MAX_PAGES || "500", 10) || 500));
  const pageSettleMs = Math.max(
    400,
    Math.min(30000, parseInt(process.env.RINSE_PAGE_SETTLE_MS || "1100", 10) || 1100),
  );
  const outCsv =
    (process.env.OUTPUT_SCAN_EVENTS_CSV && String(process.env.OUTPUT_SCAN_EVENTS_CSV).trim()) ||
    defaultScanEventsOutputPath();
  const outCsvAbsolute = path.resolve(outCsv);
  console.error("[rinse-scan-events] OUTPUT_SCAN_EVENTS_CSV (absolute):", outCsvAbsolute);

  const includeEmptyTickets =
    String(process.env.RINSE_SCAN_INCLUDE_EMPTY_TICKETS || "0").trim() === "1";

  progressLine("Launching Chromium for scan-events export…");
  const browser = await chromium.launch({
    headless: !headed,
    slowMo: headed ? 80 : 0,
    args: ["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox"],
  });
  const context = await browser.newContext(storageState ? { storageState } : {});
  const page = await context.newPage();
  const pwTimeout = navTimeoutMs();
  page.setDefaultTimeout(pwTimeout);
  page.setDefaultNavigationTimeout(pwTimeout);

  try {
    if (!storageState) {
      await tryLogin(page, baseUrl);
    }

    const allEvents = [];
    const seenFingerprints = new Set();

    for (let p = pageStart; p < pageStart + maxPages; p++) {
      const url = urlForPage(baseUrl, p);
      progressLine(`\nPage ${p}: ${url}`);
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: Math.max(pwTimeout, 90000) });
      await page.waitForTimeout(pageSettleMs);
      await page.waitForSelector("table tbody tr", { timeout: 20000 }).catch(() => {});

      const landed = pageNumFromUrl(page.url());
      if (landed != null && landed !== p) {
        progressLine(`Stopping: requested page ${p}, landed on ${landed}.`);
        break;
      }

      if (await isLikelyLoginPage(page)) {
        console.error("\nNot logged in — run npm run save-session and set RINSE_STORAGE_STATE.");
        await browser.close();
        process.exit(3);
      }

      const { events, tableRowCount } = await scrapeScanEventsOnPage(page, url);
      if (tableRowCount === 0) {
        progressLine(`Stopping: no table rows on page ${p}.`);
        break;
      }

      const fp = await page
        .evaluate(() => {
          const trs = Array.from(document.querySelectorAll("table tbody tr")).filter((tr) =>
            tr.querySelector("td"),
          );
          return trs
            .slice(0, 80)
            .map((tr) => (tr.innerText || "").trim().replace(/\s+/g, " ").slice(0, 120))
            .join("\u241e");
        })
        .catch(() => "");
      if (fp.length > 24 && seenFingerprints.has(fp)) {
        progressLine(`Stopping: page ${p} duplicates an earlier page.`);
        break;
      }
      if (fp.length > 24) seenFingerprints.add(fp);

      allEvents.push(...events);
      if (!(await hasNextPageInUi(page, p))) {
        progressLine(`Stopping: no next page after ${p}.`);
        break;
      }
    }

    const rows = includeEmptyTickets
      ? allEvents.filter((r) => !r._empty || r.scan_index === 0)
      : allEvents.filter((r) => !r._empty && r.scan_index > 0);

    if (rows.length === 0) {
      console.error("\nNo scan events exported. Expand a ticket in HEADED=1 and confirm the Scans table headers.");
      await browser.close();
      process.exit(2);
    }

    const dir = path.dirname(outCsvAbsolute);
    if (dir && !fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    const lines = rows.map((r) => rowToCsvLine(r) + "\n");
    fs.writeFileSync(outCsvAbsolute, SCAN_EVENTS_HEADER + "\n" + lines.join(""), "utf8");
    const ticketCount = new Set(rows.map((r) => `${r.page}\u241e${r.ticket_row_index}`)).size;
    console.error(
      `[rinse-scan-events] wrote ${rows.length} event row(s) for ${ticketCount} ticket(s) → ${outCsvAbsolute}`,
    );
    progressLine(`\nWrote ${rows.length} scan event row(s) → ${outCsvAbsolute}`);
    progressLine(
      "Next: python -m backend.rinse_scan_events_cli apply --csv " + outCsvAbsolute,
    );
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
