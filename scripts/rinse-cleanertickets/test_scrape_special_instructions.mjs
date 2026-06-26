import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  findSpecialInstructionsColumnIndexFromHeaders,
  dataColumnIndexForSpecialInstructions,
  normalizeCellMultilineText,
  cleanVisibleTableSpecialInstructions,
  resolveFinalSpecialInstructions,
  derivePortalSupplyFlagsFromSi,
  isVendorCatalogPollution,
  isPortalTableStatusMarker,
  parsePortalFields,
} from "./scrape.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fixturePath = path.join(__dirname, "fixtures", "visible_table_si_rows.json");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

test("findSpecialInstructionsColumnIndexFromHeaders locates SI column", () => {
  assert.equal(findSpecialInstructionsColumnIndexFromHeaders(fixture.table_headers), 8);
  assert.equal(dataColumnIndexForSpecialInstructions(fixture.table_headers), 7);
  assert.equal(
    findSpecialInstructionsColumnIndexFromHeaders(["Date", "Customer", "Special Instruction"]),
    2,
  );
  assert.equal(findSpecialInstructionsColumnIndexFromHeaders(["Date", "Customer", "Weight"]), -1);
});

test("isPortalTableStatusMarker ignores assembled/bagged icons", () => {
  assert.equal(isPortalTableStatusMarker("✗"), true);
  assert.equal(isPortalTableStatusMarker("USE OXICLEAN"), false);
});

test("normalizeCellMultilineText preserves intentional line breaks", () => {
  const raw = "USE FABRIC SOFTENER\r\nUSE OXICLEAN\r\n  Use Hypoallergenic Soap  ";
  assert.equal(
    normalizeCellMultilineText(raw),
    "USE FABRIC SOFTENER\nUSE OXICLEAN\nUse Hypoallergenic Soap",
  );
});

test("cleanVisibleTableSpecialInstructions rejects vendor catalog pollution", () => {
  assert.equal(cleanVisibleTableSpecialInstructions("VENDOR NOTES\nWash and Fold"), "");
  assert.equal(cleanVisibleTableSpecialInstructions("USE OXICLEAN"), "USE OXICLEAN");
});

test("resolveFinalSpecialInstructions prefers visible table over expanded detail", () => {
  const visible = "USE FABRIC SOFTENER\nUSE OXICLEAN";
  const expanded = "Special Instructions: vendor noise";
  assert.equal(resolveFinalSpecialInstructions(visible, expanded), visible);
});

test("resolveFinalSpecialInstructions falls back to expanded detail when visible empty", () => {
  assert.equal(resolveFinalSpecialInstructions("", "Low dry heat only"), "Low dry heat only");
});

test("isVendorCatalogPollution detects expanded vendor menus", () => {
  assert.equal(isVendorCatalogPollution("VENDOR NOTES"), true);
  assert.equal(isVendorCatalogPollution("Please ensure accurate pairing of socks."), false);
});

test("derivePortalSupplyFlagsFromSi reads multiline visible SI", () => {
  const flags = derivePortalSupplyFlagsFromSi(
    "USE FABRIC SOFTENER\nUSE OXICLEAN\nUse Hypoallergenic Soap",
  );
  assert.equal(flags.USE_FAB, "X");
  assert.equal(flags.USE_OXIC, "X");
  assert.equal(flags.Use_Hypo, "X");
});

test("parsePortalFields uses visible table SI as primary source", () => {
  for (const row of fixture.rows) {
    const collapsed = `Sun 06/28/2026\n${row.customer}\n18.8 LBS\nNA`;
    const expanded = row.expanded_detail_special_instructions
      ? `Bag: ${row.bag_id}\nSpecial Instructions: ${row.expanded_detail_special_instructions}`
      : "";
    const portal = parsePortalFields(collapsed, expanded, null, row.bag_id, {
      visibleTableSi: row.visible_table_special_instructions,
    });

    assert.equal(
      portal.special_instructions,
      row.expected_final_special_instructions,
      `final SI mismatch for ${row.bag_id}`,
    );
    assert.equal(
      portal.visible_table_special_instructions,
      cleanVisibleTableSpecialInstructions(row.visible_table_special_instructions),
      `visible SI mismatch for ${row.bag_id}`,
    );

    for (const [flag, expected] of Object.entries(row.expected_flags || {})) {
      assert.equal(portal[flag], expected, `${flag} for ${row.bag_id}`);
    }
    for (const flag of ["USE_FAB", "USE_OXIC", "Use_Hypo", "Low_DRY", "NO_SCEN", "Extra_Scen"]) {
      if (row.expected_flags?.[flag]) continue;
      assert.equal(portal[flag] || "", "", `${flag} should be empty for ${row.bag_id}`);
    }
  }
});

test("visible table cell texts map to SI column index from headers", () => {
  const siIdx = dataColumnIndexForSpecialInstructions(fixture.table_headers);
  assert.equal(siIdx, 7);
  const sampleCells = [
    "Fri 06/26/2026 TODAY",
    "Sofia Sam 0",
    "0",
    "18.8 LBS",
    "0",
    "0",
    "0",
    "USE FABRIC SOFTENER\nUSE OXICLEAN",
    "✗",
    "✗",
  ];
  const visible = cleanVisibleTableSpecialInstructions(normalizeCellMultilineText(sampleCells[siIdx]));
  assert.equal(visible, "USE FABRIC SOFTENER\nUSE OXICLEAN");
  assert.equal(cleanVisibleTableSpecialInstructions(sampleCells[siIdx + 1]), "");
});
