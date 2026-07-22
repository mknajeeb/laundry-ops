/**
 * Map Step-1 UI filters onto API `summary.segments` keys.
 * Presentation only — no count math.
 *
 * @param {"all"|"wf"|"hd"} service
 * @param {"all"|"rush"|"non_rush"} rush
 * @returns {{ wf: string|null, hd: string|null, total: string }}
 */
export function resolveStep1SegmentKeys(service = "all", rush = "all") {
  const rushKey = rush === "rush" ? "rush" : rush === "non_rush" ? "non_rush" : "all";
  if (service === "wf") {
    if (rushKey === "rush") return { wf: "wf_rush", hd: null, total: "wf_rush" };
    if (rushKey === "non_rush") return { wf: "wf_non_rush", hd: null, total: "wf_non_rush" };
    return { wf: "wf", hd: null, total: "wf" };
  }
  if (service === "hd") {
    if (rushKey === "rush") return { wf: null, hd: "hd_rush", total: "hd_rush" };
    if (rushKey === "non_rush") return { wf: null, hd: "hd_non_rush", total: "hd_non_rush" };
    return { wf: null, hd: "hd", total: "hd" };
  }
  if (rushKey === "rush") return { wf: "wf_rush", hd: "hd_rush", total: "rush" };
  if (rushKey === "non_rush") return { wf: "wf_non_rush", hd: "hd_non_rush", total: "non_rush" };
  return { wf: "wf", hd: "hd", total: "all" };
}
