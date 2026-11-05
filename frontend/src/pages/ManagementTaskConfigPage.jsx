import { useCallback, useEffect, useMemo, useState } from "react";
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
import { useI18n } from "../i18n/I18nContext";
import { categoryLabel, localizedConfigured } from "../components/tasks/taskEmployeeI18n";
import ActivityChecklistEditor, {
  itemsFromGroup,
  itemsToPayload,
} from "../components/tasks/ActivityChecklistEditor";
import {
  checklistSections,
  groupActivitiesByCategory,
  isOperationalActivity,
} from "../components/tasks/taskManagementLists";
import {
  getEndOfDayClosingTemplate,
  getManagementTaskAssignees,
  getManagementTaskCatalog,
  upsertManagementTaskChecklist,
  upsertManagementTaskDefinition,
  retireManagementActivityGroup,
  upsertManagementTaskActivityGroup,
  upsertManagementTaskVerificationPolicy,
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
  const { locale, t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [categories, setCategories] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [checklists, setChecklists] = useState([]);
  const [draft, setDraft] = useState(null);
  const [schemaText, setSchemaText] = useState("");
  const [checklistDraft, setChecklistDraft] = useState(null);
  const [activityGroups, setActivityGroups] = useState([]);
  const [groupDraft, setGroupDraft] = useState(null);
  const [globalPolicy, setGlobalPolicy] = useState(null);
  const [globalDraft, setGlobalDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [assignees, setAssignees] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementTaskCatalog();
      setCategories(res.data?.categories || []);
      try {
        const people = await getManagementTaskAssignees();
        setAssignees(people.data?.assignees || []);
      } catch {
        setAssignees([]);
      }
      setTasks(res.data?.tasks || []);
      setChecklists(res.data?.checklists || []);
      setActivityGroups(res.data?.activity_groups || []);
      const policy = res.data?.verification_policy || {
        verification_required: true,
        verification_method: "supervisor",
        verification_timing: "same_shift",
        is_default: true,
      };
      setGlobalPolicy(policy);
      setGlobalDraft(null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.config.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

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
      setOkMsg(t("tasks.config.saved"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.config.saveFailed"));
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
      setError(e?.response?.data?.error || e?.message || t("tasks.config.updateFailed"));
    } finally {
      setBusy(false);
    }
  };

  const retireGroup = async (group, permanent) => {
    setBusy(true);
    setError("");
    try {
      const saved = await retireManagementActivityGroup(group.id, { permanent });
      setOkMsg(
        saved.data?.deleted
          ? t("tasks.config.deletedUnused")
          : t("tasks.config.archivedInstead"),
      );
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.config.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const saveGroup = async () => {
    if (!groupDraft) return;
    setBusy(true);
    setError("");
    try {
      const rows = itemsToPayload(groupDraft.itemRows || []);
      const used = new Set(rows.map((row) => row.task_code).filter(Boolean));
      const items = [];
      for (const [index, row] of rows.entries()) {
        let code = row.task_code;
        if (!code) {
          const base =
            String(row.task_name || "item")
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, "_")
              .replace(/^_|_$/g, "")
              .slice(0, 40) || `item_${index + 1}`;
          code = base;
          let n = 2;
          while (used.has(code)) {
            code = `${base}_${n}`;
            n += 1;
          }
          used.add(code);
        }
        const saved = await upsertManagementTaskDefinition({
          code,
          name: row.task_name,
          category_code: groupDraft.category_code || "intra_day",
          completion_type: (row.input_schema || []).length ? "input_required" : "simple",
          input_schema: row.input_schema || [],
          timer_enabled: false,
          verification_inherits: true,
          active: row.active !== false,
          display_order: row.display_order,
        });
        items.push({
          ...row,
          task_code: saved.data?.task?.code || code,
        });
      }
      const inherits = groupDraft.verification_inherits !== false;
      const requireChecklist = groupDraft.id
        ? groupDraft.requireChecklistTouched
          ? { require_checklist_before_completion: groupDraft.require_checklist_before_completion === true }
          : {}
        : {
            require_checklist_before_completion: groupDraft.requireChecklistTouched
              ? groupDraft.require_checklist_before_completion === true
              : items.some((item) => item.required !== false),
          };
      await upsertManagementTaskActivityGroup({
        id: groupDraft.id,
        code: groupDraft.code,
        name: groupDraft.name,
        category_code: groupDraft.category_code || "intra_day",
        display_order: Number(groupDraft.display_order || 0),
        active: groupDraft.active !== false,
        ...requireChecklist,
        verification_inherits: inherits,
        ...(inherits
          ? {}
          : {
              verification_method: groupDraft.verification_method || "supervisor",
              verification_required: groupDraft.verification_method !== "none",
              verification_timing: groupDraft.verification_timing || "same_shift",
              verifier_config: groupDraft.verifier_config || {},
            }),
        instructions: groupDraft.instructions || "",
        instructions_es: groupDraft.instructions_es || "",
        name_es: groupDraft.name_es || "",
        items,
      });
      setGroupDraft(null);
      setOkMsg(t("tasks.config.groupSaved"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.config.groupSaveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const startEndOfDay = async () => {
    setBusy(true);
    setError("");
    try {
      const existing = activityGroups.find(
        (group) => group.code === "end_of_day_closing" || group.name === "End of Day Closing"
      );
      if (existing) {
        setGroupDraft({
          ...existing,
          itemRows: itemsFromGroup(existing.items),
          requireChecklistTouched: false,
        });
        return;
      }
      const res = await getEndOfDayClosingTemplate();
      const template = res.data || {};
      setGroupDraft({
        name: template.name || "End of Day Closing",
        code: template.code || "end_of_day_closing",
        instructions: template.instructions || "",
        category_code: template.category_code || "end_of_day",
        display_order: template.display_order || 30,
        active: true,
        verification_inherits: false,
        verification_method: template.verification_method || "supervisor",
        verification_timing: template.verification_timing || "same_shift",
        verification_required: true,
        require_checklist_before_completion: true,
        requireChecklistTouched: true,
        itemRows: itemsFromGroup(template.items),
      });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.config.eodFailed"));
    } finally {
      setBusy(false);
    }
  };

  const saveGlobalPolicy = async () => {
    if (!globalDraft) return;
    setBusy(true);
    setError("");
    try {
      const method = globalDraft.verification_method || "supervisor";
      await upsertManagementTaskVerificationPolicy({
        verification_method: method,
        verification_required: method !== "none",
        verification_timing: globalDraft.verification_timing || "same_shift",
        verifier_config: globalDraft.verifier_config || {},
      });
      setOkMsg(t("tasks.config.policySaved"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.config.policySaveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const saveChecklist = async () => {
    if (!checklistDraft) return;
    setBusy(true);
    setError("");
    try {
      const groups = (checklistDraft.groups || [])
        .map((g, idx) => ({
          id: g.id,
          name: String(g.name || `Group ${idx + 1}`).trim() || `Group ${idx + 1}`,
          display_order: idx * 10,
          items: (g.items || [])
            .filter((it) => it && it.task_code)
            .map((it, iidx) => ({
              task_code: it.task_code,
              required: it.required !== false,
              display_order: iidx * 10,
            })),
        }))
        .filter((g) => g.items.length);
      await upsertManagementTaskChecklist({
        id: checklistDraft.id,
        code: checklistDraft.code,
        name: checklistDraft.name,
        category_id: checklistDraft.category_id || null,
        verification_method: checklistDraft.verification_method || "employee",
        verification_timing: checklistDraft.verification_timing || "next_day",
        verification_required: true,
        active: checklistDraft.active !== false,
        groups,
      });
      setChecklistDraft(null);
      setOkMsg(t("tasks.config.checklistSaved"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.config.checklistSaveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const openChecklistEditor = (cl) => {
    const groups =
      Array.isArray(cl?.groups) && cl.groups.length
        ? cl.groups.map((g) => ({
            id: g.id,
            name: g.name || "General",
            collapsed: false,
            items: (g.items || []).map((it) => ({
              task_code: it.task_code,
              required: it.required !== false,
            })),
          }))
        : [
            {
              name: "General",
              collapsed: false,
              items: (cl?.items || []).map((it) => ({
                task_code: it.task_code,
                required: it.required !== false,
              })),
            },
          ];
    setChecklistDraft({ ...cl, groups, addTaskCode: "" });
  };

  const updateChecklistGroup = (gIdx, patch) => {
    setChecklistDraft((prev) => {
      if (!prev) return prev;
      const groups = [...(prev.groups || [])];
      groups[gIdx] = { ...groups[gIdx], ...patch };
      return { ...prev, groups };
    });
  };

  const visibleTasks = tasks;
  const operationalGroups = useMemo(
    () => activityGroups.filter(isOperationalActivity),
    [activityGroups]
  );
  const legacyGroups = useMemo(
    () => activityGroups.filter((group) => !isOperationalActivity(group)),
    [activityGroups]
  );
  const activityBuckets = useMemo(
    () => groupActivitiesByCategory(operationalGroups, categories),
    [operationalGroups, categories]
  );

  return (
    <Box sx={{ p: { xs: 1.5, md: 2.5 }, maxWidth: 1100, mx: "auto" }}>
      <ManagementHubNav />
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" sx={{ mb: 2 }} spacing={1}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 800 }}>
            {t("tasks.config.title")}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t("tasks.config.intro")}
          </Typography>
        </Box>
        <Button component={RouterLink} to="/management/tasks" size="small" variant="outlined">
          {t("tasks.config.openDashboard")}
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
        <Typography>{t("tasks.config.loading")}</Typography>
      ) : (
        <Stack spacing={2.5}>
          <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Typography sx={{ fontWeight: 800 }}>{t("tasks.config.global")}</Typography>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={busy}
                  onClick={() =>
                    setGlobalDraft({
                      ...(globalPolicy || {}),
                      verification_method:
                        globalPolicy?.verification_method || "supervisor",
                      verification_timing: globalPolicy?.verification_timing || "same_shift",
                    })
                  }
                >
                  {t("tasks.config.edit")}
                </Button>
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {t("tasks.config.hierarchy")}
                {globalPolicy
                  ? t("tasks.config.current", {
                      value: `${
                        globalPolicy.verification_required
                          ? `${globalPolicy.verification_method}/${globalPolicy.verification_timing}`
                          : t("tasks.config.notRequired")
                      }${globalPolicy.is_default ? ` (${t("tasks.config.builtin")})` : ""}`,
                    })
                  : ""}
              </Typography>
              {globalDraft ? (
                <Stack spacing={1.25} sx={{ mt: 1.5 }}>
                  <TextField
                    select
                    label={t("tasks.config.verification")}
                    size="small"
                    value={
                      globalDraft.verification_required === false ||
                      globalDraft.verification_method === "none"
                        ? "none"
                        : globalDraft.verification_method || "supervisor"
                    }
                    onChange={(e) => {
                      const method = e.target.value;
                      setGlobalDraft({
                        ...globalDraft,
                        verification_method: method,
                        verification_required: method !== "none",
                      });
                    }}
                    helperText={t("tasks.config.noVerificationIntentional")}
                  >
                    <MenuItem value="none">{t("tasks.config.noVerification")}</MenuItem>
                    <MenuItem value="employee">{t("tasks.config.employeePeer")}</MenuItem>
                    <MenuItem value="supervisor">{t("tasks.config.supervisor")}</MenuItem>
                    <MenuItem value="role">{t("tasks.config.roleBased")}</MenuItem>
                  </TextField>
                  <TextField
                    select
                    label={t("tasks.config.verificationTiming")}
                    size="small"
                    value={globalDraft.verification_timing || "same_shift"}
                    onChange={(e) =>
                      setGlobalDraft({ ...globalDraft, verification_timing: e.target.value })
                    }
                  >
                    <MenuItem value="same_shift">{t("tasks.config.sameShift")}</MenuItem>
                    <MenuItem value="later_shift">{t("tasks.config.laterShift")}</MenuItem>
                    <MenuItem value="next_day">{t("tasks.config.nextDay")}</MenuItem>
                  </TextField>
                  <Stack direction="row" spacing={1}>
                    <Button variant="contained" disabled={busy} onClick={saveGlobalPolicy}>
                      {t("tasks.config.savePolicy")}
                    </Button>
                    <Button disabled={busy} onClick={() => setGlobalDraft(null)}>
                      {t("tasks.config.cancel")}
                    </Button>
                  </Stack>
                </Stack>
              ) : null}
          </Paper>

          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("tasks.config.categories")}</Typography>
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
                    {categoryLabel(t, cat.code, cat.name)}{" "}
                    <Typography component="span" variant="caption">
                      ({cat.code})
                    </Typography>
                  </Typography>
                  <FormControlLabel
                    control={
                      <Switch checked={!!cat.active} disabled={busy} onChange={() => toggleCategory(cat)} />
                    }
                    label={cat.active ? t("tasks.config.active") : t("tasks.config.inactive")}
                  />
                </Stack>
              ))}
            </Stack>
          </Paper>

                    <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 800 }}>{t("tasks.config.groups")}</Typography>
              <Stack direction="row" spacing={1}>
                <Button size="small" variant="contained" disabled={busy} onClick={startEndOfDay}>
                  {t("tasks.config.endOfDay")}
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={busy}
                  onClick={() =>
                    setGroupDraft({
                      name: "",
                      instructions: "",
                      category_code: categories[0]?.code || "intra_day",
                      display_order: 0,
                      active: true,
                      verification_inherits: true,
                      verification_method: "supervisor",
                      verification_timing: "same_shift",
                      itemRows: [],
                      require_checklist_before_completion: true,
                      requireChecklistTouched: false,
                    })
                  }
                >
                  {t("tasks.config.addActivity")}
                </Button>
              </Stack>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {t("tasks.config.activeHelp")}
            </Typography>
            <Stack spacing={1.5}>
              {activityBuckets.length ? (
                activityBuckets.map((bucket) => (
                  <Box key={bucket.code}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 0.5 }}>
                      {categoryLabel(t, bucket.code, bucket.name)}
                    </Typography>
                    <Stack spacing={1}>
                      {bucket.groups.map((g) => (
                        <Paper key={g.id || g.code} variant="outlined" sx={{ p: 1.25 }}>
                          <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                            <Box sx={{ minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 800 }}>
                                {localizedConfigured(g, locale, "name", "name_es") || g.name}
                                {!g.active ? <Chip size="small" label={t("tasks.config.inactive")} sx={{ ml: 0.5 }} /> : null}
                              </Typography>
                              <Typography variant="caption" color="text.secondary" display="block">
                                {t("tasks.config.scheduleCode", { code: g.role_code })}
                                {" · "}
                                {g.verification_inherits !== false
                                  ? t("tasks.config.verifyInherited")
                                  : g.verification_required
                                    ? t("tasks.config.verifyDetail", {
                                        method: g.verification_method,
                                        timing: g.verification_timing,
                                      })
                                    : t("tasks.config.verifyNone")}
                              </Typography>
                              {checklistSections(g.items).map((section) => (
                                <Box key={section.label} sx={{ mt: 0.75 }}>
                                  <Typography variant="caption" sx={{ fontWeight: 800 }}>
                                    {localizedConfigured(
                                      {
                                        section_label: section.label,
                                        section_label_es: section.items?.[0]?.section_label_es,
                                      },
                                      locale,
                                      "section_label",
                                      "section_label_es",
                                    ) || section.label}
                                  </Typography>
                                  {section.items.map((item) => (
                                    <Typography
                                      key={item.task_code || item.id}
                                      variant="caption"
                                      color="text.secondary"
                                      display="block"
                                    >
                                      {localizedConfigured(item, locale, "task_name", "task_name_es") ||
                                        item.task_name ||
                                        item.task_code}
                                      {item.required === false
                                        ? ` · ${t("tasks.config.optional")}`
                                        : ` · ${t("tasks.config.required")}`}
                                    </Typography>
                                  ))}
                                </Box>
                              ))}
                            </Box>
                            <Button
                              size="small"
                              onClick={() =>
                                setGroupDraft({
                                  ...g,
                                  itemRows: itemsFromGroup(g.items),
                                  requireChecklistTouched: false,
                                })
                              }
                            >
                              {t("tasks.config.edit")}
                            </Button>
                            <Button size="small" disabled={busy} onClick={() => retireGroup(g, false)}>
                              {t("tasks.config.archive")}
                            </Button>
                            <Button size="small" color="error" disabled={busy} onClick={() => retireGroup(g, true)}>
                              {t("tasks.config.deleteUnused")}
                            </Button>
                          </Stack>
                        </Paper>
                      ))}
                    </Stack>
                  </Box>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t("tasks.config.noGroupsYet")}
                </Typography>
              )}
            </Stack>
          </Paper>

          {groupDraft ? (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("tasks.config.editGroup")}</Typography>
              <Stack spacing={1.25}>
                <TextField
                  label={t("tasks.config.name")}
                  size="small"
                  value={groupDraft.name || ""}
                  onChange={(e) => setGroupDraft({ ...groupDraft, name: e.target.value })}
                />
                <TextField
                  label={t("tasks.config.nameEs")}
                  size="small"
                  value={groupDraft.name_es || ""}
                  onChange={(e) => setGroupDraft({ ...groupDraft, name_es: e.target.value })}
                />
                <TextField
                  label={t("tasks.config.instructions")}
                  size="small"
                  multiline
                  minRows={2}
                  value={groupDraft.instructions || ""}
                  onChange={(e) => setGroupDraft({ ...groupDraft, instructions: e.target.value })}
                />
                <TextField
                  label={t("tasks.config.instructionsEs")}
                  size="small"
                  multiline
                  minRows={2}
                  value={groupDraft.instructions_es || ""}
                  onChange={(e) => setGroupDraft({ ...groupDraft, instructions_es: e.target.value })}
                />
                <TextField
                  select
                  label={t("tasks.config.category")}
                  size="small"
                  value={groupDraft.category_code || "intra_day"}
                  onChange={(e) => setGroupDraft({ ...groupDraft, category_code: e.target.value })}
                >
                  {categories.map((c) => (
                    <MenuItem key={c.code} value={c.code}>
                      {categoryLabel(t, c.code, c.name)}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  label={t("tasks.config.displayOrder")}
                  size="small"
                  type="number"
                  value={groupDraft.display_order ?? 0}
                  onChange={(e) => setGroupDraft({ ...groupDraft, display_order: e.target.value })}
                />
                <ActivityChecklistEditor
                  items={groupDraft.itemRows || []}
                  assignees={assignees}
                  onChange={(itemRows) => setGroupDraft({ ...groupDraft, itemRows })}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={groupDraft.active !== false}
                      onChange={(e) => setGroupDraft({ ...groupDraft, active: e.target.checked })}
                    />
                  }
                  label={t("tasks.config.active")}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={(() => {
                        if (groupDraft.requireChecklistTouched) {
                          return groupDraft.require_checklist_before_completion === true;
                        }
                        if (groupDraft.require_checklist_before_completion === false) return false;
                        if (groupDraft.require_checklist_before_completion === true) return true;
                        const rows = groupDraft.itemRows || [];
                        if (!rows.length) return !groupDraft.id;
                        return rows.some((row) => row.required !== false);
                      })()}
                      onChange={(e) =>
                        setGroupDraft({
                          ...groupDraft,
                          require_checklist_before_completion: e.target.checked,
                          requireChecklistTouched: true,
                        })
                      }
                    />
                  }
                  label={t("tasks.config.requireChecklist")}
                />
                <Typography variant="caption" color="text.secondary">
                  {t("tasks.config.checklistRequirementHelp")}
                </Typography>
                <FormControlLabel
                  control={
                    <Switch
                      checked={groupDraft.verification_inherits !== false}
                      onChange={(e) =>
                        setGroupDraft({
                          ...groupDraft,
                          verification_inherits: e.target.checked,
                        })
                      }
                    />
                  }
                  label={
                    groupDraft.verification_inherits !== false
                      ? t("tasks.config.inheritVerification")
                      : t("tasks.config.overrideGroupVerification")
                  }
                />
                {groupDraft.verification_inherits === false ? (
                  <>
                    <TextField
                      select
                      label={t("tasks.config.groupVerification")}
                      size="small"
                      value={
                        groupDraft.verification_required === false ||
                        groupDraft.verification_method === "none"
                          ? "none"
                          : groupDraft.verification_method || "supervisor"
                      }
                      onChange={(e) => {
                        const method = e.target.value;
                        setGroupDraft({
                          ...groupDraft,
                          verification_inherits: false,
                          verification_method: method,
                          verification_required: method !== "none",
                        });
                      }}
                      helperText={t("tasks.config.sameOptions")}
                    >
                      <MenuItem value="none">{t("tasks.config.noVerification")}</MenuItem>
                      <MenuItem value="employee">{t("tasks.config.employeePeer")}</MenuItem>
                      <MenuItem value="supervisor">{t("tasks.config.supervisor")}</MenuItem>
                      <MenuItem value="role">{t("tasks.config.roleBased")}</MenuItem>
                    </TextField>
                    <TextField
                      select
                      label={t("tasks.config.verificationTiming")}
                      size="small"
                      value={groupDraft.verification_timing || "same_shift"}
                      onChange={(e) =>
                        setGroupDraft({ ...groupDraft, verification_timing: e.target.value })
                      }
                    >
                      <MenuItem value="same_shift">{t("tasks.config.sameShift")}</MenuItem>
                      <MenuItem value="later_shift">{t("tasks.config.laterShift")}</MenuItem>
                      <MenuItem value="next_day">{t("tasks.config.nextDay")}</MenuItem>
                    </TextField>
                  </>
                ) : null}
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy} onClick={saveGroup}>
                    {t("tasks.config.saveGroup")}
                  </Button>
                  <Button disabled={busy} onClick={() => setGroupDraft(null)}>
                    {t("tasks.config.cancel")}
                  </Button>
                </Stack>
              </Stack>
            </Paper>
          ) : null}

          <Box component="details" sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, px: 1.5, py: 1 }}>
            <Box component="summary" sx={{ cursor: "pointer", fontWeight: 800 }}>
              {t("tasks.config.legacy")}
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 1 }}>
              {t("tasks.config.legacyHelp")}
            </Typography>
            <Stack spacing={1} sx={{ mb: 1.5 }}>
              {legacyGroups.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {t("tasks.config.noneArchived")}
                </Typography>
              ) : (
                legacyGroups.map((g) => (
                  <Paper key={g.id || g.code} variant="outlined" sx={{ p: 1.25 }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Box>
                        <Typography sx={{ fontWeight: 800 }}>
                          {localizedConfigured(g, locale, "name", "name_es") || g.name}
                          {!g.active ? <Chip size="small" label={t("tasks.config.inactive")} sx={{ ml: 0.5 }} /> : null}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {g.category_code || "intra_day"} · {g.role_code}
                        </Typography>
                      </Box>
                      <Button
                        size="small"
                        onClick={() =>
                          setGroupDraft({
                            ...g,
                            itemRows: itemsFromGroup(g.items),
                            requireChecklistTouched: false,
                          })
                        }
                      >
                        {t("tasks.config.edit")}
                      </Button>
                    </Stack>
                  </Paper>
                ))
              )}
            </Stack>
          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 800 }}>{t("tasks.config.standalone")}</Typography>
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
                    verification_inherits: true,
                    verification_required: true,
                    verification_method: "supervisor",
                    verification_timing: "same_shift",
                    verifier_config: { user_ids: [] },
                    input_schema: [],
                    active: true,
                    _isNew: true,
                  });
                  setSchemaText("");
                }}
              >
                {t("tasks.config.addTask")}
              </Button>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {t("tasks.config.codesStay")}
            </Typography>
            <Stack spacing={1}>
              {visibleTasks.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {t("tasks.config.noStandalone")}
                </Typography>
              ) : null}
              {visibleTasks.map((task) => (
                <Paper key={task.code} variant="outlined" sx={{ p: 1.25 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Box>
                      <Typography sx={{ fontWeight: 800 }}>
                        {localizedConfigured(task, locale, "name", "name_es") || task.name}{" "}
                        {!task.active ? <Chip size="small" label={t("tasks.config.inactive")} sx={{ ml: 0.5 }} /> : null}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {categoryLabel(t, task.category_code, task.category_name)} ·{" "}
                        {task.completion_type === "input_required"
                          ? t("tasks.config.inputRequired")
                          : t("tasks.config.simpleCompletion")}
                        {task.timer_enabled ? ` · ${t("tasks.config.timedShort")}` : ` · ${t("tasks.config.untimed")}`} ·{" "}
                        {task.verification_inherits
                          ? t("tasks.config.verifyInherited")
                          : task.verification_required
                            ? t("tasks.config.verifyDetail", {
                                method: task.verification_method,
                                timing: task.verification_timing,
                              })
                            : t("tasks.config.verifyNone")}
                        {task.checklist_id ? ` · ${t("tasks.config.checklistRef", { id: task.checklist_id })}` : ""}
                      </Typography>
                    </Box>
                    <Button size="small" onClick={() => openTask(task)}>
                      {t("tasks.config.edit")}
                    </Button>
                  </Stack>
                </Paper>
              ))}
            </Stack>
          </Paper>
          </Box>

          {draft ? (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("tasks.config.editTask")}</Typography>
              <Stack spacing={1.25}>
                <TextField
                  label={t("tasks.config.name")}
                  size="small"
                  value={draft.name || ""}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
                <TextField
                  label={t("tasks.config.code")}
                  size="small"
                  value={draft.code || ""}
                  onChange={(e) => setDraft({ ...draft, code: e.target.value })}
                  disabled={!draft._isNew}
                  helperText={t("tasks.config.codeHelp")}
                />
                <TextField
                  label={t("tasks.config.peerIds")}
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
                  helperText={t("tasks.config.peerIdsHelp")}
                />
                <TextField
                  select
                  label={t("tasks.config.category")}
                  size="small"
                  value={draft.category_code || "intra_day"}
                  onChange={(e) => setDraft({ ...draft, category_code: e.target.value })}
                >
                  {categories.map((c) => (
                    <MenuItem key={c.code} value={c.code}>
                      {categoryLabel(t, c.code, c.name)}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label={t("tasks.config.completion")}
                  size="small"
                  value={draft.completion_type || "simple"}
                  onChange={(e) => setDraft({ ...draft, completion_type: e.target.value })}
                >
                  <MenuItem value="simple">{t("tasks.config.simpleCompletion")}</MenuItem>
                  <MenuItem value="input_required">{t("tasks.config.inputRequired")}</MenuItem>
                </TextField>
                {draft.completion_type === "input_required" ? (
                  <TextField
                    label={t("tasks.config.inputFields")}
                    size="small"
                    multiline
                    minRows={3}
                    value={schemaText}
                    onChange={(e) => setSchemaText(e.target.value)}
                    helperText={t("tasks.config.inputFieldsHelp")}
                  />
                ) : null}
                <FormControlLabel
                  control={
                    <Switch
                      checked={draft.verification_inherits !== false}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          verification_inherits: e.target.checked,
                          ...(e.target.checked
                            ? {}
                            : {
                                verification_method: draft.verification_method || "supervisor",
                                verification_required: draft.verification_method !== "none",
                              }),
                        })
                      }
                    />
                  }
                  label={
                    draft.verification_inherits !== false
                      ? t("tasks.config.inheritGroupVerification")
                      : t("tasks.config.overrideTaskVerification")
                  }
                />
                {draft.verification_inherits === false ? (
                  <>
                    <TextField
                      select
                      label={t("tasks.config.verification")}
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
                          verification_inherits: false,
                          verification_method: method,
                          verification_required: method !== "none",
                        });
                      }}
                      helperText={t("tasks.config.noVerificationChoice")}
                    >
                      <MenuItem value="none">{t("tasks.config.noVerification")}</MenuItem>
                      <MenuItem value="employee">{t("tasks.config.employeePeer")}</MenuItem>
                      <MenuItem value="supervisor">{t("tasks.config.supervisor")}</MenuItem>
                      <MenuItem value="role">{t("tasks.config.roleBased")}</MenuItem>
                    </TextField>
                    <TextField
                      select
                      label={t("tasks.config.verificationTiming")}
                      size="small"
                      value={draft.verification_timing || "same_shift"}
                      onChange={(e) => setDraft({ ...draft, verification_timing: e.target.value })}
                    >
                      <MenuItem value="same_shift">{t("tasks.config.sameShift")}</MenuItem>
                      <MenuItem value="later_shift">{t("tasks.config.laterShift")}</MenuItem>
                      <MenuItem value="next_day">{t("tasks.config.nextDay")}</MenuItem>
                    </TextField>
                  </>
                ) : null}
                <TextField
                  select
                  label={t("tasks.config.checklist")}
                  size="small"
                  value={draft.checklist_id || ""}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      checklist_id: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                >
                  <MenuItem value="">{t("tasks.config.none")}</MenuItem>
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
                  label={t("tasks.config.timed")}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={draft.active !== false}
                      onChange={(e) => setDraft({ ...draft, active: e.target.checked })}
                    />
                  }
                  label={t("tasks.config.active")}
                />
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy} onClick={saveTask}>
                    {t("tasks.config.save")}
                  </Button>
                  <Button disabled={busy} onClick={() => setDraft(null)}>
                    {t("tasks.config.cancel")}
                  </Button>
                </Stack>
              </Stack>
            </Paper>
          ) : null}

