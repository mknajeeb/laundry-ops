import { summaryTextLines } from "./weeklyScheduleSummaryLines";

/** Summary lines for the print header: totals first, then one line per role category. */
export default function WeeklyScheduleSummaryPrint({
  summary,
  showBreaks = true,
  hideLaborHours = false,
  noRolesText = "",
}) {
  if (!summary) return null;
  const lines = noRolesText
    ? [noRolesText]
    : summaryTextLines(summary, { showBreaks, hideLaborHours });
  return (
    <div className="weekly-schedule-print-summary-lines">
      {lines.map((line, index) => (
        <div key={index} className={index === 0 ? "weekly-schedule-print-summary-total" : "weekly-schedule-print-summary-role"}>
          {line}
        </div>
      ))}
    </div>
  );
}
