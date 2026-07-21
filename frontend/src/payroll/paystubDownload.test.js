import { describe, expect, it } from "vitest";
import {
  paystubArchiveDownloadFilename,
  paystubDownloadFilename,
} from "./paystubDownload";

describe("paystubDownloadFilename", () => {
  it("uses employee name and pay period", () => {
    expect(
      paystubDownloadFilename("Alec Coaxum", "2026-05-18", "2026-05-24"),
    ).toBe("Alec Coaxum 2026-05-18 to 2026-05-24 Paystub.pdf");
  });

  it("sanitizes unsafe characters in names", () => {
    expect(
      paystubDownloadFilename("Jane / Doe", "2026-01-01", "2026-01-07"),
    ).toBe("Jane Doe 2026-01-01 to 2026-01-07 Paystub.pdf");
  });
});

describe("paystubArchiveDownloadFilename", () => {
  it("names all-employee archive", () => {
    expect(
      paystubArchiveDownloadFilename({
        payPeriodStart: "2026-05-18",
        payPeriodEnd: "2026-06-14",
        workerCategoryLabel: "W-2 employees",
      }),
    ).toBe("W-2 employees Paystub Archive 2026-05-18 to 2026-06-14.pdf");
  });

  it("names single-employee archive", () => {
    expect(
      paystubArchiveDownloadFilename({
        workerName: "Alec Coaxum",
        payPeriodStart: "2026-05-18",
        payPeriodEnd: "2026-06-14",
      }),
    ).toBe("Alec Coaxum Paystubs 2026-05-18 to 2026-06-14.pdf");
  });
});
