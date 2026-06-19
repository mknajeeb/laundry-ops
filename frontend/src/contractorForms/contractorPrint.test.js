import { afterEach, describe, expect, it, vi } from "vitest";
import {
  absolutizePrintAssetUrls,
  buildPrintDocumentHtml,
  downloadPrintDocumentPdf,
} from "./contractorPrint";

describe("buildPrintDocumentHtml", () => {
  it("returns empty string when root element is missing", () => {
    expect(buildPrintDocumentHtml(null)).toBe("");
    expect(buildPrintDocumentHtml(undefined)).toBe("");
  });

  it("wraps element HTML in a standalone document without print script", () => {
    const root = { innerHTML: "<p class='sample'>Direct deposit</p>" };
    const html = buildPrintDocumentHtml(root, {
      pageSize: "letter portrait",
      title: "Direct Deposit Authorization",
    });
    expect(html).toContain("<!DOCTYPE html>");
    expect(html).toContain("Direct Deposit Authorization");
    expect(html).toContain("class='sample'");
    expect(html).toContain("size: letter portrait");
    expect(html).not.toContain("window.print");
  });

  it("absolutizes root-relative asset URLs for print iframes", () => {
    vi.stubGlobal("window", { location: { origin: "http://localhost" } });
    const root = { innerHTML: '<img src="/assets/veewash-logo.png" alt="" />' };
    const html = buildPrintDocumentHtml(root, { title: "Logo test" });
    expect(html).toContain('src="http://localhost/assets/veewash-logo.png"');
  });
});

describe("absolutizePrintAssetUrls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("leaves absolute URLs unchanged", () => {
    vi.stubGlobal("window", { location: { origin: "http://localhost" } });
    const html = '<img src="https://cdn.example.com/logo.png" />';
    expect(absolutizePrintAssetUrls(html)).toBe(html);
  });
});

describe("downloadPrintDocumentPdf", () => {
  it("returns false when root element is missing", async () => {
    await expect(downloadPrintDocumentPdf(null)).resolves.toBe(false);
  });
});