<Paper variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 800 }}>{t("tasks.config.checklists")}</Typography>
              <Button
                size="small"
                variant="outlined"
                onClick={() =>
                  openChecklistEditor({
                    name: "End of Day Checklist",
                    code: `eod_${Date.now().toString(36).slice(-4)}`,
                    category_id: categories.find((c) => c.code === "end_of_day")?.id || null,
                    verification_method: "employee",
                    verification_timing: "next_day",
                    active: true,
                    groups: [
                      {
                        name: "General",
                        collapsed: false,
                        items: tasks
                          .filter((t) => t.category_code === "end_of_day")
                          .map((t) => ({ task_code: t.code, required: true })),
                      },
                    ],
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
                          {(cl.groups || []).length
                            ? t("tasks.config.groupCount", {
                                groups: (cl.groups || []).length,
                                tasks: (cl.items || []).length,
                              })
                            : (cl.items || []).map((i) => i.task_code).join(", ") || t("tasks.config.noItems")}{" "}
                          · {cl.verification_method}/{cl.verification_timing}
                        </Typography>
                      </Box>
                      <Button size="small" onClick={() => openChecklistEditor(cl)}>
                        {t("tasks.config.edit")}
                      </Button>
                    </Stack>
                  </Paper>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t("tasks.config.noChecklists")}
                </Typography>
              )}
            </Stack>
          </Paper>

          {checklistDraft ? (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("tasks.config.editChecklist")}</Typography>
              <Stack spacing={1.25}>
                <TextField
                  label={t("tasks.config.name")}
                  size="small"
                  value={checklistDraft.name || ""}
                  onChange={(e) => setChecklistDraft({ ...checklistDraft, name: e.target.value })}
                />
                <TextField
                  select
                  label={t("tasks.config.category")}
                  size="small"
                  value={checklistDraft.category_id || ""}
                  onChange={(e) =>
                    setChecklistDraft({
                      ...checklistDraft,
                      category_id: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                >
                  <MenuItem value="">{t("tasks.config.none")}</MenuItem>
                  {categories.map((c) => (
                    <MenuItem key={c.id} value={c.id}>
                      {categoryLabel(t, c.code, c.name)}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label={t("tasks.config.verification")}
                  size="small"
                  value={checklistDraft.verification_method || "employee"}
                  onChange={(e) =>
                    setChecklistDraft({ ...checklistDraft, verification_method: e.target.value })
                  }
                >
                  <MenuItem value="employee">{t("tasks.config.employeePeer")}</MenuItem>
                  <MenuItem value="supervisor">{t("tasks.config.supervisor")}</MenuItem>
                </TextField>
                <TextField
                  select
                  label={t("tasks.config.verificationTiming")}
                  size="small"
                  value={checklistDraft.verification_timing || "next_day"}
                  onChange={(e) =>
                    setChecklistDraft({ ...checklistDraft, verification_timing: e.target.value })
                  }
                >
                  <MenuItem value="same_shift">{t("tasks.config.sameShift")}</MenuItem>
                  <MenuItem value="later_shift">{t("tasks.config.laterShift")}</MenuItem>
                  <MenuItem value="next_day">{t("tasks.config.nextDay")}</MenuItem>
                </TextField>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                    {t("tasks.config.checklistGroups")}
                  </Typography>
                  <Button
                    size="small"
                    onClick={() =>
                      setChecklistDraft({
                        ...checklistDraft,
                        groups: [
                          ...(checklistDraft.groups || []),
                          { name: `Group ${(checklistDraft.groups || []).length + 1}`, collapsed: false, items: [] },
                        ],
                      })
                    }
                  >
                    {t("tasks.config.addGroup")}
                  </Button>
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  {t("tasks.config.checklistGroupsHelp")}
                </Typography>
                <Stack spacing={1.25}>
                  {(checklistDraft.groups || []).map((group, gIdx) => (
                    <Paper key={`g-${gIdx}-${group.id || group.name}`} variant="outlined" sx={{ p: 1.25 }}>
                      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                        <TextField
                          label={t("tasks.config.groupName")}
                          size="small"
                          fullWidth
                          value={group.name || ""}
                          onChange={(e) => updateChecklistGroup(gIdx, { name: e.target.value })}
                        />
                        <Button
                          size="small"
                          disabled={gIdx === 0}
                          onClick={() => {
                            const groups = [...(checklistDraft.groups || [])];
                            const tmp = groups[gIdx - 1];
                            groups[gIdx - 1] = groups[gIdx];
                            groups[gIdx] = tmp;
                            setChecklistDraft({ ...checklistDraft, groups });
                          }}
                        >
                          {t("tasks.config.up")}
                        </Button>
                        <Button
                          size="small"
                          disabled={gIdx >= (checklistDraft.groups || []).length - 1}
                          onClick={() => {
                            const groups = [...(checklistDraft.groups || [])];
                            const tmp = groups[gIdx + 1];
                            groups[gIdx + 1] = groups[gIdx];
                            groups[gIdx] = tmp;
                            setChecklistDraft({ ...checklistDraft, groups });
                          }}
                        >
                          {t("tasks.config.down")}
                        </Button>
                        <Button
                          size="small"
                          color="warning"
                          onClick={() =>
                            setChecklistDraft({
                              ...checklistDraft,
                              groups: (checklistDraft.groups || []).filter((_, i) => i !== gIdx),
                            })
                          }
                        >
                          {t("tasks.config.remove")}
                        </Button>
                      </Stack>
                      <Stack spacing={0.75}>
                        {(group.items || []).map((item, iIdx) => {
                          const task = tasks.find((t) => t.code === item.task_code);
                          return (
                            <Stack
                              key={`${item.task_code}-${iIdx}`}
                              direction="row"
                              spacing={1}
                              alignItems="center"
                            >
                              <Typography sx={{ flex: 1, fontWeight: 600 }}>
                                {localizedConfigured(task || { name: item.task_code }, locale, "name", "name_es") ||
                                  item.task_code}
                              </Typography>
                              <FormControlLabel
                                control={
                                  <Switch
                                    size="small"
                                    checked={item.required !== false}
                                    onChange={(e) => {
                                      const items = [...(group.items || [])];
                                      items[iIdx] = { ...items[iIdx], required: e.target.checked };
                                      updateChecklistGroup(gIdx, { items });
                                    }}
                                  />
                                }
                                label={t("tasks.config.required")}
                              />
                              <Button
                                size="small"
                                onClick={() => {
                                  const items = [...(group.items || [])];
                                  items.splice(iIdx, 1);
                                  updateChecklistGroup(gIdx, { items });
                                }}
                              >
                                {t("tasks.config.remove")}
                              </Button>
                            </Stack>
                          );
                        })}
                      </Stack>
                      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
                        <TextField
                          select
                          size="small"
                          label={t("tasks.config.addTask")}
                          fullWidth
                          value={group._addCode || ""}
                          onChange={(e) => updateChecklistGroup(gIdx, { _addCode: e.target.value })}
                        >
                          <MenuItem value="">{t("tasks.config.selectTask")}</MenuItem>
                          {tasks
                            .filter(
                              (t) => !(group.items || []).some((it) => it.task_code === t.code),
                            )
                            .map((t) => (
                              <MenuItem key={t.code} value={t.code}>
                                {t.name} ({t.code})
                              </MenuItem>
                            ))}
                        </TextField>
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={!group._addCode}
                          onClick={() => {
                            if (!group._addCode) return;
                            updateChecklistGroup(gIdx, {
                              items: [
                                ...(group.items || []),
                                { task_code: group._addCode, required: true },
                              ],
                              _addCode: "",
                            });
                          }}
                        >
                          {t("tasks.config.addTask")}
                        </Button>
                      </Stack>
                    </Paper>
                  ))}
                </Stack>
                <FormControlLabel
                  control={
                    <Switch
                      checked={checklistDraft.active !== false}
                      onChange={(e) =>
                        setChecklistDraft({ ...checklistDraft, active: e.target.checked })
                      }
                    />
                  }
                  label={t("tasks.config.active")}
                />
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy} onClick={saveChecklist}>
                    {t("tasks.config.saveChecklist")}
                  </Button>
                  <Button disabled={busy} onClick={() => setChecklistDraft(null)}>
                    {t("tasks.config.cancel")}
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
