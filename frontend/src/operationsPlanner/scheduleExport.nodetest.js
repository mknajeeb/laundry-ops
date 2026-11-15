import assert from "node:assert/strict";
import test from "node:test";
import { printDocumentHtml, scheduleCardSvg, scheduleCsv } from "./scheduleExport.js";

test("schedule card is a document, not application chrome", () => {
  const svg = scheduleCardSvg({
    title: "Amina Cole",
    subtitle: "Week of Nov 9, 2026",
    rows: [{ name: "Monday", when: "8:00–4:00", role: "Fold", breaks: "12:00–12:30" }],
  });
  assert.match(svg, /Amina Cole/);
  assert.match(svg, /Fold/);
  assert.equal(svg.includes("<button"), false);
});

test("print and csv include only the given employee", () => {
  const html = printDocumentHtml({
    title: "Breaks",
    subtitle: "Monday",
    sections: [{ heading: "Breaks", rows: [{ employee: "Amina Cole", when: "12:00", detail: "Timed" }] }],
  });
  assert.match(html, /Amina Cole/);
  assert.equal(html.includes("Other Person"), false);
  assert.match(scheduleCsv([{ employee: "Amina Cole", day: "Monday", start: "08:00", end: "16:00", role: "fold", breaks: "", tasks: "" }]), /Amina Cole/);
});
