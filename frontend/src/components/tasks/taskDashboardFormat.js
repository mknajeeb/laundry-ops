/** Friendly date/time formatting for Task Dashboard (America/New_York wall times). */

export function formatDashboardDate(value) {
  if (!value) return "—";
  const text = String(value).trim().replace("T", " ");
  const ymd = text.slice(0, 10);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  if (!m) return text;
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const month = months[Number(m[2]) - 1] || m[2];
  return `${month} ${Number(m[3])}, ${m[1]}`;
}

export function formatDashboardTime(value) {
  if (!value) return "—";
  const text = String(value).trim().replace("T", " ");
  const match = /(\d{2}):(\d{2})(?::\d{2})?/.exec(text);
  if (!match) return text;
  let hour = Number(match[1]);
  const minute = match[2];
  const suffix = hour >= 12 ? "PM" : "AM";
  hour = hour % 12;
  if (hour === 0) hour = 12;
  return `${hour}:${minute} ${suffix}`;
}

export function formatDashboardDateTime(value) {
  if (!value) return "—";
  const text = String(value).trim().replace("T", " ");
  const datePart = formatDashboardDate(text.slice(0, 10));
  const timePart = formatDashboardTime(text);
  if (datePart === "—" || timePart === "—") return text;
  if (text.length <= 10) return datePart;
  return `${datePart} · ${timePart}`;
}
