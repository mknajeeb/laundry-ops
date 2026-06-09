import { filterByRush } from "../../utils/shiftMonitorHelpers";

export function facilityDrilldownRecords(records, tag, rushFilter) {
  if (!tag) return records || [];
  let out = (records || []).filter((r) => (r.drilldown_tags || []).includes(tag));
  return filterByRush(out, rushFilter);
}
