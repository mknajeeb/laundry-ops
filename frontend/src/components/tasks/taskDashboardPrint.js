/** Letter print document for the Task Dashboard.

The app shell's print CSS hides every element except contractor and
weekly-schedule print roots. Printing the live dashboard page therefore yields
a blank sheet. This module writes a standalone document and prints that
document only.
*/

import { formatCompletionInput } from "../../opsMobile/TaskCompletionInputs";
import {
  formatDashboardDate,
  formatDashboardDateTime,
  formatDashboardTime,
  participationTimeLine,
} from "./taskDashboardFormat";
import {
  checklistItemLabel,
  completionLabel,
  dashboardHeadlineMetrics,
  formatDurationHm,
  overallLabel,
  participationLabel,
  participationStatusOf,
  participationSummary,
  verificationLabel,
} from "./taskDashboardLabels";

const GROUP_BY_LABELS = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function groupByLabel(groupBy) {
  const key = String(groupBy || "daily").trim().toLowerCase();
  return GROUP_BY_LABELS[key] || key;
}

function rangeText(start, end) {
  const startLabel = formatDashboardDate(start);
  const endLabel = formatDashboardDate(end);
  if (!end || start === end) return `${startLabel} ET`;
  return `${startLabel} – ${endLabel} ET`;
}

function checklistGroups(items) {
  const groups = new Map();
  for (const item of items) {
    const label = String(item?.section_label || "").trim();
    const order = Number(item?.section_order || 0);
    const key = `${order}::${label}`;
    if (!groups.has(key)) groups.set(key, { label, order, items: [] });
    groups.get(key).items.push(item);
  }
  return [...groups.values()].sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
}

function assignmentSummary(row) {
  const checklistItems = row?.shared_checklist_items || [];
  const requiredItems = checklistItems.filter((item) => item.required !== false);
  const checklistDone = requiredItems.filter((item) =>
    ["completed", "approved", "verified"].includes(String(item.status || "").toLowerCase())
  ).length;
  const finishedCount = (row?.contributions || []).filter(
    (contribution) => participationStatusOf(contribution) === "finished"
  ).length;
  return participationSummary({
    finished: row?.employees_finished ?? finishedCount,
    assigned: row?.employees_assigned ?? (row?.contributions || []).length,
    checklistDone: row?.checklist_done ?? checklistDone,
    checklistRequired: row?.checklist_required ?? requiredItems.length,
  });
}

function employeeNames(row) {
  const assigned = (row?.assigned_employees || []).filter(Boolean);
  if (assigned.length) return assigned.join(", ");
  const fromContributions = (row?.contributions || []).map((item) => item.employee_name).filter(Boolean);
  return fromContributions.join(", ") || "Unassigned";
}

function metricCells(metrics, hideLabor) {
  const cells = [
    ["Activities assigned", metrics.activitiesAssigned],
    ["Completed", metrics.completedActivities],
    ["Pending verification", metrics.pendingVerification],
    ["Verified", metrics.verifiedActivities],
    ["Overdue", metrics.overdue],
    ["Employees assigned", metrics.employeesAssigned],
    ["Employees started", metrics.employeesStarted],
    ["Employees finished", metrics.employeesFinished],
  ];
  if (!hideLabor) cells.push(["Total time", metrics.totalTimeLabel]);
  return cells
    .map(
      ([label, value]) =>
        `<div class="metric"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`
    )
    .join("");
}

