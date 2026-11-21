import { describe, expect, it } from "vitest";
import { reportKeyFromSearch, safePinIssuesPath } from "./pinIssuesDeepLink";

describe("pin issues notification deep link", () => {
  it("keeps an employee or rinse report key", () => {
    expect(reportKeyFromSearch("?report=employee:42")).toBe("employee:42");
    expect(reportKeyFromSearch("report=rinse:7")).toBe("rinse:7");
    expect(reportKeyFromSearch("?report=employee:0")).toBe("");
    expect(reportKeyFromSearch("?report=https://evil")).toBe("");
  });

  it("accepts only the issues screen", () => {
    expect(safePinIssuesPath("/pin-issues?report=employee:15")).toBe("/pin-issues?report=employee:15");
    expect(safePinIssuesPath(encodeURIComponent("/pin-issues?report=employee:15"))).toBe(
      "/pin-issues?report=employee:15",
    );
    expect(safePinIssuesPath("/pin-issues")).toBe("/pin-issues");
    expect(safePinIssuesPath("/management/lost-found")).toBe("");
    expect(safePinIssuesPath("//evil.example/pin-issues")).toBe("");
    expect(safePinIssuesPath("/pin-issues?report=employee:15&next=https://evil")).toBe("");
    expect(safePinIssuesPath("/pin-issues?foo=1&report=employee:15")).toBe("/pin-issues?report=employee:15");
  });
});
