import { describe, expect, it } from "vitest";
import { TRANSLATIONS } from "../i18n/translations";
import {
  displayRole,
  displayWorkType,
  formatEmployeeAssignmentLabel,
  successAssignmentLabelFromBody,
} from "./mobileOpsCopy";

const tEs = (key) => TRANSLATIONS.es[key] ?? TRANSLATIONS.en[key] ?? key;
const tEn = (key) => TRANSLATIONS.en[key] ?? key;

describe("mobileOpsCopy displayRole / displayWorkType", () => {
  it("maps backend codes to friendly EN labels", () => {
    expect(displayRole("OPERATOR", tEn)).toBe("Wash-Dry");
    expect(displayRole("SORT", tEn)).toBe("Sort");
    expect(displayRole("FOLDER", tEn)).toBe("Fold");
    expect(displayWorkType("RINSE_WF", tEn)).toBe("Rinse Wash & Fold");
    expect(displayWorkType("RINSE_HD", tEn)).toBe("Rinse Hang Dry");
  });

  it("maps the same codes to operational Spanish", () => {
    expect(displayRole("OPERATOR", tEs)).toBe("Lavar-Secar");
    expect(displayRole("SORT", tEs)).toBe("Clasificar");
    expect(displayRole("FOLDER", tEs)).toBe("Doblar");
    expect(displayWorkType("RINSE_WF", tEs)).toBe("Rinse Lavado y Doblado");
    expect(displayWorkType("RINSE_HD", tEs)).toBe("Rinse Secado al Aire");
    expect(displayWorkType("DHS", tEs)).toBe("No Rinse");
  });

  it("formats assignment without leaking Operator / RINSE_*", () => {
    const label = formatEmployeeAssignmentLabel(
      {
        roleCode: "OPERATOR",
        categoryCode: "RINSE_WF",
      },
      tEs,
    );
    expect(label).toBe("Lavar-Secar | Rinse Lavado y Doblado");
    expect(label).not.toMatch(/Operator|FOLDER|RINSE_|DHS/i);
  });

  it("builds success label from switch body segment codes", () => {
    const label = successAssignmentLabelFromBody(
      {
        ok: true,
        segment: {
          role_code: "SORT",
          category_code: "RINSE_WF",
        },
      },
      tEn,
    );
    expect(label).toBe("Sort | Rinse Wash & Fold");
  });
});
