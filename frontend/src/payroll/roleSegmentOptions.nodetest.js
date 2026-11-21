import assert from "node:assert/strict";
import test from "node:test";
import { categoryMenuOptions, roleMenuOptions } from "./roleSegmentOptions.js";

const tree = [
  {
    id: 1,
    name: "Rinse WF",
    roles: [
      { id: 1, role_id: 1, role_name: "Operator" },
      { id: 11, role_id: 3, role_name: "Sort" },
      { id: 2, role_id: 2, role_name: "Folder" },
    ],
  },
  {
    id: 2,
    name: "Rinse HD",
    roles: [
      { id: 3, role_id: 1, role_name: "Operator" },
      { id: 4, role_id: 2, role_name: "Folder" },
    ],
  },
  {
    id: 3,
    name: "DHS",
    roles: [
      { id: 5, role_id: 1, role_name: "Operator" },
      { id: 6, role_id: 2, role_name: "Folder" },
    ],
  },
  {
    id: 4,
    name: "Drop Off",
    roles: [
      { id: 7, role_id: 1, role_name: "Operator" },
      { id: 8, role_id: 2, role_name: "Folder" },
    ],
  },
];

const savedWfOperator = {
  categoryId: 1,
  categoryName: "Rinse WF",
  roleId: 1,
  roleName: "Operator",
};

test("saved category and role ids resolve to configured names", () => {
  const categories = categoryMenuOptions(tree, savedWfOperator);
  assert.deepEqual(
    categories.map((row) => row.label),
    ["Rinse WF", "Rinse HD", "DHS", "Drop Off"],
  );
  assert.equal(categories.find((row) => row.id === "1").label, "Rinse WF");
  assert.equal(
    categories.some((row) => /current category/i.test(row.label)),
    false,
  );

  const roles = roleMenuOptions(tree, "1", savedWfOperator);
  assert.deepEqual(
    roles.map((row) => [row.id, row.label]),
    [
      ["1", "Wash-Dry"],
      ["3", "Sort"],
      ["2", "Fold"],
    ],
  );
});

test("category selection limits roles to that category's active assignments", () => {
  const hd = roleMenuOptions(tree, "2", savedWfOperator);
  assert.deepEqual(
    hd.map((row) => row.label),
    ["Wash-Dry", "Fold"],
  );
  assert.equal(
    hd.some((row) => row.id === "1" && row.label === "Wash-Dry"),
    true,
  );
  assert.equal(hd.some((row) => row.label === "Sort"), false);
});

test("a saved role that is not on the newly selected category is not offered", () => {
  const savedSort = {
    categoryId: 1,
    categoryName: "Rinse WF",
    roleId: 3,
    roleName: "Sort",
  };
  const hd = roleMenuOptions(tree, 2, savedSort);
  assert.deepEqual(
    hd.map((row) => row.id),
    ["1", "2"],
  );
});

test("an inactive saved category keeps its stored name when absent from the active tree", () => {
  const options = categoryMenuOptions(tree, {
    categoryId: 5,
    categoryName: "Production Test Updated",
    roleId: 1,
    roleName: "Operator",
  });
  assert.equal(options.at(-1).id, "5");
  assert.equal(options.at(-1).label, "Production Test Updated");
  assert.equal(options.filter((row) => row.label === "Rinse WF").length, 1);
});
