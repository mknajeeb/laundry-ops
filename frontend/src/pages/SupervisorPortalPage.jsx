import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Drawer,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import ManagementHubNav from "../components/management/ManagementHubNav";
import {
  createSupervisorAdjustment,
  getManagementTaskDashboard,
  getSupervisorDay,
  getSupervisorOverview,
  getSupervisorQualityTypes,
  getSupervisorQualityWeek,
  getSupervisorQualityWeights,
  getSupervisorTrainingAssignments,
  getSupervisorTrainingTemplates,
  reverseSupervisorAdjustment,
  reverseSupervisorQualityAssignment,
  saveSupervisorQualityAssignment,
  saveSupervisorQualityType,
  saveSupervisorQualityWeights,
  saveSupervisorTarget,
  saveSupervisorTrainingAssignments,
  saveSupervisorTrainingTemplate,
} from "../api";
import { CATEGORIES, etToday, formatNumber, formatRate, reconciliationCheck } from "../supervisor/supervisorFormat";

const NAVY = "#16192b";
const VIEWS = [
  ["overview", "Overview"],
  ["performance", "Performance"],
  ["quality", "Quality"],
  ["training", "Training"],
  ["tasks", "Tasks"],
];

const cardSx = {
  bgcolor: "#fff",
  border: "1px solid #e6e8ef",
  borderRadius: 2,
  p: 1.5,
  textAlign: "left",
};

function errorText(err, fallback) {
  return err?.response?.data?.error || err?.message || fallback;
}

function Kpi({ label, value, hint, onClick, active }) {
  return (
    <Box
      component={onClick ? "button" : "div"}
      type={onClick ? "button" : undefined}
      onClick={onClick}
      sx={{
        ...cardSx,
        cursor: onClick ? "pointer" : "default",
        minWidth: 0,
        outline: active ? `2px solid ${NAVY}` : "none",
      }}
    >
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 700 }}>{label}</Typography>
      <Typography sx={{ fontSize: 22, fontWeight: 800, color: NAVY, lineHeight: 1.2 }}>{value}</Typography>
      {hint ? <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.25 }}>{hint}</Typography> : null}
    </Box>
  );
}

export default function SupervisorPortalPage() {
  const [params, setParams] = useSearchParams();
  const view = VIEWS.some(([id]) => id === params.get("view")) ? params.get("view") : "overview";
  const date = params.get("date") || etToday();

  const setView = (next) => {
    const copy = new URLSearchParams(params);
    copy.set("view", next);
    if (!copy.get("date")) copy.set("date", date);
    setParams(copy, { replace: true });
  };
  const setDate = (next) => {
    const copy = new URLSearchParams(params);
    copy.set("date", next);
    copy.set("view", view);
    setParams(copy, { replace: true });
  };

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "#f4f6fb", pb: 4 }}>
      <ManagementHubNav activeId="supervisor" />
      <Box sx={{ px: { xs: 1.5, md: 3 }, pt: 2, maxWidth: 1180, mx: "auto" }}>
        <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={1} sx={{ mb: 1.5 }}>
          <Box>
            <Typography sx={{ fontSize: 22, fontWeight: 800, color: NAVY }}>Supervisor</Typography>
            <Typography sx={{ fontSize: 13, color: "#64748b" }}>
              Folding performance, quality, training, and task follow-up. Times are Eastern.
            </Typography>
          </Box>
          <TextField
            size="small"
            type="date"
            label="Business date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ width: { xs: "100%", sm: 180 }, bgcolor: "#fff" }}
          />
        </Stack>
        <Stack direction="row" spacing={0.75} sx={{ mb: 2, flexWrap: "wrap" }} role="tablist">
          {VIEWS.map(([id, label]) => (
            <Button
              key={id}
              role="tab"
              aria-selected={view === id}
              onClick={() => setView(id)}
              variant={view === id ? "contained" : "text"}
              sx={{
                textTransform: "none",
                fontWeight: 700,
                bgcolor: view === id ? NAVY : "transparent",
                color: view === id ? "#fff" : NAVY,
              }}
            >
              {label}
            </Button>
          ))}
        </Stack>
        {view === "overview" ? <OverviewView date={date} onOpen={setView} /> : null}
        {view === "performance" ? <PerformanceView date={date} /> : null}
        {view === "quality" ? <QualityView date={date} /> : null}
        {view === "training" ? <TrainingView date={date} /> : null}
        {view === "tasks" ? <TasksView date={date} /> : null}
      </Box>
    </Box>
  );
}

