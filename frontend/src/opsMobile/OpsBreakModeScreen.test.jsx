import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import OpsBreakModeScreen from "./OpsBreakModeScreen";

describe("OpsBreakModeScreen", () => {
  it("renders on-break identity, resume, and lock without other tiles", () => {
    const html = renderToStaticMarkup(
      <OpsBreakModeScreen
        employeeName="Maria Lopez"
        breakStartedAt="2026-08-20T13:18:00"
        localeTag="en-US"
        onResume={() => {}}
        onLock={() => {}}
        resumeLabel="Resume Work"
        lockLabel="Lock"
        title="On Break"
        startedLabel="Break started"
        elapsedPrefix="Break"
        lockHint="Lock for shared tablet"
      />,
    );
    expect(html).toContain("On Break");
    expect(html).toContain("Maria Lopez");
    expect(html).toContain("Resume Work");
    expect(html).toContain("Lock");
    expect(html).not.toContain("Team Status");
    expect(html).not.toContain("Revenue");
    expect(html).not.toContain("Clock Out");
  });
});
