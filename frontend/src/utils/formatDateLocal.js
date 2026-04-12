/** Today in the user's locale (for floor screens). */
export function formatSystemDateLong(date = new Date()) {
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
