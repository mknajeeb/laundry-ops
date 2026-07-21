import { describe, expect, test } from "vitest";

import {
  bulkDownloadPlan,
  documentColumnLabel,
  documentDownloadSuffix,
  downloadAllLabel,
  netColumnLabel,
  rowDocumentActions,
  rowDocumentKind,
  taxWithheldApplies,
  workerOptionsForCategory,
  workersForCategory,
} from "./payrollDocumentHistory";
import { paystubDownloadFilename } from "./paystubDownload";

const w2Final = {
  id: 11,
  batch_id: 1,
  worker_category: "w2",
  worker_name_snapshot: "Ann Lee",
  pay_period_start: "2026-05-01",
  pay_period_end: "2026-05-15",
  payout_details_finalized_at: "2026-05-16T00:00:00",
  document: { effective_type: "official_paystub", paystub_available: true, vendor_receipt_available: false },
};

const tempFinal = {
  id: 12,
  batch_id: 2,
  worker_category: "temp",
  worker_name_snapshot: "Bob Ray",
  pay_period_start: "2026-05-01",
  pay_period_end: "2026-05-15",
  payout_details_finalized_at: "2026-05-16T00:00:00",
  document: {
    effective_type: "vendor_receipt",
    paystub_available: false,
    vendor_receipt_available: true,
    vendor: { id: 1, name: "Washmate Inc" },
  },
};

const contractorFinal = {
  id: 13,
  batch_id: 3,
  worker_category: "contractor_1099",
  worker_name_snapshot: "Cid Poe",
  pay_period_start: "2026-05-01",
  pay_period_end: "2026-05-15",
  payout_details_finalized_at: "2026-05-16T00:00:00",
  document: { effective_type: "vendor_receipt", paystub_available: false, vendor_receipt_available: true },
};

const tempPreviewOnly = {
  id: 14,
  batch_id: 4,
  worker_category: "temp",
  worker_name_snapshot: "Dot Kim",
  pay_period_start: "2026-06-01",
  pay_period_end: "2026-06-15",
  payout_details_finalized_at: null,
  document: {
    effective_type: "vendor_receipt",
    paystub_available: false,
    vendor_receipt_available: false,
    vendor_receipt_preview_available: true,
  },
};

const w2Pending = {
  id: 15,
  batch_id: 5,
  worker_category: "w2",
  worker_name_snapshot: "Eve Ng",
  pay_period_start: "2026-06-01",
  pay_period_end: "2026-06-15",
  payout_details_finalized_at: null,
  document: { effective_type: "official_paystub", paystub_available: false, vendor_receipt_available: false },
};

describe("document kind by category", () => {
  test("W-2 employee is a paystub", () => {
    expect(rowDocumentKind(w2Final)).toBe("paystub");
  });
  test("temp worker is a receipt", () => {
    expect(rowDocumentKind(tempFinal)).toBe("receipt");
  });
  test("1099 worker is a receipt", () => {
    expect(rowDocumentKind(contractorFinal)).toBe("receipt");
  });
});

describe("row document actions", () => {
  test("W-2 finalized offers the paystub, never a receipt", () => {
    const a = rowDocumentActions(w2Final);
    expect(a).toEqual({ kind: "paystub", final: true, preview: true });
  });

  test("temp finalized offers the receipt, never a paystub", () => {
    const a = rowDocumentActions(tempFinal);
    expect(a).toEqual({ kind: "receipt", final: true, preview: true });
  });

  test("1099 finalized offers the receipt", () => {
    expect(rowDocumentActions(contractorFinal).final).toBe(true);
    expect(rowDocumentActions(contractorFinal).kind).toBe("receipt");
  });

  test("W-2 row never resolves to a receipt even if a vendor flag leaks in", () => {
    const leaky = { ...w2Final, document: { ...w2Final.document, vendor_receipt_available: true } };
    expect(rowDocumentActions(leaky).kind).toBe("paystub");
  });

  test("temp/1099 row never resolves to a paystub even if a paystub flag leaks in", () => {
    const leaky = { ...tempFinal, document: { ...tempFinal.document, paystub_available: true } };
    expect(rowDocumentActions(leaky).kind).toBe("receipt");
  });

  test("unfinalized W-2 offers no final document and no preview", () => {
    expect(rowDocumentActions(w2Pending)).toEqual({ kind: "paystub", final: false, preview: false });
  });

  test("unfinalized temp may preview but never a final download", () => {
    expect(rowDocumentActions(tempPreviewOnly)).toEqual({
      kind: "receipt",
      final: false,
      preview: true,
    });
  });

  test("finalized receipt uses the final (non-preview) document, backed by the stored snapshot", () => {
    // final=true → the UI fetches the finalized receipt (preview=false), which the
    // backend renders from the persisted vendor snapshot for historical immutability.
    expect(rowDocumentActions(tempFinal).final).toBe(true);
    expect(tempFinal.document.vendor).toEqual({ id: 1, name: "Washmate Inc" });
  });
});

