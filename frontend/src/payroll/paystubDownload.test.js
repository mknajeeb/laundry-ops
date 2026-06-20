import { describe, expect, it } from "vitest";
import { paystubDownloadFilename } from "./paystubDownload";

describe("paystubDownloadFilename", () => {
  it("uses employee name and pay period", () => {
    expect(
      paystubDownloadFilename("Alec Coaxum", "2026-05-18", "2026-05-24"),
    ).toBe("Alec Coaxum 2026-05-18 to 2026-05-24 Paystub.html");
  });

  it("sanitizes unsafe characters in names", () => {
    expect(
      paystubDownloadFilename("Jane / Doe", "2026-01-01", "2026-01-07"),
    ).toBe("Jane Doe 2026-01-01 to 2026-01-07 Paystub.html");
  });
});
