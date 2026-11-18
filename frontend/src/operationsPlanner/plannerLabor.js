import { computeWeekSummary } from "../components/weeklySchedule/weeklyScheduleRoles";
import { scheduleHourReconciliation } from "./plannerModel";

/**
 * Labor hours for the same entries.
 * Assignment hours add every shift.
 * Unique time counts an overlapping employee-day once.
 * Schedule hours are Weekly Schedule's own timeline, including its role-split break rule.
 */
export function laborComparison(entries, employees = []) {
  const assignment = scheduleHourReconciliation(entries);
  const schedule = computeWeekSummary({ employees, entries }, { entries });
  return {
    assignmentGross: assignment.shiftGross,
    assignmentBreak: assignment.shiftBreak,
    assignmentNet: assignment.shiftNet,
    uniqueGross: assignment.workedGross,
    uniqueBreak: assignment.workedBreak,
    uniqueNet: assignment.workedNet,
    overlapHours: assignment.overlapHours,
    scheduleGross: Number(schedule.grossHours) || 0,
    scheduleBreak: Number(schedule.breakHours) || 0,
    scheduleNet: Number(schedule.totalHours) || 0,
  };
}