describe("tax withheld applicability", () => {
  test("applies to W-2", () => {
    expect(taxWithheldApplies(w2Final)).toBe(true);
  });
  test("not applicable to contractor receipts", () => {
    expect(taxWithheldApplies(tempFinal)).toBe(false);
    expect(taxWithheldApplies(contractorFinal)).toBe(false);
  });
});

describe("dynamic labels", () => {
  test("final column label by category", () => {
    expect(documentColumnLabel("w2", [w2Final])).toBe("Paystub");
    expect(documentColumnLabel("temp", [tempFinal])).toBe("Receipt");
    expect(documentColumnLabel("contractor_1099", [contractorFinal])).toBe("Receipt");
    expect(documentColumnLabel("all", [w2Final, tempFinal])).toBe("Document");
    expect(documentColumnLabel("all", [tempFinal, contractorFinal])).toBe("Receipt");
    expect(documentColumnLabel("all", [w2Final])).toBe("Paystub");
  });

  test("download-all label by category", () => {
    expect(downloadAllLabel("w2", [w2Final])).toBe("Download All Paystubs");
    expect(downloadAllLabel("temp", [tempFinal])).toBe("Download All Receipts");
    expect(downloadAllLabel("contractor_1099", [contractorFinal])).toBe("Download All Receipts");
    expect(downloadAllLabel("all", [w2Final, tempFinal])).toBe("Download All Documents");
  });

  test("net column becomes Amount paid when only receipts are shown", () => {
    expect(netColumnLabel([tempFinal, contractorFinal])).toBe("Amount paid");
    expect(netColumnLabel([w2Final])).toBe("Net paid");
    expect(netColumnLabel([w2Final, tempFinal])).toBe("Net paid");
    expect(netColumnLabel([])).toBe("Net paid");
  });
});

describe("bulk download plan", () => {
  test("includes both document types and excludes pending rows", () => {
    const plan = bulkDownloadPlan([w2Final, tempFinal, contractorFinal, tempPreviewOnly, w2Pending]);
    expect(plan.map((p) => p.kind)).toEqual(["paystub", "receipt", "receipt"]);
    // temp/1099 receipts are never silently omitted
    expect(plan.filter((p) => p.kind === "receipt").length).toBe(2);
    // pending / preview-only rows produce no final download
    expect(plan.find((p) => p.lineId === tempPreviewOnly.id)).toBeUndefined();
    expect(plan.find((p) => p.lineId === w2Pending.id)).toBeUndefined();
  });

  test("filenames identify worker, pay period, and document type", () => {
    const plan = bulkDownloadPlan([w2Final, tempFinal]);
    const names = plan.map((p) =>
      paystubDownloadFilename(p.workerName, p.payPeriodStart, p.payPeriodEnd, {
        suffix: documentDownloadSuffix(p.kind),
      }),
    );
    expect(names[0]).toBe("Ann Lee 2026-05-01 to 2026-05-15 Paystub.pdf");
    expect(names[1]).toBe("Bob Ray 2026-05-01 to 2026-05-15 Receipt.pdf");
  });
});

describe("worker filtering by category", () => {
  const users = [
    { id: 1, first_name: "Ann", last_name: "Lee", hr_form_lanes: ["employee_w2"] },
    { id: 2, first_name: "Bob", last_name: "Ray", hr_form_lanes: ["contractor_1099"] },
    { id: 3, first_name: "Cid", last_name: "Poe", hr_form_lanes: ["contractor_temp"] },
    { id: 4, first_name: "Dee", last_name: "Fox", hr_form_lanes: ["employee_w2", "contractor_1099"] },
  ];

  test("W-2 category returns only W-2 lanes", () => {
    expect(workersForCategory(users, "w2").map((u) => u.id).sort()).toEqual([1, 4]);
  });
  test("1099 category returns only 1099 lanes", () => {
    expect(workersForCategory(users, "contractor_1099").map((u) => u.id).sort()).toEqual([2, 4]);
  });
  test("temp category returns only temp lanes", () => {
    expect(workersForCategory(users, "temp").map((u) => u.id).sort()).toEqual([3]);
  });
  test("all categories unions and de-dupes workers", () => {
    expect(workersForCategory(users, "all").map((u) => u.id).sort()).toEqual([1, 2, 3, 4]);
  });
  test("options carry id and label", () => {
    const opts = workerOptionsForCategory(users, "w2");
    expect(opts).toEqual([
      { id: 1, label: "Ann Lee" },
      { id: 4, label: "Dee Fox" },
    ]);
  });
});
