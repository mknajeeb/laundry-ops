import { describe, expect, it } from "vitest";
import {
  TEAM_ROLE_COLORS,
  resolveTeamRoleColorKey,
  teamRoleColors,
} from "./roleColors";

describe("resolveTeamRoleColorKey", () => {
  it("maps role codes, not display language", () => {
    expect(resolveTeamRoleColorKey({ roleCode: "OPERATOR" })).toBe("wash_dry");
    expect(resolveTeamRoleColorKey({ roleCode: "SORT" })).toBe("sort");
    expect(resolveTeamRoleColorKey({ roleCode: "FOLDER" })).toBe("fold");
  });

  it("maps English canonical labels and break kind", () => {
    expect(resolveTeamRoleColorKey({ roleLabel: "Wash-Dry" })).toBe("wash_dry");
    expect(resolveTeamRoleColorKey({ roleLabel: "Sort | Rinse Wash & Fold" })).toBe("sort");
    expect(resolveTeamRoleColorKey({ kind: "break" })).toBe("break");
    expect(resolveTeamRoleColorKey({ roleLabel: "Break" })).toBe("break");
  });

  it("prefers code over translated-looking label text", () => {
    expect(
      resolveTeamRoleColorKey({ roleCode: "SORT", roleLabel: "Clasificar" }),
    ).toBe("sort");
  });
});

describe("teamRoleColors", () => {
  it("returns distinct accessible families", () => {
    expect(teamRoleColors({ roleCode: "OPERATOR" }).accent).toBe(TEAM_ROLE_COLORS.wash_dry.accent);
    expect(teamRoleColors({ roleCode: "SORT" }).accent).toBe(TEAM_ROLE_COLORS.sort.accent);
    expect(teamRoleColors({ roleCode: "FOLDER" }).accent).toBe(TEAM_ROLE_COLORS.fold.accent);
    expect(teamRoleColors({ kind: "break" }).accent).toBe(TEAM_ROLE_COLORS.break.accent);
    expect(new Set(["wash_dry", "sort", "fold", "break"].map((k) => TEAM_ROLE_COLORS[k].accent)).size).toBe(
      4,
    );
  });
});
