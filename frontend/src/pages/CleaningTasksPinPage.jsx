import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import {
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
  attendancePinSwitchRole,
} from "../api";
import { OpsMobileShell, OpsTopBar, OPS_MOBILE } from "../opsMobile";
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

function statusLabel(status) {
  switch (status) {
    case "pending":
      return "Pending";
    case "overdue":
      return "Overdue";
    case "in_progress":
      return "In progress";
    case "pending_approval":
    case "pending_verification":
      return "Pending Verification";
    case "approved":
    case "verified":
      return "Verified";
    case "completed":
      return "Completed";
    case "rejected":
      return "Needs redo";
    case "not_started":
      return "Not started";
    case "incomplete":
      return "Incomplete";
    case "partial":
      return "Needs attention";
    default:
      return status || "";
  }
}

function PartnerLines({ partners, executionMode, assignedNames }) {
  const names = (assignedNames || []).filter(Boolean);
  if (executionMode !== "shared" || (!partners?.length && names.length < 2)) return null;
  const working = (partners || []).filter((partner) => partner.state === "working").map((partner) => partner.name);
  const waiting = (partners || []).filter((partner) => partner.state === "assigned").map((partner) => partner.name);
  const finished = (partners || []).filter((partner) => partner.state === "finished").map((partner) => partner.name);
  const headline = names.length ? names.join(", ") : (partners || []).map((partner) => partner.name).join(", ");
  return (
    <Box sx={{ mt: 0.5 }}>
      <Typography variant="body2" sx={{ fontWeight: 700, color: OPS_MOBILE.navy }}>
        {`Assigned with: ${headline}`}
      </Typography>
      {working.length ? (
        <Typography variant="caption" display="block" sx={{ color: "#166534", fontWeight: 700 }}>
          {`Working now: ${working.join(", ")}`}
        </Typography>
      ) : null}
      {waiting.length ? (
        <Typography variant="caption" display="block" color="text.secondary">
          {`Not started: ${waiting.join(", ")}`}
        </Typography>
      ) : null}
      {finished.length ? (
        <Typography variant="caption" display="block" color="text.secondary">
          {`Finished: ${finished.join(", ")}`}
        </Typography>
      ) : null}
    </Box>
  );
}

function TaskCard({ task, onStart, onCompleteUntimed, busy }) {
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
      <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
        {task.role_label || task.role}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {isGroup ? "Activity Group" : task.category_name || task.category_code || "Task"}
        {" · "}
        {task.timing_label || "Anytime"}
        {names ? ` · ${names}` : ""}
        {isGroup && itemCount ? ` · ${itemCount} tasks` : ""}
        {!isGroup && needsInput ? " · Input required" : ""}
        {untimed ? " · Untimed" : ""}
      </Typography>
      {isGroup && (task.group_items || []).length ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
          {(task.group_items || []).map((it) => it.task_name || it.task_code).join(" · ")}
        </Typography>
      ) : null}
      <PartnerLines
        partners={task.partners}
        executionMode={task.execution_mode}
        assignedNames={task.assigned_employees}
      />
      <Typography variant="caption" sx={{ fontWeight: 700, color: "#b45309" }}>
        {statusLabel(task.status)}
      </Typography>
      {canAct ? (
        <Button
          fullWidth
          variant="contained"
          disabled={busy}
          onClick={() => (untimed ? onCompleteUntimed(task) : onStart(task))}
          sx={{ mt: 1.25, fontWeight: 800, textTransform: "none" }}
        >
          {isGroup
            ? "Start Group"
            : untimed
              ? needsInput
                ? "Complete with input"
                : "Mark Complete"
              : "Start Task"}
        </Button>
      ) : null}
    </Box>
  );
}

/**
 * PIN Tasks — My Tasks (by category) + Tasks to Verify + checklist review.
 */