function checklistTable(items, sections, hideLabor = false) {
  const groups = checklistGroups(items);
  const showSections = groups.some((group) => group.label);
  return groups
    .map((group) => {
      const sectionStatus = (sections || []).find((section) => section.section_label === (group.label || "Checklist"));
      const heading = showSections
        ? `<div class="section">${escapeHtml(group.label || "Checklist")}${
            sectionStatus ? ` · ${escapeHtml(sectionStatus.status_label)}` : ""
          }</div>`
        : `<div class="section">Checklist${
            sectionStatus ? ` · ${escapeHtml(sectionStatus.status_label)}` : ""
          }</div>`;
      const rows = group.items
        .map((item) => {
          const detail = formatCompletionInput(item.completion_input, item.input_schema);
          const who = [
            item.completed_by_name || "",
            !hideLabor && item.completed_at ? formatDashboardTime(item.completed_at) : "",
          ]
            .filter(Boolean)
            .join(" · ");
          return `<tr>
            <td>${escapeHtml(item.task_name || item.task_code || "Item")}${
              detail ? `<div class="detail">${escapeHtml(detail)}</div>` : ""
            }</td>
            <td>${escapeHtml(item.responsibility_label || "Anyone on Team")}</td>
            <td>${escapeHtml(checklistItemLabel(item.display_status || item.status))}</td>
            <td>${escapeHtml(who || "—")}</td>
          </tr>`;
        })
        .join("");
      return `${heading}<table>
        <thead><tr><th>Item</th><th>Responsible</th><th>Status</th><th>Completed by</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    })
    .join("");
}

function remarksBlock(row, hideRemarks) {
  if (hideRemarks) return "";
  const remarks = Array.isArray(row?.remarks) ? row.remarks : [];
  if (!remarks.length) return "";
  const lines = remarks
    .map((remark) => {
      const who = [remark.author_name, remark.author_role, remark.task_code, remark.created_at_label]
        .filter(Boolean)
        .join(" · ");
      return `<li><b>${escapeHtml(who || "Remark")}</b><div class="detail">${escapeHtml(remark.body || "")}</div></li>`;
    })
    .join("");
  return `<div class="section">Remarks</div><ul>${lines}</ul>`;
}

function participantLines(row, hideLabor, hideRemarks) {
  const contributions = row?.contributions || [];
  if (!contributions.length) return "";
  const lines = contributions
    .map((contribution) => {
      const activity = contribution.activity || {};
      const duration = hideLabor ? "" : formatDurationHm(activity.duration_seconds || 0);
      const showDuration = !hideLabor && activity.duration_seconds != null && activity.duration_seconds !== "";
      const remarks = hideRemarks || (row?.remarks || []).length
        ? []
        : [
            activity.employee_remark?.text ? `Employee remark: ${activity.employee_remark.text}` : "",
            activity.supervisor_remark?.text ? `Supervisor remark: ${activity.supervisor_remark.text}` : "",
          ].filter(Boolean);
      return `<li>
        <b>${escapeHtml(contribution.employee_name || "Employee")}</b>
        · ${escapeHtml(participationLabel(participationStatusOf(contribution)))}
        ${hideLabor ? "" : ` · ${escapeHtml(participationTimeLine(contribution))}`}
        ${showDuration ? ` · ${escapeHtml(duration)}` : ""}
        ${remarks.length ? `<div class="detail">${escapeHtml(remarks.join(" · "))}</div>` : ""}
      </li>`;
    })
    .join("");
  return `<div class="section">Employees</div><ul>${lines}</ul>`;
}

function assignmentCard(row, hideLabor, hideRemarks) {
  const title = row?.role_label || row?.role || "Activity";
  const when = [employeeNames(row), row?.timing_label, row?.business_date ? formatDashboardDate(row.business_date) : ""]
    .filter(Boolean)
    .join(" · ");
  const checklist = row?.shared_checklist_items || [];
  const instructions = String(row?.instructions || "").trim();
  return `<article class="card">
    <div class="top">
      <div>
        <h3>${escapeHtml(title)}</h3>
        <div class="meta">${escapeHtml(when)}</div>
        ${
          hideLabor && row?.activity_started_at
            ? `<div class="meta">Started ${escapeHtml(formatDashboardDateTime(row.activity_started_at))}</div>`
            : ""
        }
        <div>${escapeHtml(assignmentSummary(row))}</div>
      </div>
      <div class="status">
        <div>Completion: ${escapeHtml(completionLabel(row?.completion_status))}</div>
        <div>Verification: ${escapeHtml(verificationLabel(row?.verification_status))}</div>
        ${
          row?.overall_status
            ? `<div>Overall: ${escapeHtml(overallLabel(row.overall_status))}</div>`
            : ""
        }
      </div>
    </div>
    ${instructions ? `<div class="detail">${escapeHtml(instructions)}</div>` : ""}
    ${checklist.length ? checklistTable(checklist, row?.checklist_sections, hideLabor) : ""}
    ${remarksBlock(row, hideRemarks)}
    ${participantLines(row, hideLabor, hideRemarks)}
  </article>`;
}

export function buildTaskDashboardPrintDocument({
  rangeStart,
  rangeEnd,
  categoryLabel = "All",
  groupBy = "daily",
  rows = [],
  hideLabor = false,
  hideRemarks = false,
} = {}) {
  const list = Array.isArray(rows) ? rows : [];
  const metrics = dashboardHeadlineMetrics(list);
  const cards = list.length
    ? list.map((row) => assignmentCard(row, hideLabor, hideRemarks)).join("")
    : `<p class="empty">No assignments in this range.</p>`;
  const subtitle = `${rangeText(rangeStart, rangeEnd)} · ${categoryLabel || "All"} · ${groupByLabel(groupBy)}`;
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>VeeWash Task Dashboard</title>
<style>
  @page { size: letter portrait; margin: 0.55in; }
  html, body { margin: 0; padding: 0; background: #fff; color: #0f2744; }
  body { font-family: "Segoe UI", Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.35; }
  h1 { font-size: 18pt; line-height: 1.15; margin: 0 0 2px; }
  h2 { font-size: 8.5pt; letter-spacing: 0.06em; text-transform: uppercase; color: #64748b; margin: 14px 0 6px; }
  h3 { font-size: 12.5pt; margin: 0; }
  .sub, .meta, .detail { color: #475569; }
  .sub { margin: 0 0 12px; }
  .metrics { display: flex; flex-wrap: wrap; gap: 6px; }
  .metric { border: 1px solid #d5deea; border-radius: 6px; padding: 4px 8px; min-width: 92px; }
  .metric span { display: block; font-size: 8pt; color: #64748b; }
  .metric b { font-size: 13pt; }
  .card { border: 1px solid #d5deea; border-radius: 8px; padding: 8px 10px 10px; margin: 0 0 10px; break-inside: avoid; page-break-inside: avoid; }
  .top { display: flex; justify-content: space-between; gap: 12px; }
  .status { text-align: right; font-size: 9.5pt; font-weight: 700; white-space: nowrap; }
  .section { margin-top: 8px; font-size: 8pt; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: #64748b; }
  table { width: 100%; border-collapse: collapse; margin-top: 2px; }
  th { text-align: left; font-size: 8pt; color: #64748b; font-weight: 700; }
  td, th { border-bottom: 1px solid #e7edf4; padding: 3px 6px 3px 0; vertical-align: top; }
  ul { margin: 2px 0 0; padding-left: 18px; }
  .empty { border: 1px solid #d5deea; border-radius: 8px; padding: 16px; }
  .foot { margin-top: 14px; font-size: 8.5pt; color: #64748b; }
</style>
</head>
<body>
  <h1>VeeWash Task Dashboard</h1>
  <p class="sub">${escapeHtml(subtitle)}</p>
  <h2>Summary</h2>
  <div class="metrics">${metricCells(metrics, hideLabor)}</div>
  <h2>Activities</h2>
  ${cards}
  <p class="foot">Times are America/New_York. Navigation and controls are omitted from this report.</p>
</body>
</html>`;
}

function writeDocument(win, html) {
  win.document.open();
  win.document.write(html);
  win.document.close();
}

function scheduleChildPrint(win) {
  const trigger = () => {
    setTimeout(() => {
      try {
        win.focus();
      } catch {
        /* ignore */
      }
      win.print();
    }, 200);
  };
  if (win.document?.readyState === "complete") trigger();
  else win.onload = trigger;
}

function printHtmlInHiddenFrame(html) {
  const iframe = document.createElement("iframe");
  iframe.setAttribute("aria-hidden", "true");
  iframe.setAttribute("title", "VeeWash Task Dashboard print");
  iframe.style.position = "fixed";
  iframe.style.left = "-10000px";
  iframe.style.top = "0";
  iframe.style.width = "816px";
  iframe.style.height = "1056px";
  iframe.style.border = "0";
  document.body.appendChild(iframe);
  const frameWindow = iframe.contentWindow;
  writeDocument(frameWindow, html);
  const cleanup = () => {
    try {
      iframe.remove();
    } catch {
      /* ignore */
    }
  };
  frameWindow.addEventListener("afterprint", cleanup, { once: true });
  setTimeout(cleanup, 60000);
  scheduleChildPrint(frameWindow);
}

/**
 * Print the dashboard report. Uses a new document so app-shell print CSS
 * cannot hide the content. Never calls the parent window's print.
 */
export function deliverTaskDashboardPrint(html, deps = {}) {
  const openWindow = deps.openWindow || (() => window.open("", "_blank"));
  const printFrame = deps.printFrame || printHtmlInHiddenFrame;
  const schedule = deps.scheduleChildPrint || scheduleChildPrint;
  let child = null;
  try {
    child = openWindow();
  } catch {
    child = null;
  }
  if (child?.document) {
    writeDocument(child, html);
    schedule(child);
    return "window";
  }
  printFrame(html);
  return "frame";
}

export function printTaskDashboard(model, deps) {
  const html = buildTaskDashboardPrintDocument(model);
  return deliverTaskDashboardPrint(html, deps);
}
