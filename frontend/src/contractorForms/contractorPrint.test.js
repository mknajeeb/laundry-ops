import { describe, expect, it } from "vitest";
import { buildPrintDocumentHtml } from "./contractorPrint";

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
});