function OverviewView({ date, onOpen }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancel = false;
    setError("");
    getSupervisorOverview({ date })
      .then((res) => {
        if (!cancel) setData(res.data);
      })
      .catch((err) => {
        if (!cancel) setError(errorText(err, "Could not load the overview"));
      });
    return () => {
      cancel = true;
    };
  }, [date]);
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return <Typography color="text.secondary">Loading today’s picture…</Typography>;
  const check = reconciliationCheck(data.reconciliation);
  return (
    <Stack spacing={1.5}>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 1 }}>
        <Kpi label="Completed bags" value={formatNumber(data.volume?.completed_bags)} hint={check.holds ? "Fully accounted" : `${check.unaccounted} unaccounted`} onClick={() => onOpen("performance")} />
        <Kpi label="Approved speed" value={formatRate(data.approved_productivity?.approved_lbs_per_hour)} hint={`${formatNumber(data.approved_productivity?.approved_hours)} approved hours`} onClick={() => onOpen("performance")} />
        <Kpi label="Below target" value={data.below_target?.length || 0} onClick={() => onOpen("performance")} />
        <Kpi label="Pending sessions" value={data.pending_session_count || 0} onClick={() => onOpen("performance")} />
        <Kpi label="Quality incidents" value={data.quality?.incident_count ?? "—"} hint={data.quality?.week_start ? `Week of ${data.quality.week_start}` : ""} onClick={() => onOpen("quality")} />
        <Kpi label="Training overdue" value={data.training_due ?? "—"} onClick={() => onOpen("training")} />
        <Kpi label="Tasks to verify" value={data.tasks?.pending_verification ?? "—"} onClick={() => onOpen("tasks")} />
        <Kpi label="People on the floor" value={data.employees_working ?? 0} />
      </Box>
      <Box sx={cardSx}>
        <Typography sx={{ fontWeight: 800, color: NAVY, mb: 1 }}>Follow-up</Typography>
        {(data.follow_ups || []).length === 0 ? (
          <Typography sx={{ color: "#64748b" }}>Nothing is waiting on you for this day.</Typography>
        ) : (
          <Stack spacing={0.75}>
            {data.follow_ups.map((item) => (
              <Button key={item.label} onClick={() => onOpen(item.kind === "approval" ? "performance" : item.kind === "reconciliation" ? "performance" : item.kind)} sx={{ justifyContent: "flex-start", textTransform: "none", color: NAVY }}>
                {item.label}
              </Button>
            ))}
          </Stack>
        )}
        <Typography sx={{ mt: 1.5, fontSize: 12, color: "#64748b" }}>
          Overall scoring is off until management approves the weights. Auto-approval still uses its own threshold
          {data.approved_productivity?.target_lbs_per_hour != null ? ` (${data.approved_productivity.target_lbs_per_hour} lb/hr)` : ""}.
        </Typography>
      </Box>
    </Stack>
  );
}

