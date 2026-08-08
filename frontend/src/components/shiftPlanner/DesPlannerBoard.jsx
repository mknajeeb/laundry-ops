import { Fragment, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { BATCH_LIMIT_MODES, FOLD_RATE_MODES, ROLE_OPTIONS } from "../../shiftPlanner/constants";
import { formatBottleneck, newEmployee, newOrder } from "../../shiftPlanner/plannerHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const sectionPaper = {
  p: 2,
  borderRadius: 2,
  border: `1px solid ${VEEWASH_DASHBOARD.border || "#d7e0ea"}`,
  bgcolor: "#fff",
};

function Section({ title, subtitle, children }) {
  return (
    <Paper elevation={0} sx={sectionPaper}>
      <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 0.25 }}>
        {title}
      </Typography>
      {subtitle ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {subtitle}
        </Typography>
      ) : null}
      {children}
    </Paper>
  );
}

function NumField({ label, value, onChange, min, step, sx }) {
  return (
    <TextField
      size="small"
      label={label}
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      inputProps={{ min, step }}
      sx={{ minWidth: 140, ...sx }}
    />
  );
}

function SummaryCards({ summary }) {
  if (!summary) return null;
  const cards = [
    ["Bags ready by target", summary.bags_ready_by_target],
    ["Pounds ready by target", summary.pounds_ready_by_target],
    ["Bags folded by target", summary.bags_folded_by_target],
    ["Pounds folded by target", summary.pounds_folded_by_target],
    ["First batch ready", summary.first_batch_ready_time],
    ["Last batch ready", summary.last_batch_ready_time],
    ["Final completion", summary.final_completion_time],
    ["Washer utilization", `${summary.washer_utilization_pct ?? "—"}%`],
    ["Dryer utilization", `${summary.dryer_utilization_pct ?? "—"}%`],
    ["Folder utilization", `${summary.folder_utilization_pct ?? "—"}%`],
    ["Washer-person util.", `${summary.washer_person_utilization_pct ?? "—"}%`],
    ["Employee handling util.", `${summary.employee_handling_utilization_pct ?? "—"}%`],
    ["Avg ready wait (folder)", `${summary.avg_ready_bag_wait_for_folder_min ?? "—"} min`],
    ["Primary bottleneck", formatBottleneck(summary.primary_bottleneck)],
    ["Secondary bottleneck", formatBottleneck(summary.secondary_bottleneck)],
  ];
  return (
    <Grid container spacing={1}>
      {cards.map(([label, value]) => (
        <Grid item xs={6} sm={4} md={3} lg={2} key={label}>
          <Box sx={{ p: 1.25, bgcolor: "#f4f8fc", borderRadius: 1.5, minHeight: 72 }}>
            <Typography variant="caption" color="text.secondary">
              {label}
            </Typography>
            <Typography variant="subtitle1" fontWeight={800}>
              {value ?? "—"}
            </Typography>
          </Box>
        </Grid>
      ))}
    </Grid>
  );
}

