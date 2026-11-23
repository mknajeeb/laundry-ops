import { readFileSync } from "node:fs";
import { addRecipient, personLabel } from "./NotificationAssignments";

describe("assignment directory labels", () => {
  it("shows the payroll name when the login name is only a surname", () => {
    expect(
      personLabel({
        id: 28,
        username: "singh",
        display_name: "Singh",
        employee_name: "Jasanpreet Singh",
      }),
    ).toBe("Jasanpreet Singh · Singh · singh");
  });

  it("keeps similar names apart with the payroll name and username", () => {
    expect(
      personLabel({
        id: 15,
        username: "veeadmin",
        display_name: "Muhammad",
        employee_name: "Muhammad Najeeb",
      }),
    ).toBe("Muhammad Najeeb · Muhammad · veeadmin");
    expect(
      personLabel({
        id: 32,
        username: "muhammad",
        display_name: "Muhammad Najeeb",
        employee_name: "Muhammad Najeeb",
      }),
    ).toBe("Muhammad Najeeb · muhammad");
  });

  it("labels an application user who has no payroll row", () => {
    expect(personLabel({ id: 58, username: "Martha", display_name: "Martha" })).toBe("Martha · Martha");
  });
});

describe("assignment recipient selection", () => {
  const jasanpreet = { id: 28, username: "singh", display_name: "Singh", employee_name: "Jasanpreet Singh" };
  const sarah = { id: 33, username: "Sarah_kams", display_name: "Sarah Kamran", employee_name: "Sarah Kamran" };

  it("adds a person and ignores a second click on the same id", () => {
    const once = addRecipient([], jasanpreet);
    expect(addRecipient(once, { ...jasanpreet })).toBe(once);
    expect(addRecipient(once, sarah).map((person) => person.id)).toEqual([28, 33]);
  });

  it("does not clear selected recipients when the search query changes", () => {
    const src = readFileSync(new URL("./NotificationAssignments.jsx", import.meta.url), "utf8");
    const search = src.slice(src.indexOf("getNotificationManagementUsers(query)"), src.indexOf("const selectedIds"));
    expect(search).toContain("setMatches");
    expect(search).not.toContain("setSelected");
    expect(src).toContain('maxHeight: { xs: "40vh", sm: 320 }');
    expect(src).toContain("addRecipient(rows, person)");
  });
});
