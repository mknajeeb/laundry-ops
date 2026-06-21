import { getEmployeePaystubArchiveHtml, getPaystubArchiveMeta } from "../api";
import {
  downloadPdfFromFetch,
  paystubArchiveDownloadFilename,
} from "./paystubDownload";
import {
  archiveWorkerCategory,
  DEFAULT_RECENT_PAYSTUB_BATCHES,
  recentBatchIds,
} from "./paystubArchive";

/**
 * Download one PDF with an employee's paystubs across recent finalized pay periods.
 */
export async function downloadEmployeeRecentPaystubsPdf({
  userId,
  workerName,
  workerCategory,
  copy = "employee",
  recentCount = DEFAULT_RECENT_PAYSTUB_BATCHES,
} = {}) {
  if (!userId) {
    throw new Error("Employee is required");
  }
  const category = archiveWorkerCategory(workerCategory);
  const metaRes = await getPaystubArchiveMeta({ worker_category: category });
  const batches = metaRes.data?.batches || [];
  const batchIds = recentBatchIds(batches, recentCount);
  if (!batchIds.length) {
    throw new Error("No finalized pay periods available");
  }
  const selectedBatches = batches.filter((b) => batchIds.includes(b.id));
  const filename = paystubArchiveDownloadFilename({
    workerName,
    payPeriodStart: selectedBatches[0]?.pay_period_start,
    payPeriodEnd: selectedBatches[selectedBatches.length - 1]?.pay_period_end,
  });
  await downloadPdfFromFetch(
    () =>
      getEmployeePaystubArchiveHtml({
        worker_category: category,
        batch_ids: batchIds.join(","),
        user_id: userId,
        copy,
      }),
    filename,
  );
  return { batchCount: batchIds.length, filename };
}