export function ShiftSetupSection({ inputs, onChange }) {
  return (
    <Section title="A. Shift setup" subtitle="Times, bag volume, average weight, machines and capacities.">
      <Stack direction="row" flexWrap="wrap" gap={1.5}>
        <TextField size="small" label="Shift start" value={inputs.start_time} onChange={(e) => onChange("start_time", e.target.value)} />
        <TextField size="small" label="Target time" value={inputs.target_time} onChange={(e) => onChange("target_time", e.target.value)} />
        <NumField label="Number of bags" value={inputs.bag_count} onChange={(v) => onChange("bag_count", v)} min={1} />
        <NumField label="Average bag weight (lb)" value={inputs.avg_lbs_per_bag} onChange={(v) => onChange("avg_lbs_per_bag", v)} min={0.1} step={0.1} />
        <NumField label="Batch size (bags)" value={inputs.batch_size} onChange={(v) => onChange("batch_size", v)} min={1} />
        <NumField label="Washers" value={inputs.washer_count} onChange={(v) => onChange("washer_count", v)} min={1} />
        <NumField label="Dryers" value={inputs.dryer_count} onChange={(v) => onChange("dryer_count", v)} min={1} />
        <NumField label="Washer capacity (lb)" value={inputs.washer_capacity_lb} onChange={(v) => onChange("washer_capacity_lb", v)} min={1} />
        <NumField label="Dryer capacity (lb)" value={inputs.dryer_capacity_lb} onChange={(v) => onChange("dryer_capacity_lb", v)} min={1} />
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>Batch sizing</InputLabel>
          <Select
            label="Batch sizing"
            value={inputs.batch_limit_mode}
            onChange={(e) => onChange("batch_limit_mode", e.target.value)}
          >
            {BATCH_LIMIT_MODES.map((m) => (
              <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
      <TextField
        sx={{ mt: 1.5 }}
        size="small"
        fullWidth
        label="Optional individual bag weights (comma-separated lb)"
        value={inputs.bag_weights_text}
        onChange={(e) => onChange("bag_weights_text", e.target.value)}
        helperText="When set, these override average weight for bag 1…n."
      />
    </Section>
  );
}

export function EmployeesSection({ inputs, onChange, onAddStaff, onOpenAddStaff }) {
  const employees = inputs.employees || [];

  const updateEmployee = (id, patch) => {
    onChange(
      "employees",
      employees.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    );
  };

  const removeEmployee = (id) => {
    onChange(
      "employees",
      employees.filter((e) => e.id !== id),
    );
  };

  return (
    <Section
      title="B. Employees and role assignments"
      subtitle="Time-based roster for weighers, sorters, washer persons, folders and helpers. Inject labor at any time."
    >
      <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 1.5 }}>
        <FormControlLabel
          control={<Checkbox checked={Boolean(inputs.weigher_washer_same)} onChange={(e) => onChange("weigher_washer_same", e.target.checked)} />}
          label="Weigher and washer are the same employee"
        />
        <FormControlLabel
          control={<Checkbox checked={Boolean(inputs.weigher_sorter_same)} onChange={(e) => onChange("weigher_sorter_same", e.target.checked)} />}
          label="Weigher and sorter are the same person"
        />
        <FormControlLabel
          control={<Checkbox checked={Boolean(inputs.sorter_washer_same)} onChange={(e) => onChange("sorter_washer_same", e.target.checked)} />}
          label="Sorter and washer person are the same person"
        />
        <FormControlLabel
          control={<Checkbox checked={Boolean(inputs.washer_folder_same)} onChange={(e) => onChange("washer_folder_same", e.target.checked)} />}
          label="Washer person and folder are the same person"
        />
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button variant="contained" onClick={onOpenAddStaff} sx={{ textTransform: "none", fontWeight: 700 }}>
          + Add Staff During Shift
        </Button>
        <Button
          variant="outlined"
          onClick={() => onAddStaff(newEmployee("sorter", "9:15 AM"))}
          sx={{ textTransform: "none" }}
        >
          Quick: sorter at 9:15 AM
        </Button>
        <Button
          variant="outlined"
          onClick={() => onAddStaff(newEmployee("washer", "8:30 AM"))}
          sx={{ textTransform: "none" }}
        >
          Quick: washer at 8:30 AM
        </Button>
      </Stack>

      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Employee</TableCell>
              <TableCell>Primary role</TableCell>
              <TableCell>Start</TableCell>
              <TableCell>End</TableCell>
              <TableCell>Secondary roles</TableCell>
              <TableCell>Role schedule</TableCell>
              <TableCell>Rate</TableCell>
              <TableCell>Active</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {employees.map((e) => (
              <TableRow key={e.id}>
                <TableCell>
                  <TextField size="small" value={e.name} onChange={(ev) => updateEmployee(e.id, { name: ev.target.value })} />
                </TableCell>
                <TableCell>
                  <Select
                    size="small"
                    value={e.primary_role}
                    onChange={(ev) => updateEmployee(e.id, { primary_role: ev.target.value })}
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <MenuItem key={r.value} value={r.value}>{r.label}</MenuItem>
                    ))}
                  </Select>
                </TableCell>
                <TableCell>
                  <TextField size="small" value={e.start_time || ""} onChange={(ev) => updateEmployee(e.id, { start_time: ev.target.value })} sx={{ width: 110 }} />
                </TableCell>
                <TableCell>
                  <TextField size="small" value={e.end_time || ""} onChange={(ev) => updateEmployee(e.id, { end_time: ev.target.value })} sx={{ width: 110 }} />
                </TableCell>
                <TableCell>
                  <TextField
                    size="small"
                    placeholder="washer, sorter"
                    value={(e.secondary_roles || []).join(", ")}
                    onChange={(ev) =>
                      updateEmployee(e.id, {
                        secondary_roles: ev.target.value
                          .split(",")
                          .map((x) => x.trim().toLowerCase())
                          .filter(Boolean),
                      })
                    }
                    sx={{ width: 140 }}
                  />
                </TableCell>
                <TableCell>
                  <TextField
                    size="small"
                    placeholder="sorter 7:00-9:30; washer 9:30-11:00"
                    value={(e.role_schedule || [])
                      .map((w) => `${w.role} ${w.from || w.start_time || ""}-${w.to || w.end_time || ""}`)
                      .join("; ")}
                    onChange={(ev) => {
                      const schedule = ev.target.value
                        .split(";")
                        .map((part) => part.trim())
                        .filter(Boolean)
                        .map((part) => {
                          const m = part.match(/^(\w+)\s+(.+?)\s*-\s*(.+)$/i);
                          if (!m) return null;
                          return { role: m[1].toLowerCase(), from: m[2].trim(), to: m[3].trim() };
                        })
                        .filter(Boolean);
                      updateEmployee(e.id, { role_schedule: schedule });
                    }}
                    sx={{ width: 220 }}
                  />
                </TableCell>
                <TableCell>
                  {e.primary_role === "folder" ? (
                    <TextField
                      size="small"
                      type="number"
                      label="lb/hr"
                      value={e.fold_lbs_per_hour ?? ""}
                      onChange={(ev) => updateEmployee(e.id, { fold_lbs_per_hour: ev.target.value })}
                      sx={{ width: 90 }}
                    />
                  ) : e.primary_role === "sorter" ? (
                    <TextField
                      size="small"
                      type="number"
                      label="min/bag"
                      value={e.sort_min_per_bag ?? ""}
                      onChange={(ev) => updateEmployee(e.id, { sort_min_per_bag: ev.target.value })}
                      sx={{ width: 90 }}
                    />
                  ) : e.primary_role === "weigher" ? (
                    <TextField
                      size="small"
                      type="number"
                      label="min/bag"
                      value={e.weigh_min_per_bag ?? ""}
                      onChange={(ev) => updateEmployee(e.id, { weigh_min_per_bag: ev.target.value })}
                      sx={{ width: 90 }}
                    />
                  ) : (
                    <Typography variant="caption" color="text.secondary">Default</Typography>
                  )}
                </TableCell>
                <TableCell>
                  <Checkbox
                    checked={e.active !== false}
                    onChange={(ev) => updateEmployee(e.id, { active: ev.target.checked })}
                  />
                </TableCell>
                <TableCell>
                  <Button size="small" onClick={() => removeEmployee(e.id)} sx={{ textTransform: "none" }}>
                    Remove
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Section>
  );
}

export function ProcessingTimesSection({ inputs, onChange }) {
  return (
    <Section title="C. Processing times" subtitle="Machine cycles and employee handling are separate.">
      <Typography variant="caption" fontWeight={700} sx={{ display: "block", mb: 1 }}>Bag preparation</Typography>
      <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 1.5 }}>
        <NumField label="Weigh min/bag" value={inputs.weigh_min_per_bag} onChange={(v) => onChange("weigh_min_per_bag", v)} min={0} step={0.1} />
        <NumField label="Sort min/bag" value={inputs.sort_min_per_bag} onChange={(v) => onChange("sort_min_per_bag", v)} min={0} step={0.1} />
      </Stack>
      <Typography variant="caption" fontWeight={700} sx={{ display: "block", mb: 1 }}>Washer handling + wash cycle</Typography>
      <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 1.5 }}>
        <NumField label="Washer loading min/bag" value={inputs.load_washer_min} onChange={(v) => onChange("load_washer_min", v)} min={0} step={0.1} />
        <NumField label="Unload / transfer min/bag" value={inputs.unload_transfer_min} onChange={(v) => onChange("unload_transfer_min", v)} min={0} step={0.1} />
        <NumField label="Wash-cycle minutes" value={inputs.wash_cycle_min} onChange={(v) => onChange("wash_cycle_min", v)} min={1} />
      </Stack>
      <Typography variant="caption" fontWeight={700} sx={{ display: "block", mb: 1 }}>Dryer handling + dry cycle</Typography>
      <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 1.5 }}>
        <NumField label="Dryer loading min/bag" value={inputs.load_dryer_min} onChange={(v) => onChange("load_dryer_min", v)} min={0} step={0.1} />
        <NumField label="Dryer unloading min (optional)" value={inputs.unload_dryer_min} onChange={(v) => onChange("unload_dryer_min", v)} min={0} step={0.1} />
        <NumField label="Dry-cycle minutes" value={inputs.dry_cycle_min} onChange={(v) => onChange("dry_cycle_min", v)} min={1} />
      </Stack>
      <Typography variant="caption" fontWeight={700} sx={{ display: "block", mb: 1 }}>Folding</Typography>
      <Stack direction="row" flexWrap="wrap" gap={1.5}>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Fold rate mode</InputLabel>
          <Select label="Fold rate mode" value={inputs.fold_rate_mode} onChange={(e) => onChange("fold_rate_mode", e.target.value)}>
            {FOLD_RATE_MODES.map((m) => (
              <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
        {inputs.fold_rate_mode === "minutes_per_bag" ? (
          <NumField label="Fold min/bag" value={inputs.fold_min_per_bag} onChange={(v) => onChange("fold_min_per_bag", v)} min={0.1} step={0.1} />
        ) : (
          <NumField label="Folding lb/hr" value={inputs.fold_lbs_per_hour} onChange={(v) => onChange("fold_lbs_per_hour", v)} min={1} />
        )}
      </Stack>
    </Section>
  );
}

export function OrdersSection({ inputs, onChange }) {
  const orders = inputs.orders || [];
  const updateOrder = (idx, patch) => {
    onChange(
      "orders",
      orders.map((o, i) => (i === idx ? { ...o, ...patch } : o)),
    );
  };
  return (
    <Section title="D. Orders and bags" subtitle="Optional order-wise entry. Leave empty to use bag count + average/individual weights.">
      <Button
        size="small"
        variant="outlined"
        sx={{ mb: 1.5, textTransform: "none" }}
        onClick={() => onChange("orders", [...orders, newOrder(orders.length + 1)])}
      >
        + Add order
      </Button>
      {!orders.length ? (
        <Typography variant="body2" color="text.secondary">No orders entered — simulation expands bags from Shift setup.</Typography>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Order #</TableCell>
                <TableCell>Bags</TableCell>
                <TableCell>Weights / total</TableCell>
                <TableCell>2 washers</TableCell>
                <TableCell>2 dryers</TableCell>
                <TableCell>Rush</TableCell>
                <TableCell>Required done</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {orders.map((o, idx) => (
                <TableRow key={`${o.order_number}-${idx}`}>
                  <TableCell>
                    <TextField size="small" value={o.order_number} onChange={(e) => updateOrder(idx, { order_number: e.target.value })} />
                  </TableCell>
                  <TableCell>
                    <TextField size="small" type="number" value={o.bag_count} onChange={(e) => updateOrder(idx, { bag_count: e.target.value })} sx={{ width: 70 }} />
                  </TableCell>
                  <TableCell>
                    <TextField
                      size="small"
                      placeholder="18.2, 21.6, 17.9 or total"
                      value={o.weights_text || ""}
                      onChange={(e) => updateOrder(idx, { weights_text: e.target.value })}
                      sx={{ width: 200 }}
                    />
                    <TextField
                      size="small"
                      type="number"
                      label="Total lb"
                      value={o.total_weight || ""}
                      onChange={(e) => updateOrder(idx, { total_weight: e.target.value })}
                      sx={{ width: 90, ml: 1 }}
                    />
                  </TableCell>
                  <TableCell><Checkbox checked={Boolean(o.two_washer)} onChange={(e) => updateOrder(idx, { two_washer: e.target.checked })} /></TableCell>
                  <TableCell><Checkbox checked={Boolean(o.two_dryer)} onChange={(e) => updateOrder(idx, { two_dryer: e.target.checked })} /></TableCell>
                  <TableCell><Checkbox checked={Boolean(o.rush)} onChange={(e) => updateOrder(idx, { rush: e.target.checked })} /></TableCell>
                  <TableCell>
                    <TextField size="small" value={o.required_complete_time || ""} onChange={(e) => updateOrder(idx, { required_complete_time: e.target.value })} sx={{ width: 110 }} />
                  </TableCell>
                  <TableCell>
                    <Button size="small" onClick={() => onChange("orders", orders.filter((_, i) => i !== idx))} sx={{ textTransform: "none" }}>
                      Remove
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Section>
  );
}

export function StrategySection({ inputs, onChange }) {
  return (
    <Section title="E. Strategy" subtitle="Batching limits, exit policy, and re-optimization mode after staffing changes.">
      <Stack direction="row" flexWrap="wrap" gap={1.5}>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>After staffing change</InputLabel>
          <Select
            label="After staffing change"
            value={inputs.sim_mode || "reoptimize_full"}
            onChange={(e) => onChange("sim_mode", e.target.value)}
          >
            <MenuItem value="continue_from_time">Continue from that time</MenuItem>
            <MenuItem value="reoptimize_full">Re-optimize entire shift</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Exit policy</InputLabel>
          <Select
            label="Exit policy"
            value={inputs.exit_policy || "finish_current"}
            onChange={(e) => onChange("exit_policy", e.target.value)}
          >
            <MenuItem value="finish_current">Finish current task</MenuItem>
            <MenuItem value="hard_stop">Hard stop at end time</MenuItem>
          </Select>
        </FormControl>
      </Stack>
    </Section>
  );
}

export function ResultsSummarySection({ summary, simulationValid, overlapErrors, validationErrors }) {
  return (
    <Section title="G. Results summary" subtitle="Target KPIs with machine and employee utilization separated.">
      {!simulationValid ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {(validationErrors || []).length
            ? (validationErrors || []).join(" · ")
            : `Overlap detected on resources: ${(overlapErrors || []).join(", ") || "unknown"}`}
        </Alert>
      ) : (
        <Alert severity="success" sx={{ mb: 1.5 }}>No machine or employee overlap in this run.</Alert>
      )}
      <SummaryCards summary={summary} />
    </Section>
  );
}

export function ReadyByBatchSection({ rows, bagsMoved, onEditBatch }) {
  const [openBatch, setOpenBatch] = useState(null);
  const movedFor = (batchNumber) =>
    (bagsMoved || []).filter((m) => Number(m.to_batch) === Number(batchNumber) || Number(m.from_batch) === Number(batchNumber));
  return (
    <Section title="H. Ready to Fold by Batch" subtitle="When each batch becomes available and cumulative bags ready. Use Edit Batch to lock machines, people, or composition.">
      {(bagsMoved || []).length ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          Bags moved between batches:{" "}
          {(bagsMoved || []).slice(0, 8).map((m) => `${m.bag_id} (${m.from_batch}→${m.to_batch})`).join(", ")}
          {(bagsMoved || []).length > 8 ? "…" : ""}
        </Alert>
      ) : null}
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Batch</TableCell>
              <TableCell>Bags</TableCell>
              <TableCell>Pounds</TableCell>
              <TableCell>Washer</TableCell>
              <TableCell>Dryer</TableCell>
              <TableCell>Ready-to-fold time</TableCell>
              <TableCell>Cumulative bags ready</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {(rows || []).map((r) => (
              <Fragment key={r.batch_number}>
                <TableRow hover>
                  <TableCell>{r.batch_number}</TableCell>
                  <TableCell>{r.bags}</TableCell>
                  <TableCell>{r.pounds}</TableCell>
                  <TableCell>{r.washer_id}</TableCell>
                  <TableCell>{r.dryer_id}</TableCell>
                  <TableCell>{r.ready_to_fold}</TableCell>
                  <TableCell>{r.cumulative_bags_ready}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5}>
                      <Button size="small" variant="outlined" sx={{ textTransform: "none" }} onClick={() => onEditBatch?.(r)}>
                        Edit Batch
                      </Button>
                      <Button size="small" sx={{ textTransform: "none" }} onClick={() => setOpenBatch(openBatch === r.batch_number ? null : r.batch_number)}>
                        {openBatch === r.batch_number ? "Hide bags" : "Show bags"}
                      </Button>
                    </Stack>
                  </TableCell>
                </TableRow>
                {openBatch === r.batch_number ? (
                  <TableRow>
                    <TableCell colSpan={8}>
                      <Typography variant="body2">{(r.bag_ids || []).join(", ")}</Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        Orders: {(r.order_numbers || []).join(", ")}
                      </Typography>
                      {movedFor(r.batch_number).length ? (
                        <Typography variant="caption" color="warning.main" display="block">
                          Moved: {movedFor(r.batch_number).map((m) => `${m.bag_id} (${m.from_batch}→${m.to_batch})`).join(", ")}
                        </Typography>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ) : null}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Section>
  );
}

export function AvailabilitySection({ rows }) {
  return (
    <Section title="I. 30-minute availability" subtitle="Ready and folded bags at each half-hour mark.">
      <Box sx={{ overflowX: "auto", maxHeight: 320 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Time</TableCell>
              <TableCell>Bags ready</TableCell>
              <TableCell>Pounds ready</TableCell>
              <TableCell>Bags folded</TableCell>
              <TableCell>Pounds folded</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(rows || []).map((r) => (
              <TableRow key={r.time_min}>
                <TableCell>{r.time}</TableCell>
                <TableCell>{r.bags_ready}</TableCell>
                <TableCell>{r.pounds_ready}</TableCell>
                <TableCell>{r.bags_folded}</TableCell>
                <TableCell>{r.pounds_folded}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Section>
  );
}

export function RecommendationsSection({ recommendations, onApply, impact, onUndo }) {
  return (
    <Section title="J. Recommendations" subtitle="Each action updates inputs, reruns the simulation, and supports undo.">
      {impact ? (
        <Alert severity="info" sx={{ mb: 1.5 }}
          action={<Button color="inherit" size="small" onClick={onUndo}>Undo</Button>}
        >
          Applied action — bags ready {impact.bags_ready_by_target?.before} → {impact.bags_ready_by_target?.after};
          {" "}folded {impact.bags_folded_by_target?.before} → {impact.bags_folded_by_target?.after};
          {" "}complete {impact.final_completion_time?.before} → {impact.final_completion_time?.after}.
        </Alert>
      ) : null}
      {!(recommendations || []).length ? (
        <Typography variant="body2" color="text.secondary">No recommendations for this scenario.</Typography>
      ) : (
        <Stack spacing={1.5}>
          {(recommendations || []).map((rec) => (
            <Paper key={rec.id} variant="outlined" sx={{ p: 1.5 }}>
              <Typography fontWeight={800}>{rec.title}</Typography>
              <Typography variant="body2" sx={{ mt: 0.5, mb: 1 }}>{rec.detail}</Typography>
              <Stack direction="row" flexWrap="wrap" gap={1}>
                {(rec.actions || []).map((a) => (
                  <Button
                    key={a.id}
                    size="small"
                    variant="contained"
                    onClick={() => onApply(a.patch, a.label)}
                    sx={{ textTransform: "none", fontWeight: 700 }}
                  >
                    {a.label}
                  </Button>
                ))}
                <Button size="small" sx={{ textTransform: "none" }} onClick={() => onApply(null, "dismiss", rec.id)}>
                  Dismiss
                </Button>
              </Stack>
            </Paper>
          ))}
        </Stack>
      )}
    </Section>
  );
}

function StaffingAndTimelines({ result }) {
  if (!result) return null;
  const partial = result.partial_resim;
  const provenanceColor = (tag) => {
    if (tag === "preserved") return "success.main";
    if (tag === "in_progress") return "warning.main";
    if (tag === "recalculated") return "info.main";
    return "text.secondary";
  };
  return (
    <Stack spacing={2}>
      {partial ? (
        <Alert severity="info">
          Partial resim — frozen through {partial.history_frozen_through}; recalculated from {partial.recalculated_from}.
          {" "}Preserved {partial.preserved_task_count}, in-progress {partial.in_progress_task_count},
          recalculated {partial.recalculated_task_count}.
        </Alert>
      ) : null}

      <Typography variant="subtitle2" fontWeight={800}>Staffing headcount chart</Typography>
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Time</TableCell>
              <TableCell>Weighers</TableCell>
              <TableCell>Sorters</TableCell>
              <TableCell>Washer persons</TableCell>
              <TableCell>Folders</TableCell>
              <TableCell>Role switches</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(result.staffing_chart || []).map((r) => (
              <TableRow key={r.time_min}>
                <TableCell>{r.time}</TableCell>
                <TableCell>{r.weighers}</TableCell>
                <TableCell>{r.sorters}</TableCell>
                <TableCell>{r.washer_persons}</TableCell>
                <TableCell>{r.folders}</TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {(r.role_switches || r.events || []).map((ev) => (typeof ev === "string" ? ev : ev.label || JSON.stringify(ev))).join(" · ") || "—"}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>

      <Typography variant="subtitle2" fontWeight={800}>Employee timeline</Typography>
      {(result.timelines?.employees || []).map((e) => (
        <Box key={e.id} sx={{ mb: 1 }}>
          <Typography variant="body2" fontWeight={700}>{e.name} ({e.role}) — {e.utilization_pct}%</Typography>
          <Typography variant="caption" color="text.secondary">
            {(e.intervals || []).map((iv) => `${iv.start}–${iv.end}: ${iv.label}${iv.provenance ? ` [${iv.provenance}]` : ""}`).join(" · ") || "Idle"}
          </Typography>
          {(e.role_schedule || []).length ? (
            <Typography variant="caption" display="block" color="text.secondary">
              Schedule: {(e.role_schedule || []).map((w) => `${w.role} ${w.start_time || w.from}–${w.end_time || w.to}`).join("; ")}
            </Typography>
          ) : null}
        </Box>
      ))}

      <Typography variant="subtitle2" fontWeight={800}>Machine timeline</Typography>
      {[["Washers", result.timelines?.washers], ["Dryers", result.timelines?.dryers]].map(([label, rows]) => (
        <Box key={label}>
          <Typography variant="caption" fontWeight={700}>{label}</Typography>
          {(rows || []).map((m) => (
            <Typography key={m.id} variant="caption" display="block" color="text.secondary">
              {m.id}: {(m.intervals || []).map((iv) => `${iv.start}–${iv.end} ${iv.label}${iv.provenance ? ` [${iv.provenance}]` : ""}`).join(" · ") || "Idle"}
            </Typography>
          ))}
        </Box>
      ))}

      <Typography variant="subtitle2" fontWeight={800}>Bag stage provenance (sample)</Typography>
      <Box sx={{ overflowX: "auto", maxHeight: 220 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Bag</TableCell>
              <TableCell>Batch</TableCell>
              <TableCell>Stages</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(result.bag_rows || []).slice(0, 40).map((r) => (
              <TableRow key={`prov-${r.bag_id}`}>
                <TableCell>{r.bag_id}</TableCell>
                <TableCell>{r.batch}</TableCell>
                <TableCell>
                  {Object.entries(r.provenance || {}).map(([stage, tag]) => (
                    <Typography key={stage} variant="caption" component="span" sx={{ mr: 1, color: provenanceColor(tag) }}>
                      {stage}:{tag}
                    </Typography>
                  ))}
                  {!r.provenance ? "—" : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Stack>
  );
}

// Fix BagTableSection to receive result for timelines
export function BagTableAndTimelinesSection({ rows, result }) {
  const [filter, setFilter] = useState("");
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return rows || [];
    return (rows || []).filter((r) =>
      [r.order, r.bag_id, r.batch, r.folder, r.washer, r.dryer, r.rush ? "rush" : ""]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [rows, filter]);

  return (
    <Section title="K. Bag-level results & timelines" subtitle="One row per bag with named employee assignments. Timelines make conflicts visible.">
      <TextField
        size="small"
        label="Filter (order, bag, batch, folder, washer, dryer, rush)"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        sx={{ mb: 1.5, minWidth: 320 }}
      />
      <Box sx={{ overflowX: "auto", maxHeight: 420 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {[
                "Order", "Bag", "Weight", "Batch", "Weighed by", "Sorted by",
                "Washer", "Washer load", "Wash", "Transfer by", "Dryer", "Dryer load",
                "Dry", "Ready", "Folder", "Fold", "Completed", "Wait folder", "Elapsed",
              ].map((h) => (
                <TableCell key={h}>{h}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((r) => (
              <TableRow key={r.bag_id} hover>
                <TableCell>{r.order}</TableCell>
                <TableCell>{r.bag_id}</TableCell>
                <TableCell>{r.weight}{r.weight_estimated ? "*" : ""}</TableCell>
                <TableCell>{r.batch}</TableCell>
                <TableCell>{r.weighed_by}</TableCell>
                <TableCell>{r.sorted_by}</TableCell>
                <TableCell>{r.washer}</TableCell>
                <TableCell>{r.washer_load_start}–{r.washer_load_end}</TableCell>
                <TableCell>{r.wash_start}–{r.wash_end}</TableCell>
                <TableCell>{r.transferred_by}</TableCell>
                <TableCell>{r.dryer}</TableCell>
                <TableCell>{r.dryer_load_start}–{r.dryer_load_end}</TableCell>
                <TableCell>{r.dry_start}–{r.dry_end}</TableCell>
                <TableCell>{r.ready_to_fold}</TableCell>
                <TableCell>{r.folded_by}</TableCell>
                <TableCell>{r.fold_start}–{r.fold_end}</TableCell>
                <TableCell>{r.completed}</TableCell>
                <TableCell>{r.waiting_for_folder}</TableCell>
                <TableCell>{r.total_elapsed}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
      <Typography variant="caption" color="text.secondary">* Estimated weight</Typography>
      <Divider sx={{ my: 2 }} />
      <StaffingAndTimelines result={result} />
    </Section>
  );
}

export function AddStaffDialogFields({ draft, setDraft }) {
  return (
    <Stack spacing={1.5} sx={{ mt: 1, minWidth: 320 }}>
      <TextField size="small" label="Employee name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
      <FormControl size="small">
        <InputLabel>Role</InputLabel>
        <Select label="Role" value={draft.primary_role} onChange={(e) => setDraft({ ...draft, primary_role: e.target.value })}>
          {ROLE_OPTIONS.map((r) => (
            <MenuItem key={r.value} value={r.value}>{r.label}</MenuItem>
          ))}
        </Select>
      </FormControl>
      <TextField size="small" label="Start time" value={draft.start_time} onChange={(e) => setDraft({ ...draft, start_time: e.target.value })} />
      <TextField size="small" label="End time (optional)" value={draft.end_time || ""} onChange={(e) => setDraft({ ...draft, end_time: e.target.value })} />
      <TextField
        size="small"
        label="Secondary roles (comma-separated)"
        value={(draft.secondary_roles || []).join(", ")}
        onChange={(e) =>
          setDraft({
            ...draft,
            secondary_roles: e.target.value.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean),
          })
        }
      />
      {draft.primary_role === "folder" ? (
        <TextField
          size="small"
          type="number"
          label="Folding lb/hr"
          value={draft.fold_lbs_per_hour ?? 35}
          onChange={(e) => setDraft({ ...draft, fold_lbs_per_hour: e.target.value })}
        />
      ) : null}
      <FormControl size="small">
        <InputLabel>Simulation mode</InputLabel>
        <Select
          label="Simulation mode"
          value={draft.sim_mode || "continue_from_time"}
          onChange={(e) => setDraft({ ...draft, sim_mode: e.target.value })}
        >
          <MenuItem value="continue_from_time">Continue from that time</MenuItem>
          <MenuItem value="reoptimize_full">Re-optimize entire shift</MenuItem>
        </Select>
      </FormControl>
    </Stack>
  );
}
