import { describe, expect, it } from "vitest";
import { TRANSLATIONS } from "../../i18n/translations";
import { PIN_LAUNCHER_I18N } from "../../opsMobile/buildPinLauncherTiles";
import { buildTaskDashboardPrintDocument } from "./taskDashboardPrint";
import { hiddenRoutineAssignmentCodes, routineAssignmentOptions } from "./routineAssignmentOptions";
import { sectionRollups } from "./sectionVerification";
import { splitActivityRemarks } from "./taskEmployeeI18n";

describe("PIN task labels", () => {
  it("translates the cleaning task tiles in English and Spanish", () => {
    for (const key of Object.values(PIN_LAUNCHER_I18N)) {
      expect(TRANSLATIONS.en[key], key).toBeTruthy();
      expect(TRANSLATIONS.es[key], key).toBeTruthy();
      expect(TRANSLATIONS.en[key]).not.toBe(key);
      expect(TRANSLATIONS.es[key]).not.toBe(key);
    }
    expect(TRANSLATIONS.en["mobileOps.tile.cleaningTasks"]).toBe("Cleaning & Tasks");
    expect(TRANSLATIONS.es["mobileOps.tile.cleaningTasks"]).toBe("Limpieza y tareas");
    expect(TRANSLATIONS.en["mobileOps.tile.taskReview"]).toBe("Task Review");
    expect(TRANSLATIONS.es["mobileOps.tile.taskReview"]).toBe("Revisión de tareas");
    expect(TRANSLATIONS.en["mobileOps.currentRole"]).toBe("Current Role");
    expect(TRANSLATIONS.es["mobileOps.currentRole"]).toBe("Función actual");
    expect(TRANSLATIONS.es["mobileOps.notClockedIn"]).toBe("Sin fichar entrada");
    for (const key of [
      "tasks.pin.startActivity",
      "tasks.pin.finishParticipation",
      "tasks.pin.resumeActivity",
      "tasks.pin.addRemark",
      "tasks.pin.verificationNote",
      "tasks.pin.needsRedo",
      "tasks.pin.reviewTitle",
      "tasks.pin.status.pending_verification",
      "tasks.pin.status.needs_correction",
    ]) {
      expect(TRANSLATIONS.en[key], key).toBeTruthy();
      expect(TRANSLATIONS.es[key], key).toBeTruthy();
      expect(TRANSLATIONS.es[key]).not.toBe(TRANSLATIONS.en[key]);
    }
    expect(TRANSLATIONS.en["tasks.pin.startActivity"]).toBe("Start Activity");
    expect(TRANSLATIONS.es["tasks.pin.startActivity"]).toBe("Iniciar actividad");
    expect(TRANSLATIONS.en["tasks.pin.finishParticipation"]).toBe("Finish My Participation");
    expect(TRANSLATIONS.es["tasks.pin.finishParticipation"]).toBe("Terminar mi participación");
  });

  it("keeps verification events out of employee remarks", () => {
    const split = splitActivityRemarks([
      { author_role: "employee", body: "Residue in washer 2", remark_kind: "comment" },
      { author_role: "management", body: "Please recheck washer 3", remark_kind: "comment" },
      { author_role: "supervisor", body: "Machines verified", remark_kind: "verification" },
      { author_role: "supervisor", body: "Machines verified", legacy_source: null },
      { author_role: "employee", body: "Left the mop out", legacy_source: "employee_remark" },
    ]);
    expect(split.comments.map((row) => row.body)).toEqual(["Residue in washer 2", "Please recheck washer 3", "Left the mop out"]);
    expect(split.verification).toHaveLength(2);
  });
});

describe("routine assignment options", () => {
  const catalog = [
    { code: "lint_cleaning", name: "Dryer Lint Cleaning", uses_time_slots: false, active: true },
    { code: "agroup_dryer_lint", name: "Dryer Lint Cleaning", uses_time_slots: false, active: true },
    { code: "agroup_floor_washer", name: "Floor & Washer", uses_time_slots: false, active: true },
    { code: "agroup_washer_cleaning", name: "Washer Cleaning", uses_time_slots: false, active: true },
    { code: "agroup_floor_sweeping", name: "Floor Sweeping", uses_time_slots: false, active: true },
    { code: "floor_cleaning", name: "Floor Brooming", uses_time_slots: false, active: true },
  ];

  it("hides standalone routine tasks and Floor & Washer once the three groups are active", () => {
    const hidden = hiddenRoutineAssignmentCodes(catalog);
    expect(hidden.has("lint_cleaning")).toBe(true);
    expect(hidden.has("floor_cleaning")).toBe(true);
    expect(hidden.has("agroup_floor_washer")).toBe(true);
    const labels = routineAssignmentOptions(catalog).map((option) => option.label);
    expect(labels[0]).toContain("Dryer Lint Cleaning");
    expect(labels.some((label) => label.includes("Floor & Washer"))).toBe(false);
    expect(labels.some((label) => label === "Floor Brooming")).toBe(false);
  });
});

describe("section verification", () => {
  it("reports pending verification while a required item is awaiting review", () => {
    const [section] = sectionRollups([
      { section_label: "Dryer Cleaning", required: true, status: "completed", records: [{ status: "pending_approval", activity_id: 4 }] },
      { section_label: "Dryer Cleaning", required: false, status: "pending" },
    ]);
    expect(section.status_label).toBe("Pending Verification");
    expect(section.pending_activity_ids).toEqual([4]);
  });
});

describe("print remarks", () => {
  const row = {
    role_label: "Dryer Lint Cleaning",
    completion_status: "completed",
    verification_status: "pending_verification",
    remarks: [
      {
        author_name: "Yesenia",
        author_role: "employee",
        body: "Lint tray on dryer 2 was packed",
        created_at_label: "2026-11-01 21:05:00 ET",
        remark_kind: "comment",
      },
      {
        author_name: "VeeWash Admin",
        author_role: "supervisor",
        body: "Machines verified",
        created_at_label: "2026-11-01 22:46:45 ET",
        remark_kind: "verification",
      },
    ],
    checklist_sections: [{ section_label: "Dryer Cleaning", status_label: "Pending Verification" }],
    shared_checklist_items: [
      { task_name: "Clean dryer lint and gaskets", section_label: "Dryer Cleaning", status: "completed", required: true },
    ],
    contributions: [{ employee_name: "Yesenia", status: "completed", activity: { employee_remark: { text: "hidden from rinse" } } }],
  };

  it("prints authorized remarks and section status", () => {
    const html = buildTaskDashboardPrintDocument({
      rangeStart: "2026-11-01",
      rangeEnd: "2026-11-01",
      rows: [row],
    });
    expect(html).toContain("Lint tray on dryer 2 was packed");
    expect(html).toContain("Machines verified");
    expect(html.indexOf(">Remarks<")).toBeLessThan(html.indexOf(">Verification<"));
    expect(html).toContain("@page { size: letter portrait;");
    expect(html).toContain("break-inside: auto");
    expect(html).toContain("Pending Verification");
    expect(html).toContain("Yesenia");
  });

  it("omits remarks when the viewer is not authorized", () => {
    const html = buildTaskDashboardPrintDocument({
      rangeStart: "2026-11-01",
      rangeEnd: "2026-11-01",
      rows: [row],
      hideRemarks: true,
      hideLabor: true,
    });
    expect(html).not.toContain("Lint tray on dryer 2 was packed");
    expect(html).not.toContain("hidden from rinse");
    expect(html).toContain("Dryer Lint Cleaning");
  });
});
