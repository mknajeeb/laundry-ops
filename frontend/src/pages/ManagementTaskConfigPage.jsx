import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import ManagementHubNav from "../components/management/ManagementHubNav";
import {
  getManagementTaskCatalog,
  upsertManagementTaskChecklist,
  upsertManagementTaskDefinition,
  updateManagementTaskCategory,
} from "../api";

function schemaToText(schema) {
  if (!Array.isArray(schema) || !schema.length) return "";
  return schema
    .map((f) => {
      const id = f.id || f.key || "field";
      const type = f.type || "text";
      const req = f.required === false ? "optional" : "required";
      return `${id}|${type}|${f.label || id}|${req}`;
    })
    .join("\n");
}

function textToSchema(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [id, type, label, req] = line.split("|").map((x) => (x || "").trim());
      return {
        id: id || "field",
        type: type || "text",
        label: label || id || "Field",
        required: req !== "optional",
      };
    });
}

/**
 * Task Management — categories, task definitions, checklists, input schemas.
 * Assignments remain on Weekly Schedule.
 */
export default function ManagementTaskConfigPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [categories, setCategories] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [checklists, setChecklists] = useState([]);
  const [draft, setDraft] = useState(null);
  const [schemaText, setSchemaText] = useState("");
  const [checklistDraft, setChecklistDraft] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementTaskCatalog();
      setCategories(res.data?.categories || []);
      setTasks(res.data?.tasks || []);
      setChecklists(res.data?.checklists || []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not load Task Management");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openTask = (task) => {
    setDraft({ ...task });
    setSchemaText(schemaToText(task.input_schema));
    setOkMsg("");
  };

  const saveTask = async () => {
    if (!draft) return;
    setBusy(true);
    setError("");
    setOkMsg("");
    try {
      const payload = {
        ...draft,
        input_schema:
          draft.completion_type === "input_required" ? textToSchema(schemaText) : draft.input_schema || [],
      };
      await upsertManagementTaskDefinition(payload);
      setDraft(null);
      setOkMsg("Task saved.");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const toggleCategory = async (cat) => {
    setBusy(true);
    try {
      await updateManagementTaskCategory(cat.id, { name: cat.name, display_order: cat.display_order, active: !cat.active });
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Update failed");
    } finally {
      setBusy(false);
    }
  };

  const saveChecklist = async () => {
    if (!checklistDraft) return;
    setBusy(true);
    setError("");
    try {
      const items = String(checklistDraft.itemsText || "")
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .map((line) => {
          const [code, req] = line.split("|").map((x) => (x || "").trim());
          return { task_code: code, required: req !== "optional" };
        });
      await upsertManagementTaskChecklist({
        id: checklistDraft.id,
        code: checklistDraft.code,
        name: checklistDraft.name,
        category_id: checklistDraft.category_id || null,
        verification_method: checklistDraft.verification_method || "employee",
        verification_timing: checklistDraft.verification_timing || "next_day",
        verification_required: true,
        active: checklistDraft.active !== false,
        items,
      });
      setChecklistDraft(null);
      setOkMsg("Checklist saved.");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Checklist save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 1.5, md: 2.5 }, maxWidth: 1100, mx: "auto" }}>
      <ManagementHubNav />
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" sx={{ mb: 2 }} spacing={1}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 800 }}>
            Task Management
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Configure categories, tasks, inputs, and checklists. Assign people on Weekly Schedule.
          </Typography>
        </Box>
        <Button component={RouterLink} to="/management/tasks" size="small" variant="outlined">
          Task Dashboard
        </Button>
      </Stack>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}
      {okMsg ? (
        <Alert severity="success" sx={{ mb: 2 }}>
          {okMsg}
        </Alert>
      ) : null}
      {loading ? (
        <Typography>Loading…</Typography>
      ) : (
        <Stack spacing={2.5}>
          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>Categories</Typography>
            <Stack spacing={1}>
              {categories.map((cat) => (
                <Stack
                  key={cat.code}
                  direction="row"
                  alignItems="center"
                  justifyContent="space-between"
                  spacing={1}
                >
                  <Typography>
                    {cat.name}{" "}
                    <Typography component="span" variant="caption">
                      ({cat.code})
                    </Typography>
                  </Typography>
                  <FormControlLabel
                    control={
                      <Switch checked={!!cat.active} disabled={busy} onChange={() => toggleCategory(cat)} />
                    }
                    label={cat.active ? "Active" : "Inactive"}
                  />
                </Stack>
              ))}
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 800 }}>Tasks</Typography>
              <Button
                size="small"
                variant="outlined"
                onClick={() => {
                  openTask({
                    code: `custom_task_${Date.now().toString(36).slice(-4)}`,
                    name: "New Task",
                    category_code: categories.find((c) => c.active)?.code || "intra_day",
                    completion_type: "simple",
                    timer_enabled: true,
                    verification_required: false,
                    verification_method: "none",
                    verification_timing: "same_shift",
                    verifier_config: { user_ids: [] },
                    input_schema: [],
                    active: true,
                    _isNew: true,
                  });
                  setSchemaText("");
                }}
              >
                Add task
              </Button>
            </Stack>
            <Stack spacing={1}>
              {tasks.map((task) => (
                <Paper key={task.code} variant="outlined" sx={{ p: 1.25 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Box>
                      <Typography sx={{ fontWeight: 800 }}>
                        {task.name}{" "}
                        {!task.active ? <Chip size="small" label="Inactive" sx={{ ml: 0.5 }} /> : null}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {task.category_name} · {task.completion_type}
                        {task.timer_enabled ? " · timed" : " · untimed"} ·{" "}
                        {task.verification_required
                          ? `verify:${task.verification_method}/${task.verification_timing}`
                          : "no verification"}
                        {task.checklist_id ? ` · checklist #${task.checklist_id}` : ""}
                      </Typography>
                    </Box>
                    <Button size="small" onClick={() => openTask(task)}>
                      Edit
                    </Button>
                  </Stack>
                </Paper>
              ))}
            </Stack>
          </Paper>

          {draft ? (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography sx={{ fontWeight: 800, mb: 1 }}>Edit task</Typography>
              <Stack spacing={1.25}>
                <TextField
                  label="Name"
                  size="small"
                  value={draft.name || ""}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
                <TextField
                  label="Code"
                  size="small"
                  value={draft.code || ""}
                  onChange={(e) => setDraft({ ...draft, code: e.target.value })}
                  disabled={!draft._isNew}
                  helperText="Use custom_… codes for new tasks. Codes stick on schedule assignments."
                />
                <TextField
                  label="Peer verifier user IDs (comma-separated)"
                  size="small"
                  value={
                    Array.isArray(draft.verifier_config?.user_ids)
                      ? draft.verifier_config.user_ids.join(", ")
                      : draft.verifier_config?.user_ids || ""
                  }
                  onChange={(e) => {
                    const ids = e.target.value
                      .split(",")
                      .map((x) => x.trim())
                      .filter(Boolean)
                      .map((x) => Number(x))
                      .filter((n) => Number.isFinite(n));
                    setDraft({
                      ...draft,
                      verifier_config: { ...(draft.verifier_config || {}), user_ids: ids },
                    });
                  }}
                  helperText="For Employee/peer verification: who may verify (payroll user ids)."
                />
                <TextField
                  select
                  label="Category"
                  size="small"
                  value={draft.category_code || "intra_day"}
                  onChange={(e) => setDraft({ ...draft, category_code: e.target.value })}
                >
                  {categories.map((c) => (
                    <MenuItem key={c.code} value={c.code}>
                      {c.name}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label="Completion"
                  size="small"
                  value={draft.completion_type || "simple"}
                  onChange={(e) => setDraft({ ...draft, completion_type: e.target.value })}
                >
                  <MenuItem value="simple">Simple completion</MenuItem>
                  <MenuItem value="input_required">Input required</MenuItem>
                </TextField>
                {draft.completion_type === "input_required" ? (
                  <TextField
                    label="Input fields (one per line: id|type|label|required|optional)"
                    size="small"
                    multiline
                    minRows={3}
                    value={schemaText}
                    onChange={(e) => setSchemaText(e.target.value)}
                    helperText="Types: number, text, yes_no, checkbox, checklist. Example: gallons|number|Gallons remaining|required"
                  />
                ) : null}
                <TextField
                  select
                  label="Verification"
                  size="small"
                  value={
                    draft.verification_required === false || draft.verification_method === "none"
                      ? "none"
                      : draft.verification_method || "supervisor"
                  }
                  onChange={(e) => {
                    const method = e.target.value;
                    setDraft({
                      ...draft,
                      verification_method: method,
                      verification_required: method !== "none",
                    });
                  }}
                >
                  <MenuItem value="none">No verification</MenuItem>
                  <MenuItem value="employee">Employee / peer</MenuItem>
                  <MenuItem value="supervisor">Supervisor</MenuItem>
                  <MenuItem value="role">Role-based</MenuItem>
                </TextField>
                <TextField
                  select
                  label="Verification timing"
                  size="small"
                  value={draft.verification_timing || "same_shift"}
                  onChange={(e) => setDraft({ ...draft, verification_timing: e.target.value })}
                >
                  <MenuItem value="same_shift">Same shift</MenuItem>
                  <MenuItem value="later_shift">Later shift</MenuItem>
                  <MenuItem value="next_day">Next day</MenuItem>
                </TextField>
                <TextField
                  select
                  label="Checklist (optional)"
                  size="small"
                  value={draft.checklist_id || ""}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      checklist_id: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                >
                  <MenuItem value="">None</MenuItem>
                  {checklists.map((cl) => (
                    <MenuItem key={cl.id} value={cl.id}>
                      {cl.name}
                    </MenuItem>
                  ))}
                </TextField>
                <FormControlLabel
                  control={
                    <Switch
                      checked={!!draft.timer_enabled}
                      onChange={(e) => setDraft({ ...draft, timer_enabled: e.target.checked })}
                    />
                  }
                  label="Timed activity"
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={draft.active !== false}
                      onChange={(e) => setDraft({ ...draft, active: e.target.checked })}
                    />
                  }
                  label="Active"
                />
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy} onClick={saveTask}>
                    Save
                  </Button>
                  <Button disabled={busy} onClick={() => setDraft(null)}>
                    Cancel
                  </Button>
                </Stack>
              </Stack>
            </Paper>
          ) : null}

          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 800 }}>Checklists</Typography>
              <Button
                size="small"
                variant="outlined"
                onClick={() =>
                  setChecklistDraft({
                    name: "End of Day Checklist",
                    code: `eod_${Date.now().toString(36).slice(-4)}`,
                    category_id: categories.find((c) => c.code === "end_of_day")?.id || null,
                    verification_method: "employee",
                    verification_timing: "next_day",
                    active: true,
                    itemsText: tasks
                      .filter((t) => t.category_code === "end_of_day")
                      .map((t) => t.code)
                      .join("\n"),
                  })
                }
              >
                Add checklist
              </Button>
            </Stack>
            <Stack spacing={1}>
              {checklists.length ? (
                checklists.map((cl) => (
                  <Paper key={cl.id} variant="outlined" sx={{ p: 1.25 }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Box>
                        <Typography sx={{ fontWeight: 800 }}>{cl.name}</Typography>
                        <Typography variant="body2" color="text.secondary">
                          {(cl.items || []).map((i) => i.task_code).join(", ") || "No items"} ·{" "}
                          {cl.verification_method}/{cl.verification_timing}
                        </Typography>
                      </Box>
                      <Button
                        size="small"
                        onClick={() =>
                          setChecklistDraft({
                            ...cl,
                            itemsText: (cl.items || [])
                              .map((i) => `${i.task_code}${i.required ? "" : "|optional"}`)
                              .join("\n"),
                          })
                        }
                      >
                        Edit
                      </Button>
                    </Stack>
                  </Paper>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No checklists yet. Create one for End of Day → next-morning verification.
                </Typography>
              )}
            </Stack>
          </Paper>

          {checklistDraft ? (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography sx={{ fontWeight: 800, mb: 1 }}>Edit checklist</Typography>
              <Stack spacing={1.25}>
                <TextField
                  label="Name"
                  size="small"
                  value={checklistDraft.name || ""}
                  onChange={(e) => setChecklistDraft({ ...checklistDraft, name: e.target.value })}
                />
                <TextField
                  select
                  label="Category"
                  size="small"
                  value={checklistDraft.category_id || ""}
                  onChange={(e) =>
                    setChecklistDraft({
                      ...checklistDraft,
                      category_id: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                >
                  <MenuItem value="">None</MenuItem>
                  {categories.map((c) => (
                    <MenuItem key={c.id} value={c.id}>
                      {c.name}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label="Verification method"
                  size="small"
                  value={checklistDraft.verification_method || "employee"}
                  onChange={(e) =>
                    setChecklistDraft({ ...checklistDraft, verification_method: e.target.value })
                  }
                >
                  <MenuItem value="employee">Employee / peer</MenuItem>
                  <MenuItem value="supervisor">Supervisor</MenuItem>
                </TextField>
                <TextField
                  select
                  label="Verification timing"
                  size="small"
                  value={checklistDraft.verification_timing || "next_day"}
                  onChange={(e) =>
                    setChecklistDraft({ ...checklistDraft, verification_timing: e.target.value })
                  }
                >
                  <MenuItem value="same_shift">Same shift</MenuItem>
                  <MenuItem value="later_shift">Later shift</MenuItem>
                  <MenuItem value="next_day">Next day</MenuItem>
                </TextField>
                <TextField
                  label="Task codes (one per line; append |optional)"
                  size="small"
                  multiline
                  minRows={3}
                  value={checklistDraft.itemsText || ""}
                  onChange={(e) => setChecklistDraft({ ...checklistDraft, itemsText: e.target.value })}
                  helperText="Example: floor_cleaning or custom_fold_stations|optional"
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={checklistDraft.active !== false}
                      onChange={(e) =>
                        setChecklistDraft({ ...checklistDraft, active: e.target.checked })
                      }
                    />
                  }
                  label="Active"
                />
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy} onClick={saveChecklist}>
                    Save checklist
                  </Button>
                  <Button disabled={busy} onClick={() => setChecklistDraft(null)}>
                    Cancel
                  </Button>
                </Stack>
              </Stack>
            </Paper>
          ) : null}
        </Stack>
      )}
    </Box>
  );
}
