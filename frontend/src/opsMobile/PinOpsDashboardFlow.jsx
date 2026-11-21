import { useEffect, useState } from "react";
import { Alert, Box, CircularProgress, Stack, Typography } from "@mui/material";
import { attendancePinCleaningTasksReview, getIssuesRegister, getPayoutBatches, getScanChronology, getTeamStatus } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { addDaysYmd, businessTodayYmd } from "../utils/businessTime";
import { loadPinHubSession } from "../utils/pinHubSession";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import { approvedPublicBatches, formatMoney } from "./pinPayrollModel";

function Card({ title, lines, action, onOpen }) {
  return (
    <Box
      component="button"
      onClick={onOpen}
      sx={{
        textAlign: "left",
        width: "100%",
        p: 1.5,
        borderRadius: 2,
        border: `1px solid ${OPS_MOBILE.border}`,
        bgcolor: OPS_MOBILE.surface,
        cursor: "pointer",
      }}
    >
      <Typography fontWeight={800}>{title}</Typography>
      {lines.map((line) => (
        <Typography key={line} variant="body2" sx={{ mt: 0.5 }}>
          {line}
        </Typography>
      ))}
      <Typography variant="body2" color="primary" sx={{ mt: 1 }}>
        {action}
      </Typography>
    </Box>
  );
}

