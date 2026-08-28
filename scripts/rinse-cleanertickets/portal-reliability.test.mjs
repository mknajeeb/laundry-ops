/**
 * Unit tests for portal scrape reliability helpers (no live browser).
 * Run: node --test scripts/rinse-cleanertickets/portal-reliability.test.mjs
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  actionTimeoutMs,
  ticketOpTimeoutMs,
  withBoundedTimeout,
  runExclusivePageOp,
  isTransientBrowserError,
  buildDegradedPortalMetaFields,
  closeBrowserSafe,
} from "./rinse-playwright-lib.mjs";

describe("bounded timeouts", () => {
  it("action timeout is well below historical 120s nav default", () => {
    delete process.env.RINSE_ACTION_TIMEOUT_MS;
    assert.ok(actionTimeoutMs() <= 15000);
    assert.ok(actionTimeoutMs() >= 3000);
  });

  it("ticket op wall is bounded", () => {
    delete process.env.RINSE_TICKET_OP_TIMEOUT_MS;
    assert.ok(ticketOpTimeoutMs() <= 60000);
    assert.ok(ticketOpTimeoutMs() >= 8000);
  });

  it("withBoundedTimeout rejects stuck promise", async () => {
    const t0 = Date.now();
    await assert.rejects(
      () =>
        withBoundedTimeout(
          new Promise(() => {}),
          1000,
          "stuckDomRead",
        ),
      /stuckDomRead_timeout_1000ms/,
    );
    assert.ok(Date.now() - t0 < 2000);
  });
});

describe("transient browser errors", () => {
  it("classifies navigation/timeout/crash as transient", () => {
    assert.equal(isTransientBrowserError(new Error("Navigation timeout")), true);
    assert.equal(isTransientBrowserError(new Error("Target closed")), true);
    assert.equal(isTransientBrowserError(new Error("page crashed")), true);
    assert.equal(isTransientBrowserError(new Error("auth invalid")), false);
  });
});

describe("degraded meta", () => {
  it("marks skipped tickets as non-authoritative", () => {
    const m = buildDegradedPortalMetaFields({
      skippedTickets: [{ ticket_index: 1, reason: "expand_timeout" }],
      sourceCompleteNatural: true,
    });
    assert.equal(m.degraded, true);
    assert.equal(m.partial, true);
    assert.equal(m.skipped_ticket_count, 1);
    assert.equal(m.source_inspected_complete, false);
  });

  it("page nav failure is degraded", () => {
    const m = buildDegradedPortalMetaFields({
      pageNavFailed: true,
      sourceCompleteNatural: false,
    });
    assert.equal(m.degraded, true);
    assert.equal(m.page_navigation_failed, true);
    assert.equal(m.source_inspected_complete, false);
  });

  it("clean natural run is authoritative", () => {
    const m = buildDegradedPortalMetaFields({
      skippedTickets: [],
      pageNavFailed: false,
      sourceCompleteNatural: true,
    });
    assert.equal(m.degraded, false);
    assert.equal(m.source_inspected_complete, true);
  });
});

describe("exclusive page op cancellation", () => {
  it("closes page on timeout so underlying work cannot continue", async () => {
    let closed = false;
    const fakePage = {
      isClosed: () => closed,
      close: async () => {
        closed = true;
      },
    };
    const hung = new Promise(() => {}); // never settles
    await assert.rejects(
      () =>
        runExclusivePageOp(
          fakePage,
          () => hung,
          1000,
          "stuckExpand",
        ),
      /stuckExpand_timeout_1000ms/,
    );
    // allow microtask close to land
    await new Promise((r) => setTimeout(r, 20));
    assert.equal(closed, true);
  });
});

describe("browser close hang", () => {
  it("SIGKILLs when browser.close hangs", async () => {
    let killed = null;
    const fakeBrowser = {
      close: () => new Promise(() => {}),
      process: () => ({
        killed: false,
        kill(sig) {
          killed = sig;
        },
      }),
    };
    const prev = process.env.RINSE_ACTION_TIMEOUT_MS;
    process.env.RINSE_ACTION_TIMEOUT_MS = "3000";
    const t0 = Date.now();
    await closeBrowserSafe(fakeBrowser, "browser.close");
    process.env.RINSE_ACTION_TIMEOUT_MS = prev;
    assert.ok(Date.now() - t0 < 5000);
    assert.equal(killed, "SIGKILL");
  });
});
