/**
 * Rinse cleaner-tickets — two CSVs:
 *   *-tickets.csv  — BYTE-FOR-BYTE same format as production scrape.mjs (RINSE_CSV_LAYOUT=portal)
 *   *-events.csv   — separate file: Bag ID + Scans columns only (not used by production import)
 *
 * Ticket rows use imported portalHeaderRow / portalDataRow / parsePortalFields from scrape.mjs.
 * See README_SCAN_EVENTS.md
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import {
  bodyRowsSelector,
  ticketTableBodyRows,
  readTicketRowTextSnapshot,
  readTicketRowDirectCells,
  portalListRowPeekOk,
  isProbablySingleCellDetailRow,
  isLikelyExpandedDetailSubRow,
  isMainListTicketRow,
  expandRowAndReadBag,
  ensureRowCollapsedAfterTicket,
  parsePortalFields,
  portalHeaderRow,
  portalDataRow,
  csvEscape,
} from "./scrape.mjs";
import {
  __rinseDir,
  loadLocalEnvFile,
  progressLine,
  navTimeoutMs,
  urlForPage,
  pageNumFromUrl,
  defaultScanEventsOutputPath,
  defaultScanTicketsOutputPath,
  ticketIdFromBag,
  extractScansFromExpandedTicket,
  isLikelyLoginPage,
  tryLogin,
  hasNextPageInUi,
} from "./rinse-playwright-lib.mjs";

loadLocalEnvFile();
console.error("[rinse-scan-events] loaded (split tickets + events CSVs)…");

const SCAN_EVENT_COLUMNS = [
  "Scan Index",
  "Rack",
  "Time Scanned",
  "User",
  "Purpose",
  "Last Location",
  "Last Scan",
];

const EVENTS_HEADER = ["Bag ID", ...SCAN_EVENT_COLUMNS];

function isEventsOnlyLayout() {
  const v = String(
    process.env.RINSE_SCAN_OUTPUT_LAYOUT || process.env.RINSE_SCAN_EVENTS_LAYOUT || "",
  )
    .trim()
    .toLowerCase();
  return v === "events_only" || v === "events-only";
}

function rowToCsvLine(values) {
  return values.map(csvEscape).join(",");
}

function eventDataRow(bagIdCode, event) {
  const ev = event || {};
  return [
    bagIdCode,
    ev.scan_index ?? "",
    ev.rack ?? "",
    ev.time_scanned ?? "",
    ev.user ?? "",
    ev.purpose ?? "",
    ev.is_last_location ?? "",
    ev.is_last_scan ?? "",
  ];
}

/** Same ticket walk as production scrapePage — plus Scans table capture. */
async function scrapeScanEventsOnPage(page) {
  const sel = bodyRowsSelector();
  const tableWait = Math.max(250, Math.min(8000, parseInt(process.env.RINSE_TABLE_WAIT_MS || "450", 10) || 450));
  const tableAfter = Math.max(0, Math.min(5000, parseInt(process.env.RINSE_TABLE_AFTER_MS || "180", 10) || 180));
  await page.waitForTimeout(tableWait);
  await page.locator(sel).first().waitFor({ state: "visible", timeout: 25000 }).catch(() => {});
  await page.waitForTimeout(tableAfter);

  let rowsAll = ticketTableBodyRows(page);
  let ticketTableCount = await rowsAll.count();
  if (ticketTableCount === 0) {
    rowsAll = page.locator(sel);
    ticketTableCount = await rowsAll.count();
    console.warn(
      `Scoped ticket table matched 0 <tr>; falling back to broad selector (count=${ticketTableCount}).`,
    );
  }
  const initialRowCount = ticketTableCount;
  if (initialRowCount > 0) {
    progressLine(`  Ticket table rows: ${initialRowCount}.`);
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
  const minListTd = Math.max(2, Math.min(12, parseInt(process.env.RINSE_MIN_LIST_TD || "2", 10) || 2));

  let j = 0;
  while (true) {
    const rowCount = await rowsAll.count();
    if (j >= rowCount) break;

    const cand = rowsAll.nth(j);
    await cand.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    const rowGap = Math.max(0, Math.min(400, parseInt(process.env.RINSE_ROW_GAP_MS || "25", 10) || 25));
    await page.waitForTimeout(rowGap);

    const tdCount = await cand.locator("td").count().catch(() => 0);
    const thOnly = (await cand.locator("th").count().catch(() => 0)) > 0 && tdCount === 0;
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
    const rowHint = `${j + 1}/${rowCount}`;
    const preview = trimmed.replace(/\s+/g, " ").slice(0, 72);

    const { bagId, bagDisplay, customer, fullText, collapsed } = await expandRowAndReadBag(
      page,
      cand,
      rt,
    );
    const portal = parsePortalFields(collapsed || rt, fullText, tdTexts, bagDisplay || bagId);
    const scans = await extractScansFromExpandedTicket(cand);
    const bd = bagDisplay || bagId;
    const bagIdCode = ticketIdFromBag(bagId, bd);

    const pn = portal.customer_name || customer || "";
    const bits = ` | ${String(portal.date_display || "").slice(0, 32)} | svc:${String(portal.service_type || "").slice(0, 22)} | sub:${String(portal.sub_service || "").slice(0, 14)} | lbs:${String(portal.weight_display || "").slice(0, 18)} | #HD:${String(portal.hd_count ?? "").slice(0, 8)}`;

    const ticketRec = { portal, bag_id: bagId, bag_display: bd, bag_id_code: bagIdCode };

    if (scans.length === 0) {
      progressLine(
        `  ticket ${recordIndex} (tr ${rowHint}): ${bagIdCode || "no-bag"} — 0 scan rows — ${preview}…`,
      );
      if (String(process.env.RINSE_SCAN_INCLUDE_EMPTY_TICKETS || "0").trim() === "1") {
        out.push({
          ...ticketRec,
          events: [
            {
              scan_index: "",
              rack: "",
              time_scanned: "",
              user: "",
              purpose: "",
              is_last_location: "",
              is_last_scan: "",
            },
          ],
        });
      } else {
        out.push({ ...ticketRec, events: [] });
      }
    } else {
      const events = scans.map((ev, idx) => ({
        scan_index: idx + 1,
        rack: ev.rack,
        time_scanned: ev.time_scanned,
        user: ev.user,
        purpose: ev.purpose,
        is_last_location: ev.is_last_location ? "Y" : "",
        is_last_scan: ev.is_last_scan ? "Y" : "",
      }));
      out.push({ ...ticketRec, events });
      if (bagIdCode) {
        progressLine(
          `  ticket ${recordIndex} (tr ${rowHint}): ${bagIdCode}${pn ? ` — ${String(pn).slice(0, 48)}` : ""}${bits} — ${scans.length} scan event(s)`,
        );
      } else {
        progressLine(
          `  ticket ${recordIndex} (tr ${rowHint}): ${preview}… — no bag id — ${scans.length} scan event(s)`,
        );
      }
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
    const eventRows = out.reduce((n, t) => n + t.events.length, 0);
    progressLine(
      `  Captured ${out.length} ticket(s), ${eventRows} scan row(s) (${initialRowCount} list <tr> before).`,
    );
  }

  return { tickets: out, tableRowCount: initialRowCount };
}

/** Same CSV lines as production scrape.mjs (portal layout, one row per scraped ticket, no dedupe). */
function writeTicketsCsv(ticketRecords, outPath) {
  if (ticketRecords.length === 0) return 0;
  const header = portalHeaderRow().map(csvEscape).join(",") + "\n";
  const lines = ticketRecords.map((t) =>
    rowToCsvLine(portalDataRow(t.portal, t.bag_display || t.bag_id)),
  );
  fs.writeFileSync(outPath, header + lines.map((l) => l + "\n").join(""), "utf8");
  return lines.length;
}

function writeEventsCsv(ticketRecords, outPath) {
  const lines = [];
  for (const t of ticketRecords) {
    if (!t.bag_id_code) continue;
    for (const ev of t.events) {
      if (!ev.scan_index && String(process.env.RINSE_SCAN_INCLUDE_EMPTY_TICKETS || "0").trim() !== "1") {
        continue;
      }
      lines.push(rowToCsvLine(eventDataRow(t.bag_id_code, ev)));
    }
  }
  if (lines.length === 0) return 0;
  const header = EVENTS_HEADER.map(csvEscape).join(",") + "\n";
  fs.writeFileSync(outPath, header + lines.map((l) => l + "\n").join(""), "utf8");
  return lines.length;
}

async function main() {
  console.error(
    "[rinse-scan-events] process.env.RINSE_TICKETS_URL:",
    process.env.RINSE_TICKETS_URL ?? "<unset>",
  );
  const baseUrl =
    process.env.RINSE_TICKETS_URL?.trim() ||
    "https://www.rinse.com/cleanertickets/?page=1";
  console.error("[rinse-scan-events] baseUrl:", baseUrl);
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

  const eventsOnly = isEventsOnlyLayout();
  const eventsPath = path.resolve(
    (process.env.OUTPUT_SCAN_EVENTS_CSV && String(process.env.OUTPUT_SCAN_EVENTS_CSV).trim()) ||
      (process.env.OUTPUT_CSV && String(process.env.OUTPUT_CSV).trim()) ||
      defaultScanEventsOutputPath(),
  );
  const ticketsPath = eventsOnly
    ? ""
    : path.resolve(
        (process.env.OUTPUT_SCAN_TICKETS_CSV && String(process.env.OUTPUT_SCAN_TICKETS_CSV).trim()) ||
          defaultScanTicketsOutputPath(),
      );

  if (eventsOnly) {
    console.error("[rinse-scan-events] events-only mode (Bag ID + scans)");
    console.error("[rinse-scan-events] events CSV:", eventsPath);
  } else {
    console.error("[rinse-scan-events] tickets CSV:", ticketsPath);
    console.error("[rinse-scan-events] events CSV:", eventsPath);
  }

  progressLine(
    eventsOnly
      ? "Launching Chromium (events-only CSV: Bag ID + scans)…"
      : "Launching Chromium (tickets file = production portal; events file = Bag ID + scans)…",
  );
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

    const allTickets = [];
    const seenFingerprints = new Set();
    const seenBagSigs = new Set();

    for (let p = pageStart; p < pageStart + maxPages; p++) {
      const url = urlForPage(baseUrl, p);
      console.error("[rinse-scan-events] page URL:", url);
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

      const { tickets, tableRowCount } = await scrapeScanEventsOnPage(page);
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
            .slice(0, 120)
            .map((tr) => (tr.innerText || "").trim().replace(/\s+/g, " ").slice(0, 140))
            .join("\u241e");
        })
        .catch(() => "");
      if (fp.length > 24 && seenFingerprints.has(fp)) {
        progressLine(`Stopping: page ${p} duplicates an earlier page.`);
        break;
      }
      if (fp.length > 24) seenFingerprints.add(fp);

      if (p > pageStart && tickets.length === 0) {
        progressLine(`Stopping: page ${p} had no extractable ticket rows after filtering.`);
        break;
      }

      const pageBagSig = [
        ...new Set(
          tickets.map((t) => String(t.bag_id || t.bag_id_code || "").trim().toUpperCase()).filter(Boolean),
        ),
      ]
        .sort()
        .join("\u241e");

      if (pageBagSig.length > 0 && seenBagSigs.has(pageBagSig)) {
        progressLine(
          `Stopping: page ${p} has the same bag ID set as an earlier page (no new tickets).`,
        );
        break;
      }
      if (pageBagSig.length > 0) seenBagSigs.add(pageBagSig);

      allTickets.push(...tickets);

      if (!(await hasNextPageInUi(page, p))) {
        progressLine(`Stopping: pagination UI shows no next page after ${p}.`);
        break;
      }
    }

    if (allTickets.length === 0) {
      console.error(
        "\nNo tickets exported. Use HEADED=1, confirm RINSE_TICKETS_URL, refresh rinse-auth.json.",
      );
      await browser.close();
      process.exit(2);
    }

    const dir = path.dirname(eventsPath);
    if (dir && !fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    let nTickets = 0;
    if (!eventsOnly && ticketsPath) {
      nTickets = writeTicketsCsv(allTickets, ticketsPath);
    }
    const nEvents = writeEventsCsv(allTickets, eventsPath);

    if (nEvents === 0) {
      console.warn(
        eventsOnly
          ? "\nNo scan events exported. Use HEADED=1 and confirm tickets expand to show Scans table."
          : "\nNo scan events in events file; tickets file still written (matches production ticket export).",
      );
    }

    if (!eventsOnly && ticketsPath) {
      console.error(`[rinse-scan-events] wrote ${nTickets} ticket row(s) → ${ticketsPath}`);
    }
    console.error(`[rinse-scan-events] wrote ${nEvents} event row(s) → ${eventsPath}`);
    if (!eventsOnly && ticketsPath) {
      progressLine(`\nTickets (production portal CSV): ${ticketsPath}`);
    }
    progressLine(`Events (Bag ID + scans only): ${eventsPath}`);
    if (!eventsOnly) {
      progressLine(
        "Join on Bag ID (alphanumeric code) in events ↔ ticket_id prefix in tickets Bag ID column.",
      );
    }
    if (eventsOnly) {
      console.log(eventsPath);
    }
  } finally {
    await browser.close();
  }
}

function isCliEntry() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry);
  } catch {
    return false;
  }
}

if (isCliEntry()) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
