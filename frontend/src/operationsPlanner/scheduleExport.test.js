import { describe, expect, it } from "vitest";
import { printDocumentHtml, scheduleCardSvg, scheduleCsv, schedulePdf } from "./scheduleExport";

describe("schedule export", () => {
  it("builds a standalone card without application chrome", () => {
    const svg = scheduleCardSvg({
      title: "Amina Cole",
      subtitle: "Week of Nov 9, 2026",
      rows: [{ name: "Monday", when: "8:00–4:00", role: "Fold", breaks: "12:00–12:30" }],
    });
    expect(svg).toContain("Amina Cole");
    expect(svg).toContain("Fold");
    expect(svg).not.toContain("sidebar");
    expect(svg).not.toContain("<button");
  });

  it("prints only the rows it is given", () => {
    const html = printDocumentHtml({
      title: "Breaks",
      subtitle: "Monday",
      sections: [{ heading: "Breaks", rows: [{ employee: "Amina Cole", when: "12:00", detail: "Timed" }] }],
    });
    expect(html).toContain("Amina Cole");
    expect(html).not.toContain("Other Person");
    expect(scheduleCsv([{ employee: "Amina Cole", day: "Monday", start: "08:00", end: "16:00", role: "fold", breaks: "", tasks: "" }])).toContain(
      "Amina Cole",
    );
    const pdf = schedulePdf({ title: "Schedule", subtitle: "Nov 9", rows: [{ employee: "Amina Cole", day: "Monday", start: "08:00", end: "16:00", role: "fold" }] });
    expect(pdf.startsWith("%PDF-1.4")).toBe(true);
    expect(pdf).toContain("Amina Cole");
    expect(pdf.trimEnd().endsWith("%%EOF")).toBe(true);
  });
});
