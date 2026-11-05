import {
  Box,
  Button,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";
import VerifyingScheduleRoleField from "./VerifyingScheduleRoleField";

function blankField() {
  return {
    id: `field_${Date.now().toString(36)}`,
    type: "text",
    label: "",
    required: false,
    optionsText: "",
    showField: "",
    showValues: "",
    min: "",
  };
}

function fieldToSchema(field) {
  const schema = {
    id: field.id || "field",
    type: field.type || "text",
    label: field.label || "Field",
    required: field.required !== false && !field.showField && !field.show_when,
  };
  if (field.type === "choice") {
    const labels = String(field.optionsText || "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    const original = Array.isArray(field.options) ? field.options : [];
    const originalLabels = original.map((opt) => String(opt.label || opt.value || opt));
    schema.options =
      original.length && originalLabels.join(", ") === labels.join(", ")
        ? original
        : labels.map((label) => ({
            value: label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "option",
            label,
          }));
    schema.required = true;
  }
  if (field.type === "number" && field.min !== "" && field.min != null) {
    schema.min = Number(field.min);
  }
  if (field.showField && field.showValues) {
    const values = String(field.showValues)
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    const numeric = values.length === 1 && values[0].startsWith(">");
    schema.show_when = numeric
      ? { field: field.showField, gt: Number(values[0].slice(1)) }
      : { field: field.showField, in: values };
    if (field.required) schema.required_when = schema.show_when;
  } else if (field.show_when) {
    schema.show_when = field.show_when;
    if (field.required_when) schema.required_when = field.required_when;
    if (field.required && !schema.required_when) schema.required_when = field.show_when;
  }
  return schema;
}

function schemaToFields(schema) {
  return (schema || []).map((field, index) => ({
    id: field.id || `field_${index}`,
    type: field.type || "text",
    label: field.label || "",
    required: field.required !== false || Boolean(field.required_when),
    options: field.options || [],
    optionsText: (field.options || []).map((opt) => opt.label || opt.value || opt).join(", "),
    show_when: field.show_when?.field ? null : field.show_when || null,
    required_when: field.show_when?.field ? null : field.required_when || null,
    showField: field.show_when?.field || "",
    showValues: Array.isArray(field.show_when?.in)
      ? field.show_when.in.join(", ")
      : field.show_when?.gt != null
        ? `>${field.show_when.gt}`
        : "",
    min: field.min == null ? "" : String(field.min),
  }));
}

function blankItem(sectionLabel, sectionOrder) {
  return {
    task_code: "",
    task_name: "",
    instructions: "",
    instructions_es: "",
    section_label_es: "",
    task_name_es: "",
    required: true,
    active: true,
    section_label: sectionLabel || "",
    section_order: sectionOrder || 0,
    responsibility_mode: "team",
    responsibility_user_ids: [],
    acknowledgment_mode: "any",
    verification_inherits: true,
    verification_method: "supervisor",
    verification_timing: "same_shift",
    input_schema: [],
    fields: [],
  };
}

export function itemsFromGroup(items) {
  return (items || []).map((item) => ({
    task_code: item.task_code,
    task_name: item.task_name || "",
    instructions: item.instructions || "",
    instructions_es: item.instructions_es || "",
    section_label_es: item.section_label_es || "",
    task_name_es: item.task_name_es || "",
    required: item.required !== false,
    active: item.active !== false,
    section_label: item.section_label || "",
    section_order: item.section_order || 0,
    responsibility_mode: item.responsibility_mode === "named" ? "named" : "team",
    responsibility_user_ids: item.responsibility_user_ids || [],
    acknowledgment_mode: item.acknowledgment_mode === "each" ? "each" : "any",
    verification_inherits: item.verification_inherits !== false,
    verification_method: item.verification_method || "supervisor",
    verification_timing: item.verification_timing || "same_shift",
    verifier_config: item.verifier_config || {},
    input_schema: item.input_schema || [],
    fields: schemaToFields(item.input_schema),
  }));
}

export function itemsToPayload(rows) {
  return (rows || [])
    .filter((row) => row.task_name)
    .map((row, index) => ({
      task_code: row.task_code || "",
      task_name: row.task_name,
      instructions: row.instructions || "",
      instructions_es: row.instructions_es || "",
      section_label_es: row.section_label_es || "",
      task_name_es: row.task_name_es || "",
      required: row.required !== false,
      active: row.active !== false,
      section_label: row.section_label || null,
      section_order: Number(row.section_order || 0),
      display_order: (index + 1) * 10,
      responsibility_mode: row.responsibility_mode === "named" ? "named" : "team",
      responsibility_user_ids: row.responsibility_user_ids || [],
      acknowledgment_mode: row.acknowledgment_mode === "each" ? "each" : "any",
      verification_inherits: row.verification_inherits !== false,
      verification_method: row.verification_inherits === false ? row.verification_method || "supervisor" : null,
      verification_timing: row.verification_inherits === false ? row.verification_timing || "same_shift" : null,
      verifier_config: row.verification_inherits === false ? row.verifier_config || {} : {},
      input_schema: (row.fields || []).filter((field) => field.label).map(fieldToSchema),
    }));
}

export default function ActivityChecklistEditor({ items, assignees = [], scheduleRoles = [], onChange }) {
  const { t } = useI18n();
  const fieldTypes = [
    { value: "choice", label: t("tasks.config.choice") },
    { value: "number", label: t("tasks.config.number") },
    { value: "text", label: t("tasks.config.text") },
    { value: "machine_numbers", label: t("tasks.config.machineNumbers") },
    { value: "photo", label: t("tasks.config.photo") },
    { value: "yes_no", label: t("tasks.config.yesNo") },
    { value: "checkbox", label: t("tasks.config.checkbox") },
  ];
  const rows = items || [];
  const sections = [];
  for (const row of rows) {
    const label = row.section_label || "General";
    let section = sections.find((entry) => entry.label === label);
    if (!section) {
      section = { label, order: Number(row.section_order || 0), indexes: [] };
      sections.push(section);
    }
    section.indexes.push(rows.indexOf(row));
  }
  sections.sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));

  const update = (index, patch) => {
    const next = rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
    onChange(next);
  };

  const renameSection = (label, name) => {
    onChange(rows.map((row) => (row.section_label === label || (!row.section_label && label === "General") ? { ...row, section_label: name } : row)));
  };

  const moveSection = (label, direction) => {
    const ordered = [...sections];
    const index = ordered.findIndex((section) => section.label === label);
    const target = index + direction;
    if (target < 0 || target >= ordered.length) return;
    const [moved] = ordered.splice(index, 1);
    ordered.splice(target, 0, moved);
    const orderByLabel = Object.fromEntries(ordered.map((section, i) => [section.label, (i + 1) * 10]));
    onChange(
      rows.map((row) => ({
        ...row,
        section_order: orderByLabel[row.section_label || "General"] ?? row.section_order,
      }))
    );
  };

  return (
    <Stack spacing={1.25}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontWeight: 800 }}>{t("tasks.config.checklist")}</Typography>
        <Button
          size="small"
          onClick={() =>
            onChange([
              ...rows,
              blankItem(`Section ${sections.length + 1}`, (sections.length + 1) * 10),
            ])
          }
        >
          Add section item
        </Button>
      </Stack>
      {sections.map((section) => (
        <Box key={section.label} sx={{ border: "1px solid #dbe3ea", borderRadius: 1.5, p: 1 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              size="small"
              label={t("tasks.config.section")}
              value={section.label}
              onChange={(e) => renameSection(section.label, e.target.value)}
            />
            <TextField
              size="small"
              label={t("tasks.config.sectionEs")}
              value={rows[section.indexes[0]]?.section_label_es || ""}
              onChange={(e) => {
                const value = e.target.value;
                onChange(
                  rows.map((row) =>
                    row.section_label === section.label || (!row.section_label && section.label === "General")
                      ? { ...row, section_label_es: value }
                      : row,
                  ),
                );
              }}
            />
            <Button size="small" onClick={() => moveSection(section.label, -1)}>
              Section up
            </Button>
            <Button size="small" onClick={() => moveSection(section.label, 1)}>
              Section down
            </Button>
            <Button
              size="small"
              onClick={() =>
                onChange([
                  ...rows,
                  blankItem(section.label === "General" ? "" : section.label, section.order),
                ])
              }
            >
              Add item
            </Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {section.indexes.map((index) => {
              const row = rows[index];
              return (
                <Box key={`${row.task_code || "new"}-${index}`} sx={{ bgcolor: "#f8fafc", borderRadius: 1, p: 1 }}>
                  <Stack spacing={0.75}>
                    <TextField
                      size="small"
                      label={t("tasks.config.itemLabel")}
                      value={row.task_name || ""}
                      onChange={(e) => update(index, { task_name: e.target.value })}
                    />
                    <TextField
                      size="small"
                      label={t("tasks.config.itemLabelEs")}
                      value={row.task_name_es || ""}
                      onChange={(e) => update(index, { task_name_es: e.target.value })}
                    />
                    <TextField
                      size="small"
                      label={t("tasks.config.instructions")}
                      multiline
                      minRows={2}
                      value={row.instructions || ""}
                      onChange={(e) => update(index, { instructions: e.target.value })}
                    />
                    <TextField
                      size="small"
                      label={t("tasks.config.instructionsEs")}
                      multiline
                      minRows={2}
                      value={row.instructions_es || ""}
                      onChange={(e) => update(index, { instructions_es: e.target.value })}
                    />
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      <FormControlLabel
                        control={
                          <Switch
                            checked={row.required !== false}
                            onChange={(e) => update(index, { required: e.target.checked })}
                          />
                        }
                        label={t("tasks.config.required")}
                      />
                      <FormControlLabel
                        control={
                          <Switch
                            checked={row.active !== false}
                            onChange={(e) => update(index, { active: e.target.checked })}
                          />
                        }
                        label={t("tasks.config.active")}
                      />
                    </Stack>
                    <TextField
                      select
                      size="small"
                      label={t("tasks.config.moveSection")}
                      value={row.section_label || ""}
                      onChange={(e) => {
                        const label = e.target.value;
                        const match = sections.find((entry) => entry.label === label);
                        update(index, { section_label: label, section_order: match?.order || 0 });
                      }}
                    >
                      {sections.map((entry) => (
                        <MenuItem key={entry.label} value={entry.label === "General" ? "" : entry.label}>
                          {entry.label}
                        </MenuItem>
                      ))}
                    </TextField>
                    <TextField
                      select
                      size="small"
                      label={t("tasks.config.defaultResponsibility")}
                      value={row.responsibility_mode === "named" ? "named" : "team"}
                      onChange={(e) =>
                        update(index, {
                          responsibility_mode: e.target.value,
                          responsibility_user_ids: e.target.value === "team" ? [] : row.responsibility_user_ids,
                        })
                      }
                    >
                      <MenuItem value="team">Any assigned employee</MenuItem>
                      <MenuItem value="named">Named employees</MenuItem>
                    </TextField>
                    {row.responsibility_mode === "named" ? (
                      <TextField
                        select
                        size="small"
                        label={t("tasks.config.responsibleEmployees")}
                        value={(row.responsibility_user_ids || []).map(String)}
                        SelectProps={{ multiple: true }}
                        onChange={(e) =>
                          update(index, {
                            responsibility_user_ids: []
                              .concat(e.target.value)
                              .map((id) => Number(id))
                              .filter((id) => id > 0),
                          })
                        }
                      >
                        {assignees.map((person) => (
                          <MenuItem key={person.id} value={String(person.id)}>
                            {person.name}
                          </MenuItem>
                        ))}
                      </TextField>
                    ) : null}
                    <TextField
                      select
                      size="small"
                      label={t("tasks.config.acknowledgment")}
                      value={row.acknowledgment_mode === "each" ? "each" : "any"}
                      onChange={(e) => update(index, { acknowledgment_mode: e.target.value })}
                    >
                      <MenuItem value="any">{t("tasks.config.acknowledgmentAny")}</MenuItem>
                      <MenuItem value="each">{t("tasks.config.acknowledgmentEach")}</MenuItem>
                    </TextField>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={row.verification_inherits !== false}
                          onChange={(e) => update(index, { verification_inherits: e.target.checked })}
                        />
                      }
                      label={t("tasks.config.inheritVerification")}
                    />
                    {row.verification_inherits === false ? (
                      <Stack direction={{ xs: "column", sm: "row" }} spacing={0.5}>
                        <TextField
                          select
                          size="small"
                          label={t("tasks.config.verificationMethod")}
                          value={row.verification_method || "supervisor"}
                          onChange={(e) => update(index, { verification_method: e.target.value })}
                        >
                          <MenuItem value="supervisor">{t("tasks.config.supervisor")}</MenuItem>
                          <MenuItem value="employee">{t("tasks.config.employeePeer")}</MenuItem>
                          <MenuItem value="role">{t("tasks.config.roleBased")}</MenuItem>
                          <MenuItem value="schedule_role">{t("tasks.config.scheduleRoleVerification")}</MenuItem>
                          <MenuItem value="none">{t("tasks.config.none")}</MenuItem>
                        </TextField>
                        <TextField
                          select
                          size="small"
                          label={t("tasks.config.verificationTiming")}
                          value={row.verification_timing || "same_shift"}
                          onChange={(e) => update(index, { verification_timing: e.target.value })}
                        >
                          <MenuItem value="same_shift">{t("tasks.config.sameShift")}</MenuItem>
                          <MenuItem value="later_shift">{t("tasks.config.laterShift")}</MenuItem>
                          <MenuItem value="next_day">{t("tasks.config.nextDay")}</MenuItem>
                        </TextField>
                      </Stack>
                    ) : null}
                    <VerifyingScheduleRoleField
                      method={row.verification_inherits === false ? row.verification_method : ""}
                      value={row.verifier_config?.schedule_role}
                      roles={scheduleRoles}
                      onChange={(code) =>
                        update(index, {
                          verifier_config: { ...(row.verifier_config || {}), schedule_role: code },
                        })
                      }
                    />
                    <Typography variant="caption" sx={{ fontWeight: 800 }}>
                      Input fields
                    </Typography>
                    {(row.fields || []).map((field, fieldIndex) => (
                      <Stack key={field.id} direction={{ xs: "column", sm: "row" }} spacing={0.5}>
                        <TextField
                          size="small"
                          label={t("tasks.config.fieldLabel")}
                          value={field.label}
                          onChange={(e) => {
                            const fields = [...row.fields];
                            fields[fieldIndex] = { ...field, label: e.target.value };
                            update(index, { fields });
                          }}
                        />
                        <TextField
                          select
                          size="small"
                          label={t("tasks.config.fieldType")}
                          value={field.type}
                          onChange={(e) => {
                            const fields = [...row.fields];
                            fields[fieldIndex] = { ...field, type: e.target.value };
                            update(index, { fields });
                          }}
                        >
                          {fieldTypes.map((type) => (
                            <MenuItem key={type.value} value={type.value}>
                              {type.label}
                            </MenuItem>
                          ))}
                        </TextField>
                        {field.type === "choice" ? (
                          <TextField
                            size="small"
                            label={t("tasks.config.options")}
                            value={field.optionsText}
                            helperText="Comma-separated"
                            onChange={(e) => {
                              const fields = [...row.fields];
                              fields[fieldIndex] = { ...field, optionsText: e.target.value };
                              update(index, { fields });
                            }}
                          />
                        ) : null}
                        {field.type === "number" ? (
                          <TextField
                            size="small"
                            label={t("tasks.config.minimum")}
                            value={field.min}
                            onChange={(e) => {
                              const fields = [...row.fields];
                              fields[fieldIndex] = { ...field, min: e.target.value };
                              update(index, { fields });
                            }}
                          />
                        ) : null}
                        <TextField
                          size="small"
                          label={t("tasks.config.showWhenField")}
                          value={field.showField}
                          onChange={(e) => {
                            const fields = [...row.fields];
                            fields[fieldIndex] = { ...field, showField: e.target.value };
                            update(index, { fields });
                          }}
                        />
                        <TextField
                          size="small"
                          label={t("tasks.config.showWhenValues")}
                          value={field.showValues}
                          helperText="yes, done, or >0"
                          onChange={(e) => {
                            const fields = [...row.fields];
                            fields[fieldIndex] = { ...field, showValues: e.target.value };
                            update(index, { fields });
                          }}
                        />
                        <FormControlLabel
                          control={
                            <Switch
                              checked={field.required !== false}
                              onChange={(e) => {
                                const fields = [...row.fields];
                                fields[fieldIndex] = { ...field, required: e.target.checked };
                                update(index, { fields });
                              }}
                            />
                          }
                          label={t("tasks.config.required")}
                        />
                      </Stack>
                    ))}
                    <Stack direction="row" spacing={1}>
                      <Button
                        size="small"
                        onClick={() => update(index, { fields: [...(row.fields || []), blankField()] })}
                      >
                        Add field
                      </Button>
                      <Button
                        size="small"
                        onClick={() => {
                          const copy = {
                            ...blankItem(row.section_label, row.section_order),
                            task_name: row.task_name ? `${row.task_name} copy` : "",
                            instructions: row.instructions,
                            fields: (row.fields || []).map((field) => ({
                              ...field,
                              id: `field_${Date.now().toString(36)}_${field.id}`,
                            })),
                          };
                          const next = [...rows];
                          next.splice(index + 1, 0, copy);
                          onChange(next);
                        }}
                      >
                        Duplicate
                      </Button>
                      <Button
                        size="small"
                        onClick={() => {
                          const next = [...rows];
                          if (next[index].task_code) next[index] = { ...next[index], active: false };
                          else next.splice(index, 1);
                          onChange(next);
                        }}
                      >
                        {row.task_code ? "Deactivate" : "Remove"}
                      </Button>
                      <Button
                        size="small"
                        disabled={index === 0}
                        onClick={() => {
                          const next = [...rows];
                          const [moved] = next.splice(index, 1);
                          next.splice(index - 1, 0, moved);
                          onChange(next);
                        }}
                      >
                        Up
                      </Button>
                      <Button
                        size="small"
                        disabled={index === rows.length - 1}
                        onClick={() => {
                          const next = [...rows];
                          const [moved] = next.splice(index, 1);
                          next.splice(index + 1, 0, moved);
                          onChange(next);
                        }}
                      >
                        Down
                      </Button>
                    </Stack>
                  </Stack>
                </Box>
              );
            })}
          </Stack>
        </Box>
      ))}
    </Stack>
  );
}
