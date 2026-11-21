import { useNavigate } from "react-router-dom";
import PinOpsDashboardFlow from "../opsMobile/PinOpsDashboardFlow";
import PinPayrollFlow from "../opsMobile/PinPayrollFlow";
import PinScanChronologyFlow from "../opsMobile/PinScanChronologyFlow";

const SCAN = {
  weighing: {
    summary: { total_sessions: 0, total_stage_seconds: 0 },
    sessions: [
      {
        bag_id: "B1044",
        employee: "Ana Rivera",
        time_et: "2026-11-21 09:14:00",
        weight_lbs: 18.2,
        local_session_id: null,
        session_status: "unassigned",
      },
      {
        bag_id: "B1048",
        employee: "",
        time_et: "2026-11-21 09:22:00",
        weight_lbs: 11.5,
        local_session_id: null,
        session_status: "unassigned",
      },
    ],
    local_sessions: {
      summary: {
        total_scans: 2,
        unassigned_scans: 2,
        total_sessions: 0,
        total_hours: 0,
        scans_per_hour: null,
      },
      sessions: [],
    },
  },
  sorting: {
    summary: { total_sessions: 1, total_stage_seconds: 900 },
    sessions: [
      {
        bag_id: "B1044",
        employee: "Ana Rivera",
        sort_time_et: "2026-11-21 10:02:00",
        local_session_id: 4,
        session_status: "matched",
      },
    ],
    local_sessions: {
      summary: { total_scans: 1, unassigned_scans: 0, total_sessions: 1, total_hours: 1.5, scans_per_hour: 0.67 },
      sessions: [{ id: 4 }],
    },
  },
  washing: {
    summary: { total_sessions: 1, unique_bags_washed: 1, unique_machines_used: 1 },
    sessions: [
      {
        bag_id: "B1044",
        employee: "Luis Ortega",
        washer_rack: "Washer 3",
        wash_time_et: "2026-11-21 11:10:00",
        local_session_id: null,
        session_status: "unassigned",
      },
    ],
    local_sessions: {
      summary: { total_scans: 1, unassigned_scans: 1, total_sessions: 0, total_hours: 0 },
      sessions: [],
    },
  },
  drying: {
    summary: { total_sessions: 1, unique_machines_used: 1, most_used_machine: "Dryer 2" },
    sessions: [
      {
        bag_id: "B1044",
        employee: "Luis Ortega",
        dryer_rack: "Dryer 2",
        dry_time_et: "2026-11-21 12:05:00",
        local_session_id: 8,
        session_status: "matched",
      },
    ],
    local_sessions: {
      summary: { total_scans: 1, unassigned_scans: 0, total_sessions: 1, total_hours: 0.75, scans_per_hour: 1.33 },
      sessions: [{ id: 8 }],
    },
  },
  folder: {
    summary: { total_sessions: 1, complete_sessions: 0, incomplete_sessions: 1, total_stage_seconds: 0 },
    sessions: [
      {
        bag_id: "B1048",
        employee: "Sam Cole",
        start_et: "2026-11-21 13:40:00",
        status: "incomplete_open",
        weight_lbs: 11.5,
        local_session_id: null,
        session_status: "unassigned",
      },
    ],
    local_sessions: {
      summary: { total_scans: 1, unassigned_scans: 1, total_sessions: 0, total_hours: 0 },
      sessions: [],
    },
  },
  user_activity: {
    summary: {
      active_employees: 2,
      total_activities: 2,
      weighing_count: 0,
      sorting_sessions: 1,
      washer_loads: 1,
      dryer_loads: 0,
      folder_sessions: 0,
    },
    employee_groups: [
      {
        employee: "Ana Rivera",
        activities: [
          {
            employee: "Ana Rivera",
            activity_type: "sorting",
            activity_label: "Sorting",
            time_et: "2026-11-21 10:02:00",
            bag_id: "B1044",
            source: "scan",
          },
        ],
      },
      {
        employee: "Luis Ortega",
        activities: [
          {
            employee: "Luis Ortega",
            activity_type: "washing",
            activity_label: "Washing",
            time_et: "2026-11-21 11:10:00",
            bag_id: "B1044",
            machine_or_rack: "Washer 3",
            source: "scan",
          },
        ],
      },
    ],
  },
};

const PAYROLL = [
  {
    id: 11,
    batch_name: "1099 Nov 10",
    worker_category: "contractor_1099",
    worker_category_label: "1099",
    pay_period_start: "2026-11-10",
    pay_period_end: "2026-11-16",
    worker_count: 2,
    total_approved_hours: 40,
    total_gross_amount: 800,
    total_payout_amount: 800,
    payroll_display: {
      display_status: "ready_to_pay",
      display_status_label: "Ready To Pay",
      payroll_summary: { employee_count: 2, gross_payroll: 800 },
    },
    lines: [
      { id: 1, worker_name_snapshot: "Ana Rivera", payment_status: "paid", total_amount: 500, hourly_rate: 25 },
      {
        id: 2,
        worker_name_snapshot: "Luis Ortega",
        payment_status: "approved_unpaid",
        total_amount: 300,
        hourly_rate: 20,
      },
    ],
  },
  {
    id: 12,
    batch_name: "W-2 Nov 10",
    worker_category: "w2",
    worker_category_label: "W-2",
    pay_period_start: "2026-11-10",
    pay_period_end: "2026-11-16",
    worker_count: 4,
    total_approved_hours: 80,
    total_gross_amount: 1600,
    total_payout_amount: 1400,
    payroll_display: {
      display_status: "ready_for_payroll",
      display_status_label: "Ready For Payroll",
      payroll_summary: { employee_count: 4, gross_payroll: 1600 },
    },
  },
  {
    id: 3,
    batch_name: "Draft week",
    pay_period_start: "2026-11-17",
    pay_period_end: "2026-11-23",
    total_gross_amount: 9999,
    payroll_display: { display_status: "draft", display_status_label: "Draft" },
  },
];

export function DevPinScanPreviewPage() {
  return <PinScanChronologyFlow onBack={() => {}} onLock={() => {}} preview={SCAN} />;
}

export function DevPinPayrollPreviewPage() {
  return (
    <PinPayrollFlow
      onBack={() => {}}
      onLock={() => {}}
      preview={{ items: PAYROLL, paymentActionsAllowed: true }}
    />
  );
}

export function DevPinDashboardPreviewPage() {
  const navigate = useNavigate();
  return (
    <PinOpsDashboardFlow
      onBack={() => {}}
      onLock={() => {}}
      onOpen={(module) => {
        if (module === "issues") navigate("/dev/pin-issues");
        else if (module === "scan") navigate("/dev/pin-scan");
        else if (module === "payroll") navigate("/dev/pin-payroll");
      }}
      preview={{
        today: "2026-11-21",
        issuesToday: 3,
        issuesOpenToday: 2,
        outstanding: 2,
        scans: 2,
        scansWithEmployee: 1,
        activities: 2,
        working: 1,
        workingNames: ["Maria Lopez"],
        pendingVerification: 1,
        completedTasks: 4,
        latestPayroll: {
          name: "W-2 Nov 10",
          payPeriodStart: "2026-11-10",
          payPeriodEnd: "2026-11-16",
          grossWages: 1600,
          payoutAmount: 1400,
        },
      }}
    />
  );
}