export default function PinOpsDashboardFlow({ onBack, onLock, onOpen, preview = null }) {
  const { t } = useI18n();
  const today = businessTodayYmd();
  const [loading, setLoading] = useState(!preview);
  const [error, setError] = useState("");
  const [snapshot, setSnapshot] = useState(preview);

  useEffect(() => {
    if (preview) return undefined;
    const controller = new AbortController();
    const hub = loadPinHubSession();
    const signal = controller.signal;
    setLoading(true);
    setError("");

    const settle = (promise) =>
      promise.then(
        (value) => ({ ok: true, value }),
        (err) => ({ ok: false, status: err?.response?.status || 0, error: err }),
      );

    Promise.all([
      settle(getIssuesRegister({ date_from: today, date_to: today, page_size: 1 }, { signal })),
      settle(
        getIssuesRegister(
          { date_from: addDaysYmd(today, -29), date_to: today, page_size: 1 },
          { signal },
        ),
      ),
      settle(getScanChronology({ date_et: today, stage: "weighing" }, { signal })),
      settle(getScanChronology({ date_et: today, stage: "user_activity" }, { signal })),
      settle(getTeamStatus(today)),
      settle(getPayoutBatches(undefined, { signal })),
      hub?.pin && hub?.organization_slug && hub?.features?.cleaning_task_review?.allowed
        ? settle(
            attendancePinCleaningTasksReview(hub.organization_slug, hub.pin, {
              hubToken: hub.token,
              business_date: today,
            }).then((res) => {
              if (res?.status >= 400 || res?.data?.ok === false) {
                const error = new Error(res?.data?.error || "review");
                error.response = res;
                throw error;
              }
              return res;
            }),
          )
        : Promise.resolve({ ok: false, status: 0, skipped: true }),
    ]).then((results) => {
      if (signal.aborted) return;
      const [issuesToday, issuesWindow, weighing, activity, team, payroll, tasks] = results;
      const next = { today };
      if (issuesToday.ok) {
        const summary = issuesToday.value?.data?.summary || {};
        next.issuesToday = summary.total ?? 0;
        next.issuesOpenToday = Number(summary.open || 0) + Number(summary.review || 0);
      }
      if (issuesWindow.ok) {
        const summary = issuesWindow.value?.data?.summary || {};
        next.outstanding = Number(summary.open || 0) + Number(summary.review || 0);
      }
      if (weighing.ok) {
        const sessions = weighing.value?.data?.sessions || [];
        next.scans = sessions.length;
        const named = sessions.filter((row) => {
          const name = String(row?.employee || "").trim();
          return name && name.toLowerCase() !== "unknown";
        }).length;
        next.scansWithEmployee = named;
        const recorded = Number(weighing.value?.data?.local_sessions?.summary?.total_sessions || 0);
        if (recorded > 0) next.recordedSessions = recorded;
      }
      if (activity.ok) {
        next.activities = activity.value?.data?.summary?.total_activities ?? 0;
      }
      if (team.ok) {
        const body = team.value?.data || {};
        const summary = body.summary || body.day?.summary || {};
        const working = body.working_now || body.day?.working_now || [];
        next.working = summary.working_count ?? working.length;
        next.workingNames = working
          .map((person) => person.employee_name || person.name || person.display_name)
          .filter(Boolean)
          .slice(0, 4);
      }
      if (tasks.ok) {
        const body = tasks.value?.data || {};
        next.pendingVerification = (body.pending_approval || []).length;
        next.completedTasks = (body.approved || []).length;
      }
      if (payroll.ok) {
        const approved = approvedPublicBatches(payroll.value?.data?.items || []);
        next.latestPayroll = approved[0] || null;
      }
      if (!issuesToday.ok && !weighing.ok && !team.ok && !payroll.ok) {
        setError(t("pinMgmt.loadFailed"));
      }
      setSnapshot(next);
      setLoading(false);
    });
    return () => controller.abort();
  }, [preview, t, today]);

  const data = snapshot || {};

  return (
    <OpsMobileShell>
      <OpsTopBar title={t("pinMgmt.dashboard")} onBack={onBack} onLock={onLock} />
      <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", pb: 2 }}>
        <Stack spacing={1.25} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {t("pinMgmt.today")} · {today} ET
          </Typography>
          {loading ? (
            <Stack alignItems="center" sx={{ py: 4 }}>
              <CircularProgress size={28} />
            </Stack>
          ) : null}
          {error ? <Alert severity="error">{error}</Alert> : null}
          {!loading ? (
            <>
              {data.issuesToday != null ? (
                <Card
                  title={t("pinMgmt.todayIssues")}
                  lines={[
                    `${t("pinMgmt.reportedToday")}: ${data.issuesToday}`,
                    `${t("pinMgmt.openToday")}: ${data.issuesOpenToday ?? 0}`,
                    data.outstanding != null
                      ? `${t("pinMgmt.outstanding")}: ${data.outstanding}`
                      : "",
                  ].filter(Boolean)}
                  action={t("pinMgmt.openIssues")}
                  onOpen={() => onOpen?.("issues")}
                />
              ) : null}
              {data.scans != null || data.activities != null ? (
                <Card
                  title={t("pinMgmt.production")}
                  lines={[
                    data.scans != null ? `${t("pinMgmt.weighingScans")}: ${data.scans}` : "",
                    data.scansWithEmployee != null
                      ? `${t("pinMgmt.withEmployee")}: ${data.scansWithEmployee}`
                      : "",
                    data.recordedSessions
                      ? `${t("pinMgmt.sessionContextShort")}: ${data.recordedSessions}`
                      : "",
                    data.activities != null ? `${t("pinMgmt.activities")}: ${data.activities}` : "",
                  ].filter(Boolean)}
                  action={t("pinMgmt.openScans")}
                  onOpen={() => onOpen?.("scan")}
                />
              ) : null}
              {data.working != null ? (
                <Card
                  title={t("pinMgmt.working")}
                  lines={[
                    `${t("pinMgmt.workingNow")}: ${data.working}`,
                    ...(data.workingNames || []),
                  ]}
                  action={t("pinMgmt.openTeam")}
                  onOpen={() => onOpen?.("team")}
                />
              ) : null}
              {data.pendingVerification != null ? (
                <Card
                  title={t("pinMgmt.tasks")}
                  lines={[
                    `${t("pinMgmt.pendingVerification")}: ${data.pendingVerification}`,
                    `${t("pinMgmt.completedTasks")}: ${data.completedTasks ?? 0}`,
                  ]}
                  action={t("pinMgmt.openTasks")}
                  onOpen={() => onOpen?.("tasks")}
                />
              ) : null}
              {data.latestPayroll ? (
                <Card
                  title={t("pinMgmt.latestPayroll")}
                  lines={[
                    data.latestPayroll.name,
                    `${data.latestPayroll.payPeriodStart} – ${data.latestPayroll.payPeriodEnd}`,
                    `${t("pinMgmt.grossWages")}: ${formatMoney(data.latestPayroll.grossWages)}`,
                    `${t("pinMgmt.payoutAmount")}: ${formatMoney(data.latestPayroll.payoutAmount)}`,
                    t("pinMgmt.payrollPeriodNote"),
                  ]}
                  action={t("pinMgmt.openPayroll")}
                  onOpen={() => onOpen?.("payroll")}
                />
              ) : null}
            </>
          ) : null}
        </Stack>
      </Box>
    </OpsMobileShell>
  );
}
