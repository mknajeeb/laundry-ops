/**
 * Display API timestamps in US Eastern (America/New_York, EST/EDT).
 * Expects ISO strings from the API with UTC offset (Z or +00:00).
 */
export function formatEasternDateTime(iso) {
  if (iso == null || iso === "") return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-US", {
    timeZone: "America/New_York",
    month: "numeric",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
    timeZoneName: "short",
  });
}
