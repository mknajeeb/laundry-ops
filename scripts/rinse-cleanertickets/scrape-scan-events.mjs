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
  detectSpecialInstructionsColumnIndex,
  readVisibleTableSpecialInstructions,
  normalizeCellMultilineText,
  buildPortalValidationMeta,
  statusFromTicketsUrl,
} from "./scrape.mjs";
import {
  __rinseDir,
  loadLocalEnvFile,
  progressLine,
  navTimeoutMs,
  actionTimeoutMs,
  ticketOpTimeoutMs,
  chromiumLaunchOptions,
  installLightPage,
  gotoWithRetry,
  recoverPageAfterStuckOp,
  buildDegradedPortalMetaFields,
  closeBrowserSafe,
  portalDiag,
  withBoundedTimeout,
  runExclusivePageOp,
  isPageClosedError,
  recreateLightPage,
  isTransientBrowserError,
  urlForPage,
  pageNumFromUrl,
  defaultScanEventsOutputPath,
  defaultScanTicketsOutputPath,
  ticketIdFromBag,
  extractScansFromExpandedTicket,
  extractPrePostCleanWeightsFromExpandedTicket,
  assignAuthoritativeWeightsToScans,
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
  "Weight",
  "Weight Source",
  "Weight Role",
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
    ev.weight != null && ev.weight !== "" ? String(ev.weight) : "",
    ev.weight_source ?? "",
    ev.weight_role ?? "",
  ];
}

/** Same ticket walk as production scrapePage — plus Scans table capture.
 * `session.page` may be replaced when a timed-out op closes the page (cancellation).
 */
