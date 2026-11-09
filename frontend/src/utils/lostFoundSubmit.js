/** Turn a report-save response into an employee-facing message. Never surface "Forbidden". */

export function reportFailureMessage(body, fallback) {
  const code = String(body?.code || "");
  const raw = String(body?.error || "");
  if (code === "reporting_not_allowed" || raw === "Forbidden") {
    return "reporting_not_allowed";
  }
  if (code === "photo_required") return "photo_required";
  if (code === "redry_one_reason" || code === "redry_flag_required") return code;
  if (code === "location_number_required" || code === "pocket_not_designated") return "pocket_required";
  if (
    raw === "Invalid PIN. Please try again."
    || code === "pin_session"
  ) {
    return "pin_session";
  }
  return raw || fallback || "";
}

export function savedReport(body) {
  const item = body?.item;
  if (!body?.ok || !item?.id) return null;
  const photos = item.photos;
  if (!Array.isArray(photos) || photos.length < 1) return null;
  return item;
}
