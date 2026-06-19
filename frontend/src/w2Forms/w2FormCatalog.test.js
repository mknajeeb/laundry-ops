import { describe, expect, it } from "vitest";
import { parsePacketSections } from "../contractorForms/parsePacket";
import packetMarkdown from "./veewash_w2_workforce_forms.md?raw";
import { editorFormIdFor, findW2Form, W2_FORMS } from "./formCatalog";
import { buildW2MultiSectionPrintHtml } from "./prefillMarkdown";

describe("W2 form catalog", () => {
  it("lists handbook, warning, separation, and workforce pack", () => {
    const ids = W2_FORMS.map((f) => f.id);
    expect(ids).toContain("handbook_acknowledgment");
    expect(ids).toContain("corrective_action");
    expect(ids).toContain("separation_checklist");
    expect(ids).toContain("workforce_pack");
  });

  it("maps corrective action to written_warning editor schema", () => {
    const form = findW2Form("corrective_action");
    expect(editorFormIdFor(form)).toBe("written_warning");
    expect(form.sections).toEqual(["7"]);
  });
});

describe("W2 print pipeline", () => {
  it("builds HTML for handbook acknowledgment section", () => {
    const sections = parsePacketSections(packetMarkdown);
    expect(sections["3"]?.body).toBeTruthy();
    const html = buildW2MultiSectionPrintHtml(
      sections,
      ["3"],
      { full_name: "Jane Doe", employee_id: "E-100", company_name: "VeeWash" },
      {},
      { formId: "handbook_acknowledgment", editorFormId: "handbook_acknowledgment", formValues: {} },
    );
    expect(html).toContain("Jane Doe");
    expect(html).toContain("Handbook");
  });
});