function PerformanceView({ date }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("all");
  const [selected, setSelected] = useState(null);
  const load = useCallback(() => {
    setError("");
    return getSupervisorDay({ date })
      .then((res) => setData(res.data))
      .catch((err) => setError(errorText(err, "Could not load performance")));
  }, [date]);
  useEffect(() => {
    load();
  }, [load]);
  const bags = useMemo(() => {
    const rows = data?.reconciliation?.bags || [];
    if (category === "all") return rows;
    return rows.filter((bag) => bag.primary_category === category);
  }, [data, category]);
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return <Typography color="text.secondary">Loading performance…</Typography>;
  const check = reconciliationCheck(data.reconciliation);
  const counts = data.reconciliation.categories || {};
  return (
    <Stack spacing={1.5}>
      <Alert severity={check.holds ? "success" : "warning"}>
        {check.completed} completed bags, {check.accounted} accounted, {check.unaccounted} unaccounted.
        {data.achievement_target_source === "auto_approval_benchmark"
          ? " Achievement is using the auto-approval threshold until a separate scoring target is published."
          : " Achievement uses the published scoring target. Auto-approval is unchanged."}
      </Alert>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 1 }}>
        <Kpi label="Completed" value={check.completed} active={category === "all"} onClick={() => setCategory("all")} />
        {CATEGORIES.map(([key, label]) => (
          <Kpi key={key} label={label} value={counts[key] || 0} active={category === key} onClick={() => setCategory(key)} />
        ))}
        <Kpi label="Approved hours" value={formatNumber(data.approved_productivity?.approved_hours)} />
        <Kpi label="Approved team speed" value={formatRate(data.approved_productivity?.approved_lbs_per_hour)} />
        <Kpi label="Team average" value={formatRate(data.team?.average_lbs_per_hour)} hint={data.team?.comparison_reliable ? "Median shown separately" : "Too little data for a firm median"} />
        <Kpi label="Team median" value={formatRate(data.team?.median_lbs_per_hour)} />
      </Box>
      <Box sx={cardSx}>
        <Typography sx={{ fontWeight: 800, color: NAVY, mb: 1 }}>
          {category === "all" ? "Employees" : `${CATEGORIES.find(([key]) => key === category)?.[1] || category} bags`}
        </Typography>
        {category === "all" ? (
          <EmployeeTable employees={data.employees || []} onOpen={setSelected} />
        ) : (
          <BagTable bags={bags} />
        )}
      </Box>
      <Typography sx={{ fontSize: 13 }}>
        <a href="/management/performance">Hang Dry performance and bag moves stay on the existing performance screen.</a>
      </Typography>
      {data.access?.configure ? <TargetForm date={date} onSaved={load} /> : null}
      <Drawer anchor="right" open={Boolean(selected)} onClose={() => setSelected(null)}>
        {selected ? (
          <EmployeeDrawer employee={selected} date={date} onChanged={load} onClose={() => setSelected(null)} />
        ) : null}
      </Drawer>
    </Stack>
  );
}

