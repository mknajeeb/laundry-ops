/** Today-only Folder Performance refresh. Not a general polling framework. */

export const FOLDER_PERFORMANCE_REFRESH_MS = 60000;

/**
 * Poll only the current business day on the Today comparison.
 * Historical dates and other comparisons stay on the initial load.
 */
export function shouldPollFolderPerformance({ compare, dateEt, todayYmd } = {}) {
  if (compare !== "today") return false;
  if (!dateEt || !todayYmd) return false;
  return String(dateEt) === String(todayYmd);
}
