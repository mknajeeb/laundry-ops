import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  attendancePinCleaningTasksAddRemark,
  attendancePinCleaningTasksApprove,
  attendancePinCleaningTasksChecklistRejectItem,
  attendancePinCleaningTasksChecklistVerify,
  attendancePinCleaningTasksComplete,
  attendancePinCleaningTasksCompleteGroup,
  attendancePinCleaningTasksCompleteUntimed,
  attendancePinCleaningTasksGroupCheckoff,
  attendancePinCleaningTasksList,
  attendancePinCleaningTasksNext,
  attendancePinCleaningTasksReject,
  attendancePinCleaningTasksStart,
  attendancePinCleaningTasksVerifyQueue,
  attendancePinResolveUnassignedVerification,
  attendancePinSwitchRole,
} from "../api";
import { OpsLocaleToggle, OpsMobileShell, OpsTopBar, OPS_MOBILE } from "../opsMobile";
import { useI18n } from "../i18n/I18nContext";
import { categoryLabel, localizedConfigured, localizedInstruction, taskStatusLabel } from "../components/tasks/taskEmployeeI18n";
import ActivityRemarks from "../components/tasks/ActivityRemarks";
import InstructionHint from "../components/tasks/InstructionHint";
import SharedActivityChecklist from "../components/tasks/SharedActivityChecklist";
import TaskCompletionInputs, {
  emptyInputValues,
  formatCompletionInput,
  validateInputClient,
} from "../opsMobile/TaskCompletionInputs";
import {
  clearPinHubSession,
  loadPinHubSession,
  pinHubMenuPath,
} from "../utils/pinHubSession";

function sanitizeSlug(raw) {
  if (!raw) return "";
  try {
    return decodeURIComponent(String(raw))
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 64);
  } catch {
    return "";
  }
}

function formatElapsed(startedAt, nowMs) {
  if (!startedAt) return "—";
  const start = new Date(String(startedAt).includes("T") ? startedAt : String(startedAt).replace(" ", "T"));
  if (Number.isNaN(start.getTime())) return "—";
  const sec = Math.max(0, Math.floor((nowMs - start.getTime()) / 1000));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function statusLabel(status, t) {
  return taskStatusLabel(t, status);
}

function PartnerLines({ partners, executionMode, assignedNames }) {
  const { t } = useI18n();
  const names = (assignedNames || []).filter(Boolean);
  if (executionMode !== "shared" || (!partners?.length && names.length < 2)) return null;
  const working = (partners || []).filter((partner) => partner.state === "working").map((partner) => partner.name);
  const waiting = (partners || []).filter((partner) => partner.state === "assigned").map((partner) => partner.name);
  const finished = (partners || []).filter((partner) => partner.state === "finished").map((partner) => partner.name);
  const excused = (partners || []).filter((partner) => partner.state === "excused").map((partner) => partner.name);
  const headline = names.length ? names.join(", ") : (partners || []).map((partner) => partner.name).join(", ");
  return (
    <Box sx={{ mt: 0.5 }}>
      <Typography variant="body2" sx={{ fontWeight: 700, color: OPS_MOBILE.navy }}>
        {t("tasks.pin.assignedWith", { names: headline })}
      </Typography>
      {working.length ? (
        <Typography variant="caption" display="block" sx={{ color: "#166534", fontWeight: 700 }}>
          {t("tasks.pin.workingNow", { names: working.join(", ") })}
        </Typography>
      ) : null}
      {waiting.length ? (
        <Typography variant="caption" display="block" color="text.secondary">
          {t("tasks.pin.notStartedNames", { names: waiting.join(", ") })}
        </Typography>
      ) : null}
      {finished.length ? (
        <Typography variant="caption" display="block" color="text.secondary">
          {t("tasks.pin.finishedNames", { names: finished.join(", ") })}
        </Typography>
      ) : null}
      {excused.length ? (
        <Typography variant="caption" display="block" color="text.secondary">
          {t("tasks.pin.excusedNames", { names: excused.join(", ") })}
        </Typography>
      ) : null}
    </Box>
  );
}

function TaskCard({ task, onStart, onCompleteUntimed, busy }) {
  const { t, locale } = useI18n();
  const taskName = localizedConfigured(
    { name: task.role_label || task.role, name_es: task.name_es },
    locale,
    "name",
    "name_es",
  );
  const taskInstructions = localizedInstruction(task, locale);
  const names = (task.assigned_employees || []).join(" + ");
  const canAct =
    task.status === "pending" || task.status === "overdue" || task.status === "rejected";
  const isGroup = Boolean(task.is_activity_group);
  const untimed = !isGroup && task.timer_enabled === false;
  const needsInput = task.completion_type === "input_required";
  const itemCount = task.group_item_count || (task.group_items || []).length || 0;
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: `1px solid ${OPS_MOBILE.border}`,
        bgcolor: "#fff",
      }}
    >
      <Stack direction="row" alignItems="center" spacing={0.5}>
        <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
          {taskName || task.role}
        </Typography>
        <InstructionHint text={taskInstructions} label={t("tasks.pin.instructions")} />
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {task.timing_label || t("tasks.pin.anytime")}
        {names ? ` · ${names}` : ""}
      </Typography>
      <Typography variant="body2" sx={{ mt: 0.35, fontWeight: 700 }}>
        {isGroup && itemCount ? `${t("tasks.pin.tasksCount", { count: itemCount })} · ` : ""}
        {statusLabel(task.status, t)}
      </Typography>
      {canAct ? (
        <Button
          fullWidth
          variant="contained"
          disabled={busy}
          onClick={() => (untimed ? onCompleteUntimed(task) : onStart(task))}
          sx={{ mt: 1.25, fontWeight: 800, textTransform: "none" }}
        >
          {untimed
            ? needsInput
              ? t("tasks.pin.completeWithInput")
              : t("tasks.pin.markComplete")
            : task.status === "rejected"
              ? t("tasks.pin.resumeActivity")
              : t("tasks.pin.startActivity")}
        </Button>
      ) : null}
    </Box>
  );
}