async function scrapeScanEventsOnPage(session, { pageNum = null, pageUrl = "" } = {}) {
  let page = session.page;
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
  portalDiag({
    op: "page_start",
    page: pageNum,
    url: pageUrl,
    expected_rows: initialRowCount,
  });

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

  const siColumnIndex = await detectSpecialInstructionsColumnIndex(page);
  if (siColumnIndex >= 0) {
    progressLine(`  Special Instructions column: index ${siColumnIndex} (visible table)`);
  }

  const out = [];
  const skippedTickets = [];
  const capturedBagIds = new Set();
  let recordIndex = 0;
  const minListTd = Math.max(2, Math.min(12, parseInt(process.env.RINSE_MIN_LIST_TD || "2", 10) || 2));
  const maxRowIters = Math.max(
    initialRowCount * 4 + 40,
    Math.min(800, parseInt(process.env.RINSE_MAX_ROW_ITERS || "400", 10) || 400),
  );
  let j = 0;
  let iters = 0;
  let hardRecoveries = 0;

  async function recreateAfterClosed(reason) {
    portalDiag({ op: "recreate_after_closed", reason, page: pageNum });
    page = await recreateLightPage(session.context, pageUrl);
    session.page = page;
    hardRecoveries += 1;
    rowsAll = ticketTableBodyRows(page);
    if ((await rowsAll.count()) === 0) rowsAll = page.locator(sel);
  }

  while (iters < maxRowIters) {
    iters += 1;
    if (page.isClosed()) {
      if (hardRecoveries >= 3) break;
      await recreateAfterClosed("loop_page_closed");
      j += 1;
      continue;
    }
    const rowCount = await rowsAll.count();
    if (j >= rowCount) break;

    const cand = rowsAll.nth(j);
    await cand.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    const rowGap = Math.max(0, Math.min(400, parseInt(process.env.RINSE_ROW_GAP_MS || "25", 10) || 25));
    await page.waitForTimeout(rowGap);

    const tdCount = await cand.locator("td").count().catch(() => 0);
    const thOnly = (await cand.locator("th").count().catch(() => 0)) > 0 && tdCount === 0;
    if (thOnly) { j += 1; continue; }

    const directTd = await cand.locator(":scope > td").count().catch(() => 0);
    const directGrid = await cand.locator(":scope > [role='gridcell']").count().catch(() => 0);
    if (Math.max(directTd, directGrid) < minListTd) { j += 1; continue; }

    const tdTexts = await readTicketRowDirectCells(cand);
    const rt = await readTicketRowTextSnapshot(cand);
    const trimmed = rt.trim();
    const fromTdsPeek = portalListRowPeekOk(tdTexts, trimmed);
    if (trimmed.length < 6 || /^(scans|rack|time scanned)/i.test(trimmed)) { j += 1; continue; }
    if (await isProbablySingleCellDetailRow(cand)) { j += 1; continue; }
    if (isLikelyExpandedDetailSubRow(trimmed)) { j += 1; continue; }
    if (!isMainListTicketRow(trimmed) && !fromTdsPeek) { j += 1; continue; }

    recordIndex += 1;
    const rowHint = `${j + 1}/${rowCount}`;
    const preview = trimmed.replace(/\s+/g, " ").slice(0, 72);
    progressLine(`  ticket ${recordIndex} (tr ${rowHint}): expanding… ${preview}`);
    portalDiag({
      op: "expandRowAndReadBag",
      page: pageNum,
      ticket: recordIndex,
      tr: rowHint,
      action_timeout_ms: actionTimeoutMs(),
      ticket_op_timeout_ms: ticketOpTimeoutMs(),
    });

    let visibleTableSiRaw = "";
    if (siColumnIndex >= 0) {
      visibleTableSiRaw = await readVisibleTableSpecialInstructions(cand, siColumnIndex);
    }

    let bagId = "";
    let bagDisplay = "";
    let customer = "";
    let fullText = "";
    let collapsed = rt;
    let expandOk = false;
    let expandErrMsg = "";

    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        ({ bagId, bagDisplay, customer, fullText, collapsed } = await runExclusivePageOp(
          page,
          () => expandRowAndReadBag(page, cand, rt),
          ticketOpTimeoutMs(),
          "expandRowAndReadBag",
        ));
        expandOk = true;
        break;
      } catch (expandErr) {
        expandErrMsg = String(expandErr && expandErr.message ? expandErr.message : expandErr).slice(0, 160);
        portalDiag({
          op: "expandRowAndReadBag",
          error: expandErrMsg,
          ticket: recordIndex,
          tr: rowHint,
          attempt,
          page_closed: expandErr.pageClosed || isPageClosedError(expandErr) ? 1 : 0,
        });
        if (expandErr.pageClosed || isPageClosedError(expandErr) || page.isClosed()) {
          skippedTickets.push({
            page: pageNum, ticket_index: recordIndex, row_hint: rowHint, preview,
            reason: "expand_timeout_or_page_closed", error: expandErrMsg,
          });
          progressLine(`  ticket ${recordIndex} (tr ${rowHint}): SKIPPED (page closed/timeout) — recreating page…`);
          if (hardRecoveries >= 3) {
            return { tickets: out, tableRowCount: initialRowCount, skippedTickets };
          }
          await recreateAfterClosed("expand_timeout");
          break;
        }
        if (attempt < 2) {
          progressLine(`  ticket ${recordIndex} (tr ${rowHint}): expand failed attempt ${attempt} — retrying once…`);
          await page.waitForTimeout(200);
        }
      }
    }
    if (!expandOk) {
      if (!skippedTickets.some((s) => s.ticket_index === recordIndex)) {
        skippedTickets.push({
          page: pageNum, ticket_index: recordIndex, row_hint: rowHint, preview,
          reason: "expand_timeout", error: expandErrMsg,
        });
        progressLine(`  ticket ${recordIndex} (tr ${rowHint}): SKIPPED after expand failure — ${preview}…`);
      }
      j += 1;
      continue;
    }

    const bagKey = String(bagId || "").trim().toUpperCase();
    if (bagKey && capturedBagIds.has(bagKey)) { j += 1; continue; }
    if (bagKey) capturedBagIds.add(bagKey);

    const portal = parsePortalFields(collapsed || rt, fullText, tdTexts, bagDisplay || bagId, {
      visibleTableSi: visibleTableSiRaw,
    });

    let scansRaw = [];
    let cleanWeights = {};
    try {
      scansRaw = await runExclusivePageOp(
        page,
        () => extractScansFromExpandedTicket(cand),
        ticketOpTimeoutMs(),
        "extractScansFromExpandedTicket",
      );
      cleanWeights = await runExclusivePageOp(
        page,
        () => extractPrePostCleanWeightsFromExpandedTicket(cand),
        Math.min(20000, ticketOpTimeoutMs()),
        "extractPrePostCleanWeights",
      );
    } catch (scanErr) {
      if (scanErr.pageClosed || isPageClosedError(scanErr) || page.isClosed()) {
        skippedTickets.push({
          page: pageNum, ticket_index: recordIndex, row_hint: rowHint, preview, bag_id: bagId,
          reason: "scan_extract_page_closed",
          error: String(scanErr.message || scanErr).slice(0, 160),
        });
        if (hardRecoveries < 3) await recreateAfterClosed("scan_extract");
        j += 1;
        continue;
      }
      scansRaw = [];
      cleanWeights = {};
    }

    const assigned = assignAuthoritativeWeightsToScans(scansRaw, cleanWeights);
    const scans = assigned.scans;
    const bd = bagDisplay || bagId;
    const bagIdCode = ticketIdFromBag(bagId, bd);
    const pn = portal.customer_name || customer || "";
    const bits = ` | ${String(portal.date_display || "").slice(0, 32)} | svc:${String(portal.service_type || "").slice(0, 22)} | sub:${String(portal.sub_service || "").slice(0, 14)} | lbs:${String(portal.weight_display || "").slice(0, 18)} | #HD:${String(portal.hd_count ?? "").slice(0, 8)} | preclean:${assigned.pre_lbs ?? ""} | post:${assigned.post_lbs ?? ""}`;

    const ticketRec = {
      portal, bag_id: bagId, bag_display: bd, bag_id_code: bagIdCode,
      pre_clean_weight_lbs: assigned.pre_lbs, post_weight_lbs: assigned.post_lbs,
      workitem_wf_lbs: assigned.workitem_wf_lbs, weight_capture: cleanWeights,
    };

    if (scans.length === 0) {
      progressLine(`  ticket ${recordIndex} (tr ${rowHint}): ${bagIdCode || "no-bag"} — 0 scan rows — ${preview}…`);
      out.push({ ...ticketRec, events: [] });
    } else {
      const events = scans.map((ev, idx) => ({
        scan_index: idx + 1, rack: ev.rack, time_scanned: ev.time_scanned, user: ev.user,
        purpose: ev.purpose, is_last_location: ev.is_last_location ? "Y" : "",
        is_last_scan: ev.is_last_scan ? "Y" : "",
        weight: ev.weight != null ? ev.weight : "", weight_source: ev.weight_source || "",
        weight_role: ev.weight_role || "",
      }));
      out.push({ ...ticketRec, events });
      progressLine(
        bagIdCode
          ? `  ticket ${recordIndex} (tr ${rowHint}): ${bagIdCode}${pn ? ` — ${String(pn).slice(0, 48)}` : ""}${bits} — ${scans.length} scan event(s)`
          : `  ticket ${recordIndex} (tr ${rowHint}): ${preview}… — no bag id — ${scans.length} scan event(s)`,
      );
    }

    try {
      await ensureRowCollapsedAfterTicket(cand, page);
    } catch (collapseErr) {
      if (isPageClosedError(collapseErr) || page.isClosed()) {
        if (hardRecoveries < 3) await recreateAfterClosed("collapse");
        j += 1;
        continue;
      }
    }
    await page.evaluate(() => {
      window.scrollBy(0, Math.min(420, Math.floor(window.innerHeight * 0.4)));
    }).catch(() => {});
    j += 1;
  }

  if (iters >= maxRowIters) {
    portalDiag({ op: "scrapeScanEvents_row_loop", error: "max_row_iters", iters, max: maxRowIters });
    progressLine(`  Stopping ticket walk: hit RINSE_MAX_ROW_ITERS cap (${maxRowIters}) after ${out.length} ticket(s).`);
  }
  if (initialRowCount > 0 && out.length > 0) {
    const eventRows = out.reduce((n, t) => n + t.events.length, 0);
    progressLine(`  Captured ${out.length} ticket(s), ${eventRows} scan row(s) (${initialRowCount} list <tr> before).`);
  }
  portalDiag({
    op: "page_complete", page: pageNum, tickets: out.length,
    skipped: skippedTickets.length, expected_rows: initialRowCount,
  });
  return { tickets: out, tableRowCount: initialRowCount, skippedTickets };
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
  console.error(
    `[rinse-scan-events] effective_child_env RINSE_MAX_PAGES=${maxPages} RINSE_PAGE_START=${pageStart} RINSE_PORTAL_EARLY_STOP=${process.env.RINSE_PORTAL_EARLY_STOP || ""}`,
  );
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

  const allowBrowserRetry =
    String(process.env.RINSE_BROWSER_RETRY || "1").trim() !== "0";
  const maxAttempts = allowBrowserRetry ? 2 : 1;
  let lastErr = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    portalDiag({
      op: "scrape_attempt",
      attempt,
      max_attempts: maxAttempts,
      action_timeout_ms: actionTimeoutMs(),
      nav_timeout_ms: navTimeoutMs(),
      fresh_browser: 1,
    });
    if (attempt > 1) {
      progressLine(
        `Retry ${attempt - 1}/${maxAttempts - 1}: launching fresh Chromium after transient browser/nav failure.`,
      );
    }

    let browser = null;
    try {
      browser = await chromium.launch(chromiumLaunchOptions({ headed }));
      const context = await browser.newContext(storageState ? { storageState } : {});
      let page = await context.newPage();
      await installLightPage(page);
      const session = { browser, context, page };

      if (!storageState) {
        await tryLogin(page, baseUrl);
      }

      const allTickets = [];
      const allSkipped = [];
      const seenFingerprints = new Set();
      const seenBagSigs = new Set();
      let pagesScraped = 0;
      let stoppedReason = "no_next_page_ui";
      let reachedMaxPages = false;
      let lastPageUrl = baseUrl;
      let sessionAuthenticated = Boolean(storageState);
      let pageLoaded = false;
      let pageNavFailed = false;

      for (let p = pageStart; p < pageStart + maxPages; p++) {
        const url = urlForPage(baseUrl, p);
        console.error("[rinse-scan-events] page URL:", url);
        progressLine(`\nPage ${p}: ${url}`);
        try {
          await gotoWithRetry(page, url, { attempts: 2, label: "page.goto" });
        } catch (navErr) {
          pageNavFailed = true;
          portalDiag({
            op: "page.goto_exhausted",
            page: p,
            url,
            error: String(navErr && navErr.message ? navErr.message : navErr).slice(0, 160),
          });
          if (pagesScraped === 0) {
            throw navErr;
          }
          stoppedReason = "page_navigation_failed";
          progressLine(
            `Page ${p} navigation failed twice — stopping as partial (pages 1..${pagesScraped} kept; later pages not treated as absent).`,
          );
          break;
        }
        await page.waitForTimeout(pageSettleMs);
        await page.waitForSelector("table tbody tr", { timeout: 20000 }).catch(() => {});
        lastPageUrl = page.url();
        pageLoaded = true;
        pagesScraped += 1;
        progressLine(`[portal] page ${p} loaded — starting ticket walk`);

        const landed = pageNumFromUrl(page.url());
        if (landed != null && landed !== p) {
          progressLine(`Stopping: requested page ${p}, landed on ${landed}.`);
          stoppedReason = "pagination_redirect";
          break;
        }

        if (await isLikelyLoginPage(page)) {
          console.error("\nNot logged in — run npm run save-session and set RINSE_STORAGE_STATE.");
          sessionAuthenticated = false;
          await closeBrowserSafe(browser);
          browser = null;
          process.exit(3);
        }
        sessionAuthenticated = true;

        session.page = page;
        const { tickets, tableRowCount, skippedTickets } = await scrapeScanEventsOnPage(session, {
          pageNum: p,
          pageUrl: url,
        });
        page = session.page;
        if (skippedTickets && skippedTickets.length) {
          allSkipped.push(...skippedTickets);
        }
        if (tableRowCount === 0) {
          progressLine(`Stopping: no table rows on page ${p}.`);
          stoppedReason = "no_table_rows";
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
          stoppedReason = "duplicate_page_fingerprint";
          break;
        }
        if (fp.length > 24) seenFingerprints.add(fp);

        if (p > pageStart && tickets.length === 0) {
          progressLine(`Stopping: page ${p} had no extractable ticket rows after filtering.`);
          stoppedReason = "no_extractable_rows";
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
          stoppedReason = "duplicate_bag_set";
          break;
        }
        if (pageBagSig.length > 0) seenBagSigs.add(pageBagSig);

        allTickets.push(...tickets);

        // Freshness early-stop (same contract as scrape.mjs). Do not assume page 1 = delta.
        if (String(process.env.RINSE_PORTAL_EARLY_STOP || "") === "1") {
          if (!globalThis.__rinseEarlyStop) {
            let seed = {};
            try {
              const seedPath = String(process.env.RINSE_FINGERPRINT_SEED || "").trim();
              if (seedPath && fs.existsSync(seedPath)) {
                const raw = JSON.parse(fs.readFileSync(seedPath, "utf8"));
                seed = (raw && raw.fingerprints) || {};
              }
            } catch {
              seed = {};
            }
            globalThis.__rinseEarlyStop = {
              consecutiveUnchanged: 0,
              sourceInspectedComplete: false,
              seed,
            };
          }
          const early = globalThis.__rinseEarlyStop;
          const seed = early.seed || {};
          const unchangedNeed = Math.max(
            1,
            parseInt(process.env.RINSE_EARLY_STOP_UNCHANGED_PAGES || "2", 10) || 2,
          );
          let pageNewOrChanged = 0;
          for (const t of tickets) {
            const bid = String(t.bag_id || t.bag_id_code || "").trim().toUpperCase();
            if (!bid) {
              pageNewOrChanged += 1;
              continue;
            }
            const customer = String(t.customer || t.customer_name || "");
            const edd = String(t.edd || t.estimated_delivery || "");
            const lbs = String(t.lbs || t.weight || "");
            const service = String(t.service || "");
            const fpBag = `${bid}|${customer}|${edd}|${lbs}|${service}`.slice(0, 24);
            const known = seed[bid];
            if (!known || known !== fpBag) {
              pageNewOrChanged += 1;
              seed[bid] = fpBag;
            }
          }
          early.seed = seed;
          if (pageNewOrChanged === 0) {
            early.consecutiveUnchanged += 1;
          } else {
            early.consecutiveUnchanged = 0;
          }
          if (early.consecutiveUnchanged >= unchangedNeed) {
            progressLine(
              `Stopping: safe unchanged boundary after ${unchangedNeed} consecutive page(s) with no new/changed bag fingerprints.`,
            );
            stoppedReason = "safe_unchanged_boundary";
            early.sourceInspectedComplete = true;
            break;
          }
        }

        if (!(await hasNextPageInUi(page, p))) {
          progressLine(`Stopping: pagination UI shows no next page after ${p}.`);
          stoppedReason = "no_next_page_ui";
          break;
        }

        if (p === pageStart + maxPages - 1) {
          reachedMaxPages = true;
          stoppedReason = "max_pages_reached";
          progressLine(`Stopping: reached RINSE_MAX_PAGES limit (${maxPages}).`);
        }
      }

      if (allTickets.length === 0) {
        console.error("\nNo tickets extracted. Check auth / RINSE_TICKETS_URL / selectors.");
        await closeBrowserSafe(browser);
        browser = null;
        process.exit(2);
      }

      const dirE = path.dirname(eventsPath);
      if (dirE && !fs.existsSync(dirE)) fs.mkdirSync(dirE, { recursive: true });
      if (!eventsOnly) {
        const dirT = path.dirname(ticketsPath);
        if (dirT && !fs.existsSync(dirT)) fs.mkdirSync(dirT, { recursive: true });
      }

      let ticketCount = 0;
      if (!eventsOnly) {
        ticketCount = writeTicketsCsv(allTickets, ticketsPath);
        progressLine(`\nWrote ${ticketCount} ticket row(s) → ${ticketsPath}`);
      }
      const eventCount = writeEventsCsv(allTickets, eventsPath);
      if (eventCount === 0) {
        console.warn(
          eventsOnly
            ? "\nNo scan events exported. Use HEADED=1 and confirm tickets expand to show Scans table."
            : "\nNo scan events in events file; tickets file still written (matches production ticket export).",
        );
      }
      progressLine(`Wrote ${eventCount} scan event row(s) → ${eventsPath}`);

      if (!eventsOnly && ticketsPath) {
        const metaPath =
          (process.env.OUTPUT_PORTAL_SCRAPE_META && String(process.env.OUTPUT_PORTAL_SCRAPE_META).trim()) ||
          `${ticketsPath}.meta.json`;
        const portalScrapeMeta = {
          stopped_reason:
            allSkipped.length > 0 && stoppedReason === "no_next_page_ui"
              ? "completed_with_skipped_tickets"
              : stoppedReason,
          reached_max_pages: reachedMaxPages,
          pages_scraped: pagesScraped,
          max_pages_limit: maxPages,
          effective_child_max_pages: maxPages,
          page_start: pageStart,
          row_count: ticketCount,
          scraped_at: new Date().toISOString(),
          single_pass_source: "scan-events",
          early_stop_enabled: String(process.env.RINSE_PORTAL_EARLY_STOP || "") === "1",
          ...buildPortalValidationMeta({
            baseUrl,
            pageUrl: lastPageUrl,
            sessionAuthenticated,
            pageLoaded,
            emptyTableDetected: ticketCount === 0,
          }),
          ...buildDegradedPortalMetaFields({
            skippedTickets: allSkipped,
            pageNavFailed,
            sourceCompleteNatural:
              !reachedMaxPages &&
              !pageNavFailed &&
              (stoppedReason === "safe_unchanged_boundary" ||
                stoppedReason === "no_next_page_ui" ||
                stoppedReason === "duplicate_bag_set" ||
                stoppedReason === "duplicate_page_fingerprint" ||
                stoppedReason === "no_table_rows"),
          }),
        };
        if (reachedMaxPages || stoppedReason === "max_pages_reached") {
          portalScrapeMeta.source_inspected_complete = false;
          portalScrapeMeta.degraded = true;
          portalScrapeMeta.partial = true;
        }
        if (allSkipped.length > 0) {
          progressLine(
            `DEGRADED: skipped ${allSkipped.length} ticket(s) — not authoritative for Missing From Portal.`,
          );
        }
        fs.writeFileSync(metaPath, `${JSON.stringify(portalScrapeMeta, null, 2)}\n`, "utf8");
        console.error("[rinse-scan-events] wrote portal scrape meta:", metaPath);
        console.error("[rinse-scan-events] meta:", JSON.stringify(portalScrapeMeta));
      }

      if (!eventsOnly && ticketsPath) {
        console.error(`[rinse-scan-events] wrote ${ticketCount} ticket row(s) → ${ticketsPath}`);
      }
      console.error(`[rinse-scan-events] wrote ${eventCount} event row(s) → ${eventsPath}`);
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
      await closeBrowserSafe(browser);
      browser = null;
      return;
    } catch (err) {
      lastErr = err;
      portalDiag({
        op: "scrape_attempt_failed",
        attempt,
        error: String(err && err.message ? err.message : err).slice(0, 200),
        transient: isTransientBrowserError(err) ? 1 : 0,
      });
      await closeBrowserSafe(browser);
      browser = null;
      if (attempt < maxAttempts && isTransientBrowserError(err)) {
        progressLine(
          `Transient browser/navigation failure on attempt ${attempt}; restarting from a fresh browser.`,
        );
        continue;
      }
      throw err;
    } finally {
      if (browser) await closeBrowserSafe(browser);
    }
  }

  if (lastErr) throw lastErr;
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