export default function CleaningTasksPinPage() {
  const { orgSlug: routeSlug } = useParams();
  const navigate = useNavigate();
  const slug = sanitizeSlug(routeSlug);
  const hub = useMemo(() => loadPinHubSession(), []);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [verifyQueue, setVerifyQueue] = useState([]);
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

  const activeSchema = active?.input_schema || inputDraftTask?.input_schema || [];

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
      setError("Enter your PIN again.");
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
      if (!body.ok) throw new Error(body.error || "Could not load tasks");
      setData(body);
      if (body.open_activity) {
        setActive(body.open_activity);
        setCompleted(null);
        setInputDraftTask(null);
        resetInputs(body.open_activity.input_schema || []);
      }
      const vbody = verifyRes?.data || {};
      setVerifyQueue(vbody.ok ? vbody.pending_verification || [] : []);
      setChecklists(vbody.ok ? vbody.checklists || [] : []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not load tasks");
    } finally {
      setLoading(false);
    }
  }, [hub, slug]);

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
      if (!body.ok) throw new Error(body.error || "Could not start task");
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
      setError(e?.response?.data?.error || e?.message || "Could not start task");
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
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not complete task");
      setInputDraftTask(null);
      if ((body.activity?.next_options || []).length) {
        setCompleted(body.activity);
        setActive(null);
      } else {
        await load();
      }
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not complete task");
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
      if (!body.ok) throw new Error(body.error || "Could not verify");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not verify");
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
      if (!body.ok) throw new Error(body.error || "Could not reject");
      setRejectId(null);
      setRejectReason("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not reject");
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
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not complete task");
      setCompleted(body.activity);
      setActive(null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not complete task");
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
      if (!body.ok) throw new Error(body.error || "Could not check off task");
      setActive(body.activity);
      setCheckoffCode(null);
      resetInputs([]);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not check off task");
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
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not complete group");
      setCompleted(body.activity);
      setActive(null);
      setCheckoffCode(null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not complete group");
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
      if (!body.ok) throw new Error(body.error || "Could not verify checklist");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not verify checklist");
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
      if (!body.ok) throw new Error(body.error || "Could not reject item");
      setRejectId(null);
      setRejectReason("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not reject item");
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
      if (!body.ok) throw new Error(body.error || "Could not continue");
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
          throw new Error(switchBody.error || "Could not resume previous role");
        }
        navigate(pinHubMenuPath(slug), { replace: true });
        return;
      }
      navigate(`/attendance/role/${encodeURIComponent(slug)}?from=hub`, { replace: true });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not continue");
    } finally {
      setBusy(false);
    }
  };

  if (!hub?.token) {
    return (
      <OpsMobileShell>
        <Alert severity="warning">Enter your PIN again.</Alert>
        <Button onClick={lock}>Back to PIN</Button>
      </OpsMobileShell>
    );
  }

  return (
    <OpsMobileShell>
      <OpsTopBar
        title="Tasks"
        onBack={goHub}
        onLock={lock}
        identity={hub.employee_first_name || hub.employee_name || ""}
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
            Task Completed!
          </Typography>
          <Box sx={{ textAlign: "center" }}>
            <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              {completed.group?.name || completed.role_label || completed.role}
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
                ? "Waiting for verification"
                : "All set"}
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
            What&apos;s Next?
          </Typography>
          <Stack spacing={1.5}>
            <Button
              fullWidth
              variant="contained"
              disabled={busy}
              onClick={() => chooseNext("resume_work")}
              sx={{ fontWeight: 800, textTransform: "none", py: 1.75, fontSize: "1.05rem" }}
            >
              Resume Work
            </Button>
            <Button
              fullWidth
              variant="outlined"
              disabled={busy}
              onClick={() => chooseNext("change_role")}
              sx={{ fontWeight: 800, textTransform: "none", py: 1.75, fontSize: "1.05rem" }}
            >
              Switch Role
            </Button>
            <Button
              fullWidth
              variant="outlined"
              disabled={busy}
              onClick={() => chooseNext("take_break")}
              sx={{ fontWeight: 800, textTransform: "none", py: 1.75, fontSize: "1.05rem" }}
            >
              Take Break
            </Button>
          </Stack>
        </Stack>
      ) : inputDraftTask ? (
        <Stack spacing={1.5}>
          <Typography variant="h6" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
            {inputDraftTask.role_label || inputDraftTask.role}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Enter required information to complete this task.
          </Typography>
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
            Submit & Complete
          </Button>
          <Button disabled={busy} onClick={() => setInputDraftTask(null)} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
        </Stack>
      ) : active?.is_activity_group || active?.activity_kind === "group" ? (
        <Stack spacing={1.5} alignItems="stretch">
          <Typography variant="h6" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
            {active.group?.name || active.role_label || active.role}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {active.execution_mode === "shared" || active.group?.execution_mode === "shared"
              ? "Shared Activity · your timer · one checklist"
              : "Activity Group · your timer"}
          </Typography>
          <PartnerLines
            partners={active.partners}
            executionMode={active.execution_mode || active.group?.execution_mode}
            assignedNames={active.assigned_employees || active.group?.assigned_employees}
          />
          {active.group?.checklist_complete || active.shared_checklist_complete ? (
            <Typography variant="body2" sx={{ fontWeight: 700, color: "#166534" }}>
              Shared checklist complete
              {active.status === "in_progress" ? " — finish your timer when ready" : ""}
            </Typography>
          ) : null}
          <Typography sx={{ fontSize: "2.4rem", fontWeight: 900, textAlign: "center", color: OPS_MOBILE.navy }}>
            {formatElapsed(active.started_at, nowMs)}
          </Typography>
          <Stack spacing={1}>
            {(active.group?.items || []).map((item) => {
              const done = item.status === "completed";
              const editing = checkoffCode === item.task_code;
              return (
                <Box
                  key={item.task_code}
                  sx={{
                    p: 1.25,
                    borderRadius: 2,
                    border: `1px solid ${OPS_MOBILE.border}`,
                    bgcolor: done ? "#f0fdf4" : "#fff",
                  }}
                >
                  <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
                    {item.task_name || item.task_code}
                    {item.required ? "" : " (optional)"}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {done
                      ? item.completed_by_name
                        ? `Checked off by ${item.completed_by_name}`
                        : "Checked off"
                      : "Pending"}
                  </Typography>
                  {!done ? (
                    <>
                      {editing ? (
                        <TaskCompletionInputs
                          schema={item.input_schema || []}
                          values={inputValues}
                          remarks={inputRemarks}
                          onChangeValues={setInputValues}
                          onChangeRemarks={setInputRemarks}
                          disabled={busy}
                        />
                      ) : null}
                      <Button
                        fullWidth
                        variant="outlined"
                        disabled={busy}
                        onClick={() => checkoffGroupItem(item)}
                        sx={{ mt: 1, fontWeight: 800, textTransform: "none" }}
                      >
                        {editing ? "Save check-off" : "Check off"}
                      </Button>
                    </>
                  ) : null}
                </Box>
              );
            })}
          </Stack>
          <Button
            variant="contained"
            color="success"
            disabled={busy || !active.group?.can_complete_group}
            onClick={completeGroup}
            sx={{ fontWeight: 800, textTransform: "none", py: 1.5 }}
          >
            {active.execution_mode === "shared" || active.group?.execution_mode === "shared"
              ? "Finish My Participation"
              : "Complete Group"}
          </Button>
        </Stack>
      ) : active ? (
        <Stack spacing={1.5} alignItems="stretch">
          <Typography variant="h6" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
            {active.role_label || active.role}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {active.timing_label || "Anytime"}
          </Typography>
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
            Complete
          </Button>
        </Stack>
      ) : (
        <Stack spacing={2.5}>
          <Box>
            <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              My Tasks
            </Typography>
            {(data?.tasks_by_category || []).length ? (
              <Stack spacing={2}>
                {(data.tasks_by_category || []).map((group) => (
                  <Box key={group.category_code}>
                    <Typography sx={{ fontWeight: 800, mb: 1, color: OPS_MOBILE.navy }}>
                      {group.category_name}
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
                No tasks assigned today.
              </Typography>
            )}
          </Box>

          <Box>
            <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              Tasks to Verify ({verifyQueue.length})
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
                      {item.role_label || item.role}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {item.category_name || item.category_code || "Task"} · Completed by{" "}
                      {item.employee_name || `User #${item.user_id}`} ·{" "}
                      {item.original_business_date || item.business_date}
                    </Typography>
                    {formatCompletionInput(item.completion_input) ? (
                      <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                        Input: {formatCompletionInput(item.completion_input)}
                      </Typography>
                    ) : null}
                    {rejectId === item.id ? (
                      <Stack spacing={1} sx={{ mt: 1 }}>
                        <input
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          placeholder="Rejection reason (required)"
                          style={{ padding: 8, borderRadius: 8, border: "1px solid #cbd5e1" }}
                        />
                        <Stack direction="row" spacing={1}>
                          <Button size="small" variant="contained" color="warning" disabled={busy} onClick={rejectItem}>
                            Reject
                          </Button>
                          <Button size="small" onClick={() => setRejectId(null)}>
                            Cancel
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
                          Verify
                        </Button>
                        <Button
                          size="small"
                          color="warning"
                          disabled={busy}
                          onClick={() => setRejectId(item.id)}
                          sx={{ textTransform: "none", fontWeight: 800 }}
                        >
                          Needs redo
                        </Button>
                      </Stack>
                    )}
                  </Box>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  None waiting for you
                </Typography>
              )}
            </Stack>
          </Box>

          <Box>
            <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy, fontSize: "1.1rem" }}>
              Checklists ({checklists.length})
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
                      Original date {cl.business_date} · {statusLabel(cl.status)} ·{" "}
                      {cl.required_done}/{cl.required_total} required done
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
                                {group.group_name} · {statusLabel(group.status)} ·{" "}
                                {group.required_done}/{group.required_total}
                                {group.completion_pct != null ? ` · ${group.completion_pct}%` : ""}
                              </Typography>
                              <Stack spacing={0.5} sx={{ mt: 0.75 }}>
                                {(group.items || []).map((item) => (
                                  <Box key={item.task_code} sx={{ pl: 0.5 }}>
                                    <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                      {item.task_label} · {statusLabel(item.status)}
                                      {item.required ? "" : " (optional)"}
                                    </Typography>
                                    {(item.activities || []).map((act) => (
                                      <Box key={act.id} sx={{ ml: 1, mb: 0.5 }}>
                                        <Typography variant="caption" display="block" color="text.secondary">
                                          {act.employee_name} ·{" "}
                                          {statusLabel(act.display_status || act.status)}
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
                                                placeholder="Rejection reason"
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
                                                  Reject item
                                                </Button>
                                                <Button size="small" onClick={() => setRejectId(null)}>
                                                  Cancel
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
                                              Flag item
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
                                  Verify group
                                </Button>
                              ) : null}
                            </Box>
                          ))
                        : (cl.items || []).map((item) => (
                            <Box key={item.task_code} sx={{ pl: 0.5 }}>
                              <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                {item.task_label} · {statusLabel(item.status)}
                                {item.required ? "" : " (optional)"}
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
                        Verify entire checklist
                      </Button>
                    ) : (
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                        Complete all required items (and clear rejections) before verifying the checklist.
                      </Typography>
                    )}
                  </Box>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No checklists awaiting review
                </Typography>
              )}
            </Stack>
          </Box>
        </Stack>
      )}
    </OpsMobileShell>
  );
}