/**
 * PIN Tasks — My Tasks (by category) + Tasks to Verify + checklist review.
 */
export default function CleaningTasksPinPage() {
  const { t, locale } = useI18n();
  const { orgSlug: routeSlug } = useParams();
  const navigate = useNavigate();
  const slug = sanitizeSlug(routeSlug);
  const hub = useMemo(() => loadPinHubSession(), []);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [verifyQueue, setVerifyQueue] = useState([]);
  const [awaitingVerifier, setAwaitingVerifier] = useState([]);
  const [resolveId, setResolveId] = useState(null);
  const [resolveReason, setResolveReason] = useState("");
  const [checklists, setChecklists] = useState([]);
  const [active, setActive] = useState(null);
  const [inputDraftTask, setInputDraftTask] = useState(null);
  const [completed, setCompleted] = useState(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [rejectId, setRejectId] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const [inputValues, setInputValues] = useState({});
  const [inputRemarks, setInputRemarks] = useState("");
  const [checkoffCode, setCheckoffCode] = useState(null);
  const [workRemark, setWorkRemark] = useState("");

  const activeSchema = active?.input_schema || inputDraftTask?.input_schema || [];
  const completedName = localizedConfigured(
    {
      name: completed?.group?.name || completed?.role_label || completed?.role || "",
      name_es: completed?.name_es || completed?.group?.name_es || "",
    },
    locale,
    "name",
    "name_es",
  );
  const draftName = localizedConfigured(
    { name: inputDraftTask?.role_label || inputDraftTask?.role || "", name_es: inputDraftTask?.name_es || "" },
    locale,
    "name",
    "name_es",
  );
  const draftInstructions = localizedInstruction(inputDraftTask || {}, locale);
  const activeGroupName = localizedConfigured(
    {
      name: active?.group?.name || active?.role_label || active?.role || "",
      name_es: active?.name_es || active?.group?.name_es || "",
    },
    locale,
    "name",
    "name_es",
  );
  const activeGroupInstructions =
    localizedInstruction(active || {}, locale) || localizedInstruction(active?.group || {}, locale);
  const activeName = localizedConfigured(
    { name: active?.role_label || active?.role || "", name_es: active?.name_es || "" },
    locale,
    "name",
    "name_es",
  );
  const activeInstructions = localizedInstruction(active || {}, locale);

  const goHub = useCallback(() => {
    navigate(pinHubMenuPath(slug || hub?.organization_slug || ""), { replace: true });
  }, [navigate, slug, hub?.organization_slug]);

  const lock = useCallback(() => {
    clearPinHubSession();
    navigate(`/pin/${encodeURIComponent(slug || hub?.organization_slug || "")}`, { replace: true });
  }, [navigate, slug, hub?.organization_slug]);

  const resetInputs = (schema) => {
    setInputValues(emptyInputValues(schema));
    setInputRemarks("");
  };

  const load = useCallback(async () => {
    if (!hub?.token || !slug) {
      setError(t("tasks.pin.enterPin"));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [res, verifyRes] = await Promise.all([
        attendancePinCleaningTasksList(slug, hub.pin, { hubToken: hub.token }),
        attendancePinCleaningTasksVerifyQueue(slug, hub.pin, { hubToken: hub.token }),
      ]);
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.loadTasks"));
      setData(body);
      if (body.open_activity) {
        setActive(body.open_activity);
        setCompleted(null);
        setInputDraftTask(null);
        resetInputs(body.open_activity.input_schema || []);
      } else if (body.shared_checklist_followup) {
        // Timer finished but required shared checklist still open — keep check-off reachable.
        setActive(body.shared_checklist_followup);
        setCompleted(null);
        setInputDraftTask(null);
        resetInputs([]);
      }
      const vbody = verifyRes?.data || {};
      setVerifyQueue(vbody.ok ? vbody.pending_verification || [] : []);
      setAwaitingVerifier(vbody.ok ? vbody.awaiting_schedule_verifier || [] : []);
      setChecklists(vbody.ok ? vbody.checklists || [] : []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.loadTasks"));
    } finally {
      setLoading(false);
    }
  }, [hub, slug, t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!active?.started_at) return undefined;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active?.started_at]);

  // Shared Activity Groups: poll open activity so collaborator checkoffs appear without a manual refresh.
  useEffect(() => {
    const shared =
      active?.execution_mode === "shared" ||
      active?.group?.execution_mode === "shared" ||
      active?.shared_session_id != null;
    if (!shared || !active?.id || !hub?.pin || completed) return undefined;
    let cancelled = false;
    const sync = async () => {
      try {
        const res = await attendancePinCleaningTasksList(slug, hub.pin, { hubToken: hub.token });
        const body = res?.data || {};
        if (cancelled || !body.ok || !body.open_activity) return;
        const next = body.open_activity;
        if (Number(next.id) !== Number(active.id)) return;
        setActive((prev) => {
          if (!prev || Number(prev.id) !== Number(next.id)) return prev;
          return {
            ...prev,
            ...next,
            group: next.group || prev.group,
            shared_checklist_complete: next.shared_checklist_complete,
            shared_session_status: next.shared_session_status,
          };
        });
      } catch {
        /* keep last known checklist; next tick retries */
      }
    };
    const id = window.setInterval(sync, 2500);
    void sync();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [
    active?.id,
    active?.execution_mode,
    active?.group?.execution_mode,
    active?.shared_session_id,
    completed,
    hub?.pin,
    hub?.token,
    slug,
  ]);

  const buildCompletionInput = (schema) => {
    const err = validateInputClient(schema, inputValues, inputRemarks);
    if (err) throw new Error(err);
    return { values: inputValues, remarks: inputRemarks || undefined };
  };

  const startTask = async (task) => {
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksStart(slug, hub.pin, {
        hubToken: hub.token,
        responsibility_id: task.responsibility_id,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.startFailed"));
      const activity = {
        ...body.activity,
        input_schema: body.activity?.input_schema || task.input_schema || [],
        completion_type: body.activity?.completion_type || task.completion_type,
      };
      setActive(activity);
      setCompleted(null);
      setInputDraftTask(null);
      resetInputs(activity.input_schema || []);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.startFailed"));
    } finally {
      setBusy(false);
    }
  };

  const beginUntimed = (task) => {
    if (task.completion_type === "input_required") {
      setInputDraftTask(task);
      resetInputs(task.input_schema || []);
      setError("");
      return;
    }
    void completeUntimed(task, null);
  };

  const completeUntimed = async (task, completionInput) => {
    setBusy(true);
    setError("");
    try {
      let payload = completionInput;
      if (task.completion_type === "input_required" && !payload) {
        payload = buildCompletionInput(task.input_schema || []);
      }
      const res = await attendancePinCleaningTasksCompleteUntimed(slug, hub.pin, {
        hubToken: hub.token,
        responsibility_id: task.responsibility_id,
        completion_input: payload,
        remark: workRemark,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.completeFailed"));
      setInputDraftTask(null);
      if ((body.activity?.next_options || []).length) {
        setCompleted(body.activity);
        setActive(null);
      } else {
        await load();
      }
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.completeFailed"));
    } finally {
      setBusy(false);
    }
  };

  const verifyItem = async (activityId) => {
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksApprove(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: activityId,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.verifyFailed"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.verifyFailed"));
    } finally {
      setBusy(false);
    }
  };

  const resolveUnassigned = async () => {
    if (!resolveId) return;
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinResolveUnassignedVerification(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: resolveId,
        reason: resolveReason,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.verifyFailed"));
      setResolveId(null);
      setResolveReason("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.verifyFailed"));
    } finally {
      setBusy(false);
    }
  };

  const rejectItem = async () => {
    if (!rejectId) return;
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksReject(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: rejectId,
        reason: rejectReason,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.rejectFailed"));
      setRejectId(null);
      setRejectReason("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.rejectFailed"));
    } finally {
      setBusy(false);
    }
  };

  const completeTask = async () => {
    if (!active?.id) return;
    setBusy(true);
    setError("");
    try {
      let completion_input;
      if (active.completion_type === "input_required" || (activeSchema || []).length) {
        completion_input = buildCompletionInput(activeSchema);
      }
      const res = await attendancePinCleaningTasksComplete(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: active.id,
        completion_input,
        remark: workRemark,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.completeFailed"));
      setCompleted(body.activity);
      setActive(null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.completeFailed"));
    } finally {
      setBusy(false);
    }
  };

  const checkoffGroupItem = async (item) => {
    if (!active?.id || !item?.task_code) return;
    const needs = item.completion_type === "input_required" || (item.input_schema || []).length > 0;
    if (needs && checkoffCode !== item.task_code) {
      setCheckoffCode(item.task_code);
      resetInputs(item.input_schema || []);
      setError("");
      return;
    }
    setBusy(true);
    setError("");
    try {
      let completion_input;
      if (needs) {
        completion_input = buildCompletionInput(item.input_schema || []);
      }
      const res = await attendancePinCleaningTasksGroupCheckoff(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: active.id,
        task_code: item.task_code,
        completion_input,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.checkoffFailed"));
      const next = body.activity;
      if (
        active.checklist_followup_only &&
        (next?.shared_checklist_complete || next?.group?.checklist_complete)
      ) {
        setActive(null);
        setCompleted(next);
        await load();
      } else {
        setActive(next);
      }
      setCheckoffCode(null);
      resetInputs([]);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.checkoffFailed"));
    } finally {
      setBusy(false);
    }
  };

  const addActivityRemark = async (body, taskCode) => {
    if (!active?.id) return;
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksAddRemark(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: active.id,
        body,
        task_code: taskCode || "",
      });
      const payload = res?.data || {};
      if (!payload.ok) throw new Error(payload.error || t("tasks.pin.remarkFailed"));
      setActive((current) =>
        current ? { ...current, remarks: payload.remarks || [], remark_count: (payload.remarks || []).length } : current
      );
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.remarkFailed"));
    } finally {
      setBusy(false);
    }
  };

  const completeGroup = async () => {
    if (!active?.id) return;
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksCompleteGroup(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: active.id,
        remark: workRemark,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.groupFailed"));
      setCompleted(body.activity);
      setActive(null);
      setCheckoffCode(null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.groupFailed"));
    } finally {
      setBusy(false);
    }
  };

  const verifyChecklist = async (cl, groupId = null) => {
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksChecklistVerify(slug, hub.pin, {
        hubToken: hub.token,
        checklist_id: cl.checklist_id,
        business_date: cl.business_date,
        group_id: groupId,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.checklistVerifyFailed"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.checklistVerifyFailed"));
    } finally {
      setBusy(false);
    }
  };

  const rejectChecklistActivity = async (activityId) => {
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksChecklistRejectItem(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: activityId,
        reason: rejectReason,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.rejectItemFailed"));
      setRejectId(null);
      setRejectReason("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.rejectItemFailed"));
    } finally {
      setBusy(false);
    }
  };

  const chooseNext = async (choice) => {
    if (!completed?.id) return;
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksNext(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: completed.id,
        choice,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.continueFailed"));
      const pausedCat = body.paused_category_id ?? completed.paused_category_id;
      const pausedRole = body.paused_role_id ?? completed.paused_role_id;
      setCompleted(null);
      if (choice === "take_break") {
        navigate(pinHubMenuPath(slug), { replace: true });
        return;
      }
      if (
        choice === "resume_work" &&
        pausedCat != null &&
        pausedRole != null &&
        String(pausedCat) &&
        String(pausedRole)
      ) {
        const switchRes = await attendancePinSwitchRole(slug, hub.pin, {
          hubToken: hub.token,
          category_id: pausedCat,
          role_id: pausedRole,
        });
        const switchBody = switchRes?.data || {};
        if (!switchBody.ok) {
          throw new Error(switchBody.error || t("tasks.pin.resumeRoleFailed"));
        }
        navigate(pinHubMenuPath(slug), { replace: true });
        return;
      }
      navigate(`/attendance/role/${encodeURIComponent(slug)}?from=hub`, { replace: true });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.continueFailed"));
    } finally {
      setBusy(false);
    }
  };

  if (!hub?.token) {
    return (
      <OpsMobileShell>
        <Alert severity="warning">{t("tasks.pin.enterPin")}</Alert>
        <Button onClick={lock}>{t("tasks.pin.backToPin")}</Button>
      </OpsMobileShell>
    );
  }

  return (
    <OpsMobileShell>
      <OpsTopBar
        title={t("tasks.pin.title")}
        onBack={goHub}
        onLock={lock}
        lockLabel={t("mobileOps.lock")}
        identity={hub.employee_first_name || hub.employee_name || ""}
        right={<OpsLocaleToggle />}
      />
      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : completed ? (
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography
            sx={{
              fontWeight: 900,
              fontSize: "1.75rem",
              lineHeight: 1.2,
              color: OPS_MOBILE.navy,
              textAlign: "center",
            }}
          >
            {t("tasks.pin.completed")}
          </Typography>
          <Box sx={{ textAlign: "center" }}>
            <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              {completedName}
            </Typography>
            <Typography variant="body1" color="text.secondary" sx={{ mt: 0.5 }}>
              {completed.verification_required ||
              completed.status === "pending_approval" ||
              completed.status === "pending_verification" ||
              (completed.group?.items || []).some(
                (it) =>
                  it.verification_required ||
                  it.status === "pending_approval" ||
                  it.status === "pending_verification",
              )
                ? t("tasks.pin.waitingVerification")
                : t("tasks.pin.allSet")}
            </Typography>
          </Box>
          <Typography
            sx={{
              fontWeight: 900,
              fontSize: "1.25rem",
              color: OPS_MOBILE.navy,
              textAlign: "center",
              pt: 1,
            }}
          >
            {t("tasks.pin.whatsNext")}
          </Typography>
          <Stack spacing={1.5}>
            <Button
              fullWidth
              variant="contained"
              disabled={busy}
              onClick={() => chooseNext("resume_work")}
              sx={{ fontWeight: 800, textTransform: "none", py: 1.75, fontSize: "1.05rem" }}
            >
              {t("tasks.pin.resumeWork")}
            </Button>
            <Button
              fullWidth
              variant="outlined"
              disabled={busy}
              onClick={() => chooseNext("change_role")}
              sx={{ fontWeight: 800, textTransform: "none", py: 1.75, fontSize: "1.05rem" }}
            >
              {t("tasks.pin.switchRole")}
            </Button>
            <Button
              fullWidth
              variant="outlined"
              disabled={busy}
              onClick={() => chooseNext("take_break")}
              sx={{ fontWeight: 800, textTransform: "none", py: 1.75, fontSize: "1.05rem" }}
            >
              {t("tasks.pin.takeBreak")}
            </Button>
          </Stack>
        </Stack>
      ) : inputDraftTask ? (
        <Stack spacing={1.5}>
          <Typography variant="h6" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
            {draftName}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t("tasks.pin.enterInfo")}
          </Typography>
          {draftInstructions || inputDraftTask.remarks ? (
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
              {draftInstructions || inputDraftTask.remarks}
            </Typography>
          ) : null}
          <TextField
            size="small"
            fullWidth
            label={t("tasks.pin.remarkOptional")}
            value={workRemark}
            onChange={(e) => setWorkRemark(e.target.value)}
          />
          <TaskCompletionInputs
            schema={inputDraftTask.input_schema || []}
            values={inputValues}
            remarks={inputRemarks}
            onChangeValues={setInputValues}
            onChangeRemarks={setInputRemarks}
            disabled={busy}
          />
          <Button
            variant="contained"
            color="success"
            disabled={busy}
            onClick={() => completeUntimed(inputDraftTask)}
            sx={{ fontWeight: 800, textTransform: "none", py: 1.5 }}
          >
            {t("tasks.pin.submitComplete")}
          </Button>
          <Button disabled={busy} onClick={() => setInputDraftTask(null)} sx={{ textTransform: "none" }}>
            {t("tasks.pin.cancel")}
          </Button>
        </Stack>
      ) : active?.is_activity_group || active?.activity_kind === "group" ? (
        <Stack spacing={1.5} alignItems="stretch">
          <Stack direction="row" alignItems="center" spacing={0.5}>
            <Typography variant="h6" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
              {activeGroupName}
            </Typography>
            <InstructionHint
              text={activeGroupInstructions}
              label={t("tasks.pin.instructions")}
            />
          </Stack>
          <Typography variant="body2" color="text.secondary">
            {active.execution_mode === "shared" || active.group?.execution_mode === "shared"
              ? t("tasks.pin.sharedActivity")
              : t("tasks.pin.groupTimer")}
          </Typography>
          <PartnerLines
            partners={active.partners}
            executionMode={active.execution_mode || active.group?.execution_mode}
            assignedNames={active.assigned_employees || active.group?.assigned_employees}
          />
          {active.group?.checklist_complete || active.shared_checklist_complete ? (
            <Typography variant="body2" sx={{ fontWeight: 700, color: "#166534" }}>
              {t("tasks.pin.checklistComplete")}
              {active.status === "in_progress" ? ` ${t("tasks.pin.finishTimer")}` : ""}
            </Typography>
          ) : active.checklist_followup_only ? (
            <Typography variant="body2" sx={{ fontWeight: 700, color: OPS_MOBILE.navy }}>
              {t("tasks.pin.timerFinished")}
            </Typography>
          ) : null}
          {active.checklist_followup_only ? null : (
            <Typography sx={{ fontSize: "2.4rem", fontWeight: 900, textAlign: "center", color: OPS_MOBILE.navy }}>
              {formatElapsed(active.started_at, nowMs)}
            </Typography>
          )}
          <SharedActivityChecklist
            items={active.group?.items || []}
            userId={active.user_id}
            busy={busy}
            editingCode={checkoffCode}
            inputValues={inputValues}
            inputRemarks={inputRemarks}
            onChangeValues={setInputValues}
            onChangeRemarks={setInputRemarks}
            onCheckoff={checkoffGroupItem}
          />
          {active.checklist_followup_only ? null : (
            <>
            <ActivityRemarks
              remarks={active.remarks || []}
              items={active.group?.items || []}
              busy={busy}
              onAdd={addActivityRemark}
            />
            <Button
              variant="contained"
              color="success"
              disabled={
                busy ||
                active.group?.can_finish_participation === false ||
                active.group?.can_complete_group === false
              }
              onClick={completeGroup}
              sx={{ fontWeight: 800, textTransform: "none", py: 1.5 }}
            >
              {active.execution_mode === "shared" || active.group?.execution_mode === "shared"
                ? t("tasks.pin.finishParticipation")
                : t("tasks.pin.completeGroup")}
            </Button>
            </>
          )}
        </Stack>
      ) : active ? (
        <Stack spacing={1.5} alignItems="stretch">
          <Stack direction="row" alignItems="center" spacing={0.5}>
            <Typography variant="h6" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
              {activeName}
            </Typography>
            <InstructionHint text={activeInstructions} label={t("tasks.pin.instructions")} />
          </Stack>
          <Typography variant="body2" color="text.secondary">
            {active.timing_label || t("tasks.pin.anytime")}
          </Typography>
          <ActivityRemarks remarks={active.remarks || []} busy={busy} onAdd={addActivityRemark} />
          <Typography sx={{ fontSize: "2.4rem", fontWeight: 900, textAlign: "center", color: OPS_MOBILE.navy }}>
            {formatElapsed(active.started_at, nowMs)}
          </Typography>
          {(active.completion_type === "input_required" || (activeSchema || []).length > 0) && (
            <TaskCompletionInputs
              schema={activeSchema}
              values={inputValues}
              remarks={inputRemarks}
              onChangeValues={setInputValues}
              onChangeRemarks={setInputRemarks}
              disabled={busy}
            />
          )}
          <Button
            variant="contained"
            color="success"
            disabled={busy}
            onClick={completeTask}
            sx={{ fontWeight: 800, textTransform: "none", py: 1.5 }}
          >
            {t("tasks.pin.complete")}
          </Button>
        </Stack>
      ) : (
        <Stack spacing={2.5}>
          <Box>
            <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              {t("tasks.pin.myTasks")}
            </Typography>
            {(data?.tasks_by_category || []).length ? (
              <Stack spacing={2}>
                {(data.tasks_by_category || []).map((group) => (
                  <Box key={group.category_code}>
                    <Typography sx={{ fontWeight: 800, mb: 1, color: OPS_MOBILE.navy }}>
                      {categoryLabel(t, group.category_code, group.category_name)}
                    </Typography>
                    <Stack spacing={1}>
                      {(group.tasks || []).map((task) => (
                        <TaskCard
                          key={`${task.responsibility_id}-${task.status}`}
                          task={task}
                          onStart={startTask}
                          onCompleteUntimed={beginUntimed}
                          busy={busy}
                        />
                      ))}
                    </Stack>
                  </Box>
                ))}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                {t("tasks.pin.noTasks")}
              </Typography>
            )}
          </Box>

          <Box>
            <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              {t("tasks.pin.toVerify", { count: verifyQueue.length })}
            </Typography>
            <Stack spacing={1}>
              {verifyQueue.length ? (
                verifyQueue.map((item) => (
                  <Box
                    key={item.id}
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      border: `1px solid ${OPS_MOBILE.border}`,
                      bgcolor: "#fff",
                    }}
                  >
                    <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
                      {item.verification_queue_kind === "previous_shift" ? `${t("tasks.dashboard.previousShift")} · ` : ""}
                      {item.role_label || item.role}
                      {item.verification_overdue ? ` · ${t("tasks.pin.status.overdue")}` : ""}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {categoryLabel(t, item.category_code, item.category_name) || t("tasks.pin.task")} ·{" "}
                      {t("tasks.pin.completedBy", { name: item.employee_name || `User #${item.user_id}` })} ·{" "}
                      {item.original_business_date || item.business_date}
                    </Typography>
                    {formatCompletionInput(item.completion_input) ? (
                      <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                        {t("tasks.pin.input", { value: formatCompletionInput(item.completion_input) })}
                      </Typography>
                    ) : null}
                    {rejectId === item.id ? (
                      <Stack spacing={1} sx={{ mt: 1 }}>
                        <input
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          placeholder={t("tasks.pin.rejectReasonRequired")}
                          style={{ padding: 8, borderRadius: 8, border: "1px solid #cbd5e1" }}
                        />
                        <Stack direction="row" spacing={1}>
                          <Button size="small" variant="contained" color="warning" disabled={busy} onClick={rejectItem}>
                            {t("tasks.pin.reject")}
                          </Button>
                          <Button size="small" onClick={() => setRejectId(null)}>
                            {t("tasks.pin.cancel")}
                          </Button>
                        </Stack>
                      </Stack>
                    ) : (
                      <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                        <Button
                          size="small"
                          variant="contained"
                          disabled={busy}
                          onClick={() => verifyItem(item.id)}
                          sx={{ textTransform: "none", fontWeight: 800 }}
                        >
                          {t("tasks.pin.verify")}
                        </Button>
                        <Button
                          size="small"
                          color="warning"
                          disabled={busy}
                          onClick={() => setRejectId(item.id)}
                          sx={{ textTransform: "none", fontWeight: 800 }}
                        >
                          {t("tasks.pin.needsRedo")}
                        </Button>
                      </Stack>
                    )}
                  </Box>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t("tasks.pin.noneWaiting")}
                </Typography>
              )}
            </Stack>
          </Box>

          {awaitingVerifier.length ? (
            <Box>
              <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
                {t("tasks.pin.awaitingVerifier")}
              </Typography>
              <Stack spacing={1}>
                {awaitingVerifier.map((item) => (
                  <Box
                    key={`awaiting-${item.id}`}
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      border: `1px solid ${OPS_MOBILE.border}`,
                      bgcolor: "#fff",
                    }}
                  >
                    <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
                      {item.verification_queue_kind === "previous_shift"
                        ? `${t("tasks.dashboard.previousShift")} · `
                        : ""}
                      {item.role_label || item.role}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t("tasks.pin.completedBy", { name: item.employee_name || `User #${item.user_id}` })} ·{" "}
                      {item.original_business_date || item.business_date}
                    </Typography>
                    {resolveId === item.id ? (
                      <Stack spacing={1} sx={{ mt: 1 }}>
                        <input
                          value={resolveReason}
                          onChange={(e) => setResolveReason(e.target.value)}
                          placeholder={t("tasks.pin.resolveReason")}
                          style={{ padding: 8, borderRadius: 8, border: "1px solid #cbd5e1" }}
                        />
                        <Stack direction="row" spacing={1}>
                          <Button size="small" variant="contained" disabled={busy} onClick={resolveUnassigned}>
                            {t("tasks.pin.resolveVerification")}
                          </Button>
                          <Button size="small" onClick={() => setResolveId(null)}>
                            {t("tasks.pin.cancel")}
                          </Button>
                        </Stack>
                      </Stack>
                    ) : (
                      <Button
                        size="small"
                        sx={{ mt: 1, textTransform: "none", fontWeight: 800 }}
                        disabled={busy}
                        onClick={() => {
                          setResolveId(item.id);
                          setResolveReason("");
                        }}
                      >
                        {t("tasks.pin.resolveVerification")}
                      </Button>
                    )}
                  </Box>
                ))}
              </Stack>
            </Box>
          ) : null}

          <Box>
            <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              {t("tasks.pin.checklists", { count: checklists.length })}
            </Typography>
            <Stack spacing={1.25}>
              {checklists.length ? (
                checklists.map((cl) => (
                  <Box
                    key={`${cl.checklist_id}-${cl.business_date}`}
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      border: `1px solid ${OPS_MOBILE.border}`,
                      bgcolor: "#fff",
                    }}
                  >
                    <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
                      {cl.checklist_name}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t("tasks.pin.originalDate", { date: cl.business_date })} · {statusLabel(cl.status, t)} ·{" "}
                      {t("tasks.pin.requiredDone", { done: cl.required_done, total: cl.required_total })}
                      {cl.completion_pct != null ? ` · ${cl.completion_pct}%` : ""}
                    </Typography>
                    <Stack spacing={1} sx={{ mt: 1 }}>
                      {(cl.groups || []).length
                        ? (cl.groups || []).map((group) => (
                            <Box
                              key={`g-${group.group_id || group.group_name}`}
                              sx={{
                                p: 1,
                                borderRadius: 1.5,
                                border: `1px solid ${OPS_MOBILE.border}`,
                                bgcolor: "#f8fafc",
                              }}
                            >
                              <Typography variant="body2" sx={{ fontWeight: 800 }}>
                                {group.group_name} · {statusLabel(group.status, t)} ·{" "}
                                {group.required_done}/{group.required_total}
                                {group.completion_pct != null ? ` · ${group.completion_pct}%` : ""}
                              </Typography>
                              <Stack spacing={0.5} sx={{ mt: 0.75 }}>
                                {(group.items || []).map((item) => (
                                  <Box key={item.task_code} sx={{ pl: 0.5 }}>
                                    <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                      {item.task_label} · {statusLabel(item.status, t)}
                                      {item.required ? "" : ` ${t("tasks.pin.optionalParen")}`}
                                    </Typography>
                                    {(item.activities || []).map((act) => (
                                      <Box key={act.id} sx={{ ml: 1, mb: 0.5 }}>
                                        <Typography variant="caption" display="block" color="text.secondary">
                                          {act.employee_name} ·{" "}
                                          {statusLabel(act.display_status || act.status, t)}
                                          {formatCompletionInput(act.completion_input)
                                            ? ` · ${formatCompletionInput(act.completion_input)}`
                                            : ""}
                                        </Typography>
                                        {act.status === "pending_approval" ||
                                        act.status === "pending_verification" ? (
                                          rejectId === `cl-${act.id}` ? (
                                            <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                                              <input
                                                value={rejectReason}
                                                onChange={(e) => setRejectReason(e.target.value)}
                                                placeholder={t("tasks.pin.rejectReason")}
                                                style={{
                                                  padding: 6,
                                                  borderRadius: 6,
                                                  border: "1px solid #cbd5e1",
                                                }}
                                              />
                                              <Stack direction="row" spacing={1}>
                                                <Button
                                                  size="small"
                                                  color="warning"
                                                  disabled={busy}
                                                  onClick={() => rejectChecklistActivity(act.id)}
                                                >
                                                  {t("tasks.pin.rejectItem")}
                                                </Button>
                                                <Button size="small" onClick={() => setRejectId(null)}>
                                                  {t("tasks.pin.cancel")}
                                                </Button>
                                              </Stack>
                                            </Stack>
                                          ) : (
                                            <Button
                                              size="small"
                                              color="warning"
                                              disabled={busy}
                                              onClick={() => setRejectId(`cl-${act.id}`)}
                                              sx={{ textTransform: "none" }}
                                            >
                                              {t("tasks.pin.flagItem")}
                                            </Button>
                                          )
                                        ) : null}
                                      </Box>
                                    ))}
                                  </Box>
                                ))}
                              </Stack>
                              {group.can_verify_group && group.group_id != null ? (
                                <Button
                                  fullWidth
                                  size="small"
                                  variant="outlined"
                                  disabled={busy}
                                  onClick={() => verifyChecklist(cl, group.group_id)}
                                  sx={{ mt: 1, fontWeight: 700, textTransform: "none" }}
                                >
                                  {t("tasks.pin.verifyGroup")}
                                </Button>
                              ) : null}
                            </Box>
                          ))
                        : (cl.items || []).map((item) => (
                            <Box key={item.task_code} sx={{ pl: 0.5 }}>
                              <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                {item.task_label} · {statusLabel(item.status, t)}
                                {item.required ? "" : ` ${t("tasks.pin.optionalParen")}`}
                              </Typography>
                            </Box>
                          ))}
                    </Stack>
                    {cl.can_verify_all ? (
                      <Button
                        fullWidth
                        variant="contained"
                        disabled={busy}
                        onClick={() => verifyChecklist(cl)}
                        sx={{ mt: 1.25, fontWeight: 800, textTransform: "none" }}
                      >
                        {t("tasks.pin.verifyChecklist")}
                      </Button>
                    ) : (
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                        {t("tasks.pin.completeRequired")}
                      </Typography>
                    )}
                  </Box>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t("tasks.pin.noChecklists")}
                </Typography>
              )}
            </Stack>
          </Box>
        </Stack>
      )}
    </OpsMobileShell>
  );
}