function EmployeeTable({ employees, onOpen }) {
  if (!employees.length) return <Typography color="text.secondary">No folding employees for this day.</Typography>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          {["Employee", "Bags", "Pounds", "Eligible hours", "Rate", "Target", "Status"].map((label) => (
            <TableCell key={label} sx={{ fontWeight: 800 }}>{label}</TableCell>
          ))}
        </TableRow>
      </TableHead>
      <TableBody>
        {employees.map((employee) => (
          <TableRow key={`${employee.user_id}-${employee.employee}`} hover onClick={() => onOpen(employee)} sx={{ cursor: "pointer" }}>
            <TableCell>{employee.employee}</TableCell>
            <TableCell>{formatNumber(employee.bags)}</TableCell>
            <TableCell>{formatNumber(employee.pounds)}</TableCell>
            <TableCell>{formatNumber(employee.eligible_hours)}</TableCell>
            <TableCell>{formatRate(employee.reported_rate)}</TableCell>
            <TableCell>{employee.achievement_percent != null ? `${employee.achievement_percent}%` : "—"}</TableCell>
            <TableCell>{employee.excluded ? "Excluded" : employee.below_target ? "Below target" : "On track"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function BagTable({ bags }) {
  if (!bags.length) return <Typography color="text.secondary">No bags in this category.</Typography>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          {["Bag", "Order", "Completed", "Pounds", "Employee", "Session", "Why"].map((label) => (
            <TableCell key={label} sx={{ fontWeight: 800 }}>{label}</TableCell>
          ))}
        </TableRow>
      </TableHead>
      <TableBody>
        {bags.map((bag) => (
          <TableRow key={bag.bag_id}>
            <TableCell>{bag.bag_id}</TableCell>
            <TableCell>{bag.order_instance_id || bag.order_id || "—"}</TableCell>
            <TableCell>{bag.completion_at || "—"}</TableCell>
            <TableCell>{formatNumber(bag.pounds)}</TableCell>
            <TableCell>{bag.employee || "—"}</TableCell>
            <TableCell>{bag.session_id || "—"}</TableCell>
            <TableCell>{bag.classification_reason}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function EmployeeDrawer({ employee, date, onChanged, onClose }) {
  const [sessionId, setSessionId] = useState(employee.sessions?.[0]?.session_id || "");
  const [kind, setKind] = useState("eligible_duration");
  const [reason, setReason] = useState("");
  const [value, setValue] = useState("");
  const [role, setRole] = useState("SORT");
  const [error, setError] = useState("");
  const session = (employee.sessions || []).find((row) => String(row.session_id) === String(sessionId));
  async function submit(event) {
    event.preventDefault();
    setError("");
    const body = {
      date,
      kind,
      reason,
      session_id: kind === "day_manual_rate" ? undefined : sessionId,
      employee_name: employee.employee,
      employee_user_id: employee.user_id,
    };
    if (kind === "eligible_duration") body.eligible_hours = Number(value);
    if (kind === "eligible_percent") body.eligible_percent = Number(value);
    if (kind === "session_manual_rate" || kind === "day_manual_rate") body.manual_rate = Number(value);
    if (kind === "role_reallocation") {
      body.reallocated_hours = Number(value);
      body.reallocated_role_key = role;
    }
    try {
      await createSupervisorAdjustment(body);
      setReason("");
      await onChanged();
      onClose();
    } catch (err) {
      setError(errorText(err, "Could not save the adjustment"));
    }
  }
  return (
    <Box sx={{ width: { xs: "100vw", sm: 440 }, p: 2 }}>
      <Typography sx={{ fontSize: 18, fontWeight: 800, color: NAVY }}>{employee.employee}</Typography>
      <Typography sx={{ color: "#64748b", mb: 1 }}>
        Calculated {formatRate(employee.calculated_rate)} · Reported {formatRate(employee.reported_rate)} · {employee.rate_basis}
      </Typography>
      <Typography sx={{ fontSize: 13, mb: 1 }}>
        Score status: {employee.score?.status}. {employee.score?.reason}
      </Typography>
      {(employee.sessions || []).map((row) => (
        <Box key={row.session_id} sx={{ ...cardSx, mb: 1 }}>
          <Typography sx={{ fontWeight: 800 }}>{row.start_time || "—"} – {row.end_time || "—"}</Typography>
          <Typography sx={{ fontSize: 13, color: "#334155" }}>
            Recorded {formatNumber(row.original_hours)} h · Eligible {formatNumber(row.eligible_hours)} h · {formatNumber(row.reported_lbs)} lb · {formatRate(row.reported_rate)}
          </Typography>
          <Typography sx={{ fontSize: 13 }}>
            {row.publication_status} · {row.approval_source || row.reported_basis}
            {row.reallocated_role_key ? ` · ${formatNumber(row.eligible_hours)} h still in folding; ${row.reallocated_role_key} output ${row.destination_output_lbs} lb` : ""}
          </Typography>
          {(row.adjustments || []).map((adjustment) => (
            <Stack key={adjustment.id} direction="row" justifyContent="space-between" alignItems="center">
              <Typography sx={{ fontSize: 12 }}>{adjustment.kind}: {adjustment.reason}</Typography>
              {!adjustment.reversed_at ? (
                <Button size="small" onClick={() => reverseSupervisorAdjustment(adjustment.id, { reason: "Reversed from supervisor portal" }).then(onChanged)}>
                  Reverse
                </Button>
              ) : null}
            </Stack>
          ))}
        </Box>
      ))}
      <Box component="form" onSubmit={submit} sx={{ display: "grid", gap: 1 }}>
        <TextField select size="small" label="Session" value={sessionId} onChange={(event) => setSessionId(event.target.value)}>
          {(employee.sessions || []).map((row) => (
            <MenuItem key={row.session_id} value={row.session_id}>{row.session_id}</MenuItem>
          ))}
        </TextField>
        <TextField select size="small" label="Adjustment" value={kind} onChange={(event) => setKind(event.target.value)}>
          <MenuItem value="eligible_duration">Eligible hours</MenuItem>
          <MenuItem value="eligible_percent">Eligible percent</MenuItem>
          <MenuItem value="role_reallocation">Move time to another role</MenuItem>
          <MenuItem value="exclude">Exclude session</MenuItem>
          <MenuItem value="session_manual_rate">Approved session rate</MenuItem>
          <MenuItem value="day_manual_rate">Approved day rate</MenuItem>
        </TextField>
        {kind !== "exclude" ? <TextField size="small" label={kind === "role_reallocation" ? "Hours to move" : "Value"} value={value} onChange={(event) => setValue(event.target.value)} /> : null}
        {kind === "role_reallocation" ? (
          <TextField select size="small" label="Destination role" value={role} onChange={(event) => setRole(event.target.value)}>
            {["SORT", "WEIGH", "WASH", "DRY", "HD_OPERATOR", "HD_FOLDER", "GENERAL"].map((key) => (
              <MenuItem key={key} value={key}>{key}</MenuItem>
            ))}
          </TextField>
        ) : null}
        <TextField size="small" label="Reason" required value={reason} onChange={(event) => setReason(event.target.value)} />
        {error ? <Alert severity="error">{error}</Alert> : null}
        <Button type="submit" variant="contained" sx={{ bgcolor: NAVY, textTransform: "none" }}>Save adjustment</Button>
        {session ? (
          <Typography sx={{ fontSize: 12, color: "#64748b" }}>
            Original session stays {formatNumber(session.original_hours)} h and {formatNumber(session.original_lbs)} lb. This does not create bags.
          </Typography>
        ) : null}
      </Box>
    </Box>
  );
}

function TargetForm({ date, onSaved }) {
  const [target, setTarget] = useState("");
  const [message, setMessage] = useState("");
  return (
    <Box component="form" sx={{ ...cardSx, display: "grid", gap: 1 }} onSubmit={async (event) => {
      event.preventDefault();
      try {
        await saveSupervisorTarget({ role_key: "FOLDER", unit: "lb/hr", target_value: Number(target), effective_from: date, above_target_policy: "uncapped" });
        setMessage("Scoring target saved. Auto-approval threshold was not changed.");
        onSaved();
      } catch (err) {
        setMessage(errorText(err, "Could not save the target"));
      }
    }}>
      <Typography sx={{ fontWeight: 800, color: NAVY }}>Scoring target</Typography>
      <Typography sx={{ fontSize: 13, color: "#64748b" }}>Separate from the  auto-approval threshold. Historical days keep the target that was effective then.</Typography>
      <TextField size="small" label="Folding target lb/hr" value={target} onChange={(event) => setTarget(event.target.value)} />
      <Button type="submit" variant="outlined" sx={{ textTransform: "none", justifySelf: "start" }}>Publish scoring target</Button>
      {message ? <Typography sx={{ fontSize: 13 }}>{message}</Typography> : null}
    </Box>
  );
}

function QualityView({ date }) {
  const [data, setData] = useState(null);
  const [types, setTypes] = useState([]);
  const [weights, setWeights] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ employee_name: "", issue_type: "missing_item", quantity: 1, reference: "", notes: "", severity: "" });
  const load = useCallback(() => {
    return Promise.all([getSupervisorQualityWeek({ date }), getSupervisorQualityTypes(), getSupervisorQualityWeights()])
      .then(([week, typeRes, weightRes]) => {
        setData(week.data);
        setTypes(typeRes.data.types || []);
        setWeights(weightRes.data);
      })
      .catch((err) => setError(errorText(err, "Could not load quality")));
  }, [date]);
  useEffect(() => { load(); }, [load]);
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return <Typography color="text.secondary">Loading quality…</Typography>;
  return (
    <Stack spacing={1.5}>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "1fr 1fr 1fr" }, gap: 1 }}>
        <Kpi label="Incidents this week" value={data.totals?.incident_count ?? 0} hint={`Week of ${data.week_start}`} />
        <Kpi label="Issue types" value={types.filter((row) => row.active !== 0).length} />
        <Kpi label="Published weights" value={(weights?.versions || []).filter((row) => row.status === "published").length} />
      </Box>
      <Box component="form" sx={{ ...cardSx, display: "grid", gap: 1 }} onSubmit={async (event) => {
        event.preventDefault();
        try {
          await saveSupervisorQualityAssignment({
            week: date,
            issue_type: form.issue_type,
            quantity: Number(form.quantity),
            reference: form.reference,
            notes: form.notes,
            severity: form.severity || null,
            employees: [{ employee_name: form.employee_name, role_key: "GENERAL" }],
          });
          setForm({ ...form, employee_name: "", reference: "", notes: "" });
          load();
        } catch (err) {
          setError(errorText(err, "Could not assign the issue"));
        }
      }}>
        <Typography sx={{ fontWeight: 800, color: NAVY }}>Assign a confirmed issue</Typography>
        <Typography sx={{ fontSize: 13, color: "#64748b" }}>Responsibility is decided outside the app. The same reference counts as one incident.</Typography>
        {types.length === 0 ? (
          <Button onClick={() => saveSupervisorQualityType({ install_starter: true }).then(load)} sx={{ textTransform: "none", justifySelf: "start" }}>
            Install starter categories
          </Button>
        ) : null}
        <TextField size="small" label="Employee" value={form.employee_name} onChange={(event) => setForm({ ...form, employee_name: event.target.value })} required />
        <TextField select size="small" label="Issue type" value={form.issue_type} onChange={(event) => setForm({ ...form, issue_type: event.target.value })}>
          {(types.length ? types : [{ code: "missing_item", label: "Missing item" }]).map((row) => (
            <MenuItem key={row.code} value={row.code}>{row.label}</MenuItem>
          ))}
        </TextField>
        <TextField size="small" label="Quantity" type="number" value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} />
        <TextField size="small" label="Severity (optional)" value={form.severity} onChange={(event) => setForm({ ...form, severity: event.target.value })} />
        <TextField size="small" label="Order or Rinse issue reference" value={form.reference} onChange={(event) => setForm({ ...form, reference: event.target.value })} required />
        <TextField size="small" label="Notes" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
        <Button type="submit" variant="contained" sx={{ bgcolor: NAVY, textTransform: "none", justifySelf: "start" }}>Save assignment</Button>
      </Box>
      <Box sx={cardSx}>
        {(data.incidents || []).length === 0 ? <Typography color="text.secondary">No assignments this week.</Typography> : (
          <Table size="small">
            <TableHead>
              <TableRow>
                {["Reference", "Type", "Qty", "People", "Points", ""].map((label) => <TableCell key={label} sx={{ fontWeight: 800 }}>{label}</TableCell>)}
              </TableRow>
            </TableHead>
            <TableBody>
              {data.incidents.map((row) => (
                <TableRow key={row.id} sx={{ opacity: row.voided_at ? 0.45 : 1 }}>
                  <TableCell>{row.reference || row.incident_key}</TableCell>
                  <TableCell>{row.issue_type}</TableCell>
                  <TableCell>{row.quantity}</TableCell>
                  <TableCell>{(row.employees || []).map((employee) => employee.employee_name).filter(Boolean).join(", ") || "—"}</TableCell>
                  <TableCell>{row.points ?? "—"}</TableCell>
                  <TableCell>
                    {!row.voided_at ? (
                      <Button size="small" onClick={() => reverseSupervisorQualityAssignment(row.id, { reason: "Reversed from supervisor portal" }).then(load)}>Reverse</Button>
                    ) : "Reversed"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Box>
      <WeightForm weights={weights} date={date} onSaved={load} />
    </Stack>
  );
}

function WeightForm({ weights, date, onSaved }) {
  const [text, setText] = useState(JSON.stringify(weights?.illustrative_weights || {}, null, 2));
  const [message, setMessage] = useState("");
  return (
    <Box component="form" sx={{ ...cardSx, display: "grid", gap: 1 }} onSubmit={async (event) => {
      event.preventDefault();
      try {
        await saveSupervisorQualityWeights({ effective_from: date, status: "published", weights: JSON.parse(text), severity: weights?.illustrative_severity || {} });
        setMessage("Weight version published. Older incidents keep the version they were saved with.");
        onSaved();
      } catch (err) {
        setMessage(errorText(err, "Could not publish weights"));
      }
    }}>
      <Typography sx={{ fontWeight: 800, color: NAVY }}>Issue weights</Typography>
      <Typography sx={{ fontSize: 13, color: "#64748b" }}>Illustrative numbers are filled in. Publishing them is a management action and does not turn on the overall score.</Typography>
      <TextField size="small" multiline minRows={4} value={text} onChange={(event) => setText(event.target.value)} />
      <Button type="submit" variant="outlined" sx={{ textTransform: "none", justifySelf: "start" }}>Publish weight version</Button>
      {message ? <Typography sx={{ fontSize: 13 }}>{message}</Typography> : null}
    </Box>
  );
}

function TrainingView({ date }) {
  const [templates, setTemplates] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [items, setItems] = useState("Orientation\nPractical fold");
  const [trainee, setTrainee] = useState("");
  const [versionId, setVersionId] = useState("");
  const load = useCallback(() => {
    return Promise.all([getSupervisorTrainingTemplates(), getSupervisorTrainingAssignments()])
      .then(([templateRes, assignmentRes]) => {
        setTemplates(templateRes.data.templates || []);
        setAssignments(assignmentRes.data.assignments || []);
        setVersionId((current) => current || String(templateRes.data.templates?.[0]?.version_id || ""));
      })
      .catch((err) => setError(errorText(err, "Could not load training")));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (error) return <Alert severity="error">{error}</Alert>;
  return (
    <Stack spacing={1.5}>
      <Box component="form" sx={{ ...cardSx, display: "grid", gap: 1 }} onSubmit={async (event) => {
        event.preventDefault();
        try {
          await saveSupervisorTrainingTemplate({
            title,
            category: "onboarding",
            role_key: "FOLDER",
            practical_required: true,
            items: items.split("\n").map((label) => label.trim()).filter(Boolean),
          });
          setTitle("");
          load();
        } catch (err) {
          setError(errorText(err, "Could not save the template"));
        }
      }}>
        <Typography sx={{ fontWeight: 800, color: NAVY }}>Training template</Typography>
        <Typography sx={{ fontSize: 13, color: "#64748b" }}>A new version keeps old completions. Checklist completion does not by itself prove competency.</Typography>
        <TextField size="small" label="Title" value={title} onChange={(event) => setTitle(event.target.value)} />
        <TextField size="small" multiline minRows={3} label="Checklist, one step per line" value={items} onChange={(event) => setItems(event.target.value)} />
        <Button type="submit" variant="outlined" sx={{ textTransform: "none", justifySelf: "start" }}>Save new version</Button>
      </Box>
      <Box component="form" sx={{ ...cardSx, display: "grid", gap: 1 }} onSubmit={async (event) => {
        event.preventDefault();
        try {
          await saveSupervisorTrainingAssignments({
            version_id: Number(versionId),
            trainee_user_id: Number(trainee),
            reason: "onboarding",
            assigned_on: date,
            due_on: date,
          });
          load();
        } catch (err) {
          setError(errorText(err, "Could not assign training"));
        }
      }}>
        <Typography sx={{ fontWeight: 800, color: NAVY }}>Assign training</Typography>
        <TextField select size="small" label="Module" value={versionId} onChange={(event) => setVersionId(event.target.value)}>
          {templates.map((row) => (
            <MenuItem key={row.version_id} value={String(row.version_id)}>{row.title} v{row.version_number}</MenuItem>
          ))}
        </TextField>
        <TextField size="small" label="Trainee user id" value={trainee} onChange={(event) => setTrainee(event.target.value)} />
        <Button type="submit" variant="contained" sx={{ bgcolor: NAVY, textTransform: "none", justifySelf: "start" }}>Assign</Button>
      </Box>
      <Box sx={cardSx}>
        {assignments.length === 0 ? <Typography color="text.secondary">No assignments yet.</Typography> : (
          <Table size="small">
            <TableHead>
              <TableRow>
                {["Module", "Trainee", "Reason", "Due", "Status", ""].map((label) => <TableCell key={label} sx={{ fontWeight: 800 }}>{label}</TableCell>)}
              </TableRow>
            </TableHead>
            <TableBody>
              {assignments.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.title} v{row.version_number}</TableCell>
                  <TableCell>{row.trainee_user_id}</TableCell>
                  <TableCell>{row.reason}</TableCell>
                  <TableCell>{row.due_on || "—"}</TableCell>
                  <TableCell>{row.status}</TableCell>
                  <TableCell />
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Box>
    </Stack>
  );
}

function TasksView({ date }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancel = false;
    getManagementTaskDashboard({ date })
      .then((res) => {
        if (!cancel) setData(res.data);
      })
      .catch((err) => {
        if (!cancel) setError(errorText(err, "Could not load tasks"));
      });
    return () => {
      cancel = true;
    };
  }, [date]);
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return <Typography color="text.secondary">Loading tasks…</Typography>;
  const metrics = data.metrics || {};
  const waiting = (data.shared_assignments || []).filter((row) =>
    ["waiting", "partial", "pending_verification"].includes(String(row.verification_status || row.status || ""))
    || String(row.status || "").toLowerCase().includes("verif")
  );
  return (
    <Stack spacing={1.5}>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 1 }}>
        <Kpi label="Assigned" value={metrics.total_assigned ?? "—"} />
        <Kpi label="In progress" value={metrics.in_progress ?? "—"} />
        <Kpi label="Awaiting verification" value={metrics.pending_verification ?? "—"} />
        <Kpi label="Overdue" value={metrics.overdue ?? "—"} />
      </Box>
      <Box sx={cardSx}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography sx={{ fontWeight: 800, color: NAVY }}>Needs a supervisor</Typography>
          <Button href="/management/tasks" sx={{ textTransform: "none" }}>Open task dashboard</Button>
        </Stack>
        <Typography sx={{ fontSize: 13, color: "#64748b", mb: 1 }}>
          Shared activity groups, timers, and verification still live in the task dashboard. This list is the same queue.
        </Typography>
        {waiting.length === 0 ? <Typography color="text.secondary">No tasks are waiting for verification.</Typography> : (
          <Table size="small">
            <TableBody>
              {waiting.slice(0, 20).map((row) => (
                <TableRow key={row.assignment_key || row.responsibility_id || row.role}>
                  <TableCell>{row.task_name || row.role_label || row.role}</TableCell>
                  <TableCell>{row.status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Box>
    </Stack>
  );
}
