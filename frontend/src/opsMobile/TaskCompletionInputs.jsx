import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  FormGroup,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getAuthToken, getWashproApiBase } from "../api";
import { useI18n } from "../i18n/I18nContext";

export function conditionMet(condition, values) {
  if (!condition || typeof condition !== "object") return true;
  if (Array.isArray(condition.any)) return condition.any.some((part) => conditionMet(part, values));
  if (Array.isArray(condition.all)) return condition.all.every((part) => conditionMet(part, values));
  const current = values?.[condition.field];
  if (Array.isArray(condition.in)) return condition.in.map(String).includes(String(current ?? ""));
  if (condition.gt != null) {
    const number = Number(current);
    return Number.isFinite(number) && number > Number(condition.gt);
  }
  return true;
}

export function fieldShown(field, values) {
  if (!field?.show_when) return true;
  return conditionMet(field.show_when, values);
}

export function fieldRequired(field, values) {
  if (!fieldShown(field, values)) return false;
  if (field.required_when && conditionMet(field.required_when, values)) return true;
  return field.required !== false;
}

function optionList(options) {
  return (Array.isArray(options) ? options : [])
    .map((opt) => {
      if (typeof opt === "string") return { value: opt, label: opt };
      const value = String(opt?.value || opt?.id || "");
      return value ? { value, label: String(opt.label || value) } : null;
    })
    .filter(Boolean);
}

/** Normalize schema entries from task config. */
export function normalizeInputSchema(schema) {
  if (!Array.isArray(schema)) return [];
  return schema
    .filter((f) => f && (f.id || f.key))
    .map((f) => ({
      id: String(f.id || f.key),
      label: String(f.label || f.id || f.key),
      type: String(f.type || "text"),
      required: f.required !== false,
      options: optionList(f.options),
      show_when: f.show_when || null,
      required_when: f.required_when || null,
      min: f.min == null || f.min === "" ? null : Number(f.min),
    }));
}

export function emptyInputValues(schema) {
  const values = {};
  for (const field of normalizeInputSchema(schema)) {
    if (field.type === "yes_no") values[field.id] = "";
    else if (field.type === "checkbox") values[field.id] = false;
    else if (field.type === "checklist") values[field.id] = [];
    else values[field.id] = "";
  }
  return values;
}

function valueEmpty(field, raw) {
  if (field.type === "checkbox") return !raw;
  if (field.type === "machine_numbers") {
    if (Array.isArray(raw)) return raw.join("").trim() === "";
    return String(raw || "").trim() === "";
  }
  if (field.type === "checklist" || field.type === "photo") {
    return !Array.isArray(raw) || raw.length === 0;
  }
  return raw === "" || raw == null;
}

/** Client-side required check before submit. */
export function validateInputClient(schema, values) {
  const fields = normalizeInputSchema(schema);
  for (const field of fields) {
    if (!fieldShown(field, values)) continue;
    const raw = values?.[field.id];
    if (fieldRequired(field, values) && valueEmpty(field, raw)) {
      return `${field.label} is required`;
    }
    if (field.type === "number" && raw !== "" && raw != null && field.min != null && Number(raw) < field.min) {
      return `${field.label} cannot be less than ${field.min}`;
    }
  }
  return "";
}

export function formatCompletionInput(completionInput, schema) {
  if (!completionInput) return null;
  const values = completionInput.values || completionInput;
  if (!values || typeof values !== "object") return null;
  const fields = normalizeInputSchema(schema);
  const byId = Object.fromEntries(fields.map((field) => [field.id, field]));
  const parts = [];
  const keys = fields.length ? fields.map((field) => field.id) : Object.keys(values);
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(values, key)) continue;
    const field = byId[key];
    if (field && !fieldShown(field, values)) continue;
    const raw = values[key];
    const label = field?.label || key;
    if (Array.isArray(raw) && raw.some((part) => part && typeof part === "object" && part.token)) {
      parts.push(`${label}: ${raw.length} photo${raw.length === 1 ? "" : "s"}`);
      continue;
    }
    if (field?.type === "choice") {
      const match = field.options.find((opt) => opt.value === String(raw));
      parts.push(`${label}: ${match?.label || raw}`);
      continue;
    }
    if (Array.isArray(raw)) parts.push(`${label}: ${raw.join(", ")}`);
    else if (typeof raw === "boolean") parts.push(`${label}: ${raw ? "Yes" : "No"}`);
    else if (raw !== "" && raw != null) parts.push(`${label}: ${raw}`);
  }
  if (completionInput.remarks) parts.push(`Notes: ${completionInput.remarks}`);
  return parts.join(" · ") || null;
}

export function completionPhotoTokens(completionInput) {
  const values = completionInput?.values || {};
  const tokens = [];
  for (const raw of Object.values(values)) {
    if (!Array.isArray(raw)) continue;
    for (const part of raw) {
      if (part?.token) tokens.push(part.token);
    }
  }
  return tokens;
}

function TaskPhotoThumb({ token }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    const base = getWashproApiBase();
    fetch(`${base}/api/management/task-completion-photos/${token}`, {
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    })
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => {
        if (!blob || cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token]);
  if (!url) return null;
  return (
    <Box
      component="img"
      alt="Checklist photo"
      src={url}
      sx={{ width: 72, height: 72, objectFit: "cover", borderRadius: 1 }}
    />
  );
}

export function CompletionDetails({ completionInput, schema }) {
  const text = formatCompletionInput(completionInput, schema);
  const tokens = completionPhotoTokens(completionInput);
  if (!text && !tokens.length) return null;
  return (
    <Box sx={{ mt: 0.25 }}>
      {text ? (
        <Typography variant="caption" color="text.secondary" display="block">
          {text}
        </Typography>
      ) : null}
      {tokens.length ? (
        <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: "wrap" }}>
          {tokens.map((token) => (
            <TaskPhotoThumb key={token} token={token} />
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}

/**
 * Dynamic completion inputs for PIN Tasks (number/text/yes_no/checkbox/checklist + remarks).
 */
export default function TaskCompletionInputs({
  schema,
  values,
  remarks,
  onChangeValues,
  onChangeRemarks,
  disabled,
}) {
  const { t } = useI18n();
  const fields = normalizeInputSchema(schema);
  if (!fields.length) {
    return (
      <TextField
        fullWidth
        size="small"
        label={t("tasks.pin.commentsOptional")}
        value={remarks || ""}
        disabled={disabled}
        onChange={(e) => onChangeRemarks?.(e.target.value)}
        sx={{ bgcolor: "#fff" }}
      />
    );
  }

  return (
    <Stack spacing={1.25}>
      {fields.map((field) => {
        if (!fieldShown(field, values)) return null;
        const value = values?.[field.id];
        const required = fieldRequired(field, values);
        if (field.type === "number") {
          return (
            <TextField
              key={field.id}
              fullWidth
              size="small"
              type="number"
              label={field.label}
              required={required}
              value={value ?? ""}
              disabled={disabled}
              inputProps={field.min == null ? undefined : { min: field.min }}
              onChange={(e) => onChangeValues?.({ ...values, [field.id]: e.target.value })}
              sx={{ bgcolor: "#fff" }}
            />
          );
        }
        if (field.type === "choice") {
          return (
            <Box key={field.id}>
              <Typography variant="body2" sx={{ fontWeight: 800, mb: 0.5 }}>
                {field.label}
                {required ? " *" : ""}
              </Typography>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                {field.options.map((opt) => (
                  <Button
                    key={opt.value}
                    variant={String(value) === opt.value ? "contained" : "outlined"}
                    disabled={disabled}
                    onClick={() => onChangeValues?.({ ...values, [field.id]: opt.value })}
                    sx={{ textTransform: "none", fontWeight: 800, minHeight: 44 }}
                  >
                    {opt.label}
                  </Button>
                ))}
              </Stack>
            </Box>
          );
        }
        if (field.type === "machine_numbers") {
          const text = Array.isArray(value) ? value.join(", ") : value ?? "";
          return (
            <TextField
              key={field.id}
              fullWidth
              size="small"
              label={field.label}
              required={required}
              value={text}
              disabled={disabled}
              placeholder="12, 18, 24"
              onChange={(e) => onChangeValues?.({ ...values, [field.id]: e.target.value })}
              sx={{ bgcolor: "#fff" }}
            />
          );
        }
        if (field.type === "photo") {
          const photos = Array.isArray(value) ? value : [];
          return (
            <Box key={field.id}>
              <Typography variant="body2" sx={{ fontWeight: 800, mb: 0.5 }}>
                {field.label}
                {required ? " *" : ""}
              </Typography>
              <Button variant="outlined" component="label" disabled={disabled} sx={{ textTransform: "none" }}>
                Add photo
                <input
                  hidden
                  accept="image/jpeg,image/png,image/webp"
                  type="file"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (!file) return;
                    const reader = new FileReader();
                    reader.onload = () => {
                      const data = String(reader.result || "");
                      const dataBase64 = data.includes(",") ? data.split(",")[1] : data;
                      onChangeValues?.({
                        ...values,
                        [field.id]: [
                          ...photos,
                          { content_type: file.type || "image/jpeg", data_base64: dataBase64, name: file.name },
                        ].slice(0, 4),
                      });
                    };
                    reader.readAsDataURL(file);
                  }}
                />
              </Button>
              {photos.length ? (
                <Typography variant="caption" display="block">
                  {photos.length} photo{photos.length === 1 ? "" : "s"} selected
                </Typography>
              ) : null}
            </Box>
          );
        }
        if (field.type === "yes_no") {
          return (
            <TextField
              key={field.id}
              select
              fullWidth
              size="small"
              label={field.label}
              required={field.required}
              value={value ?? ""}
              disabled={disabled}
              onChange={(e) => onChangeValues?.({ ...values, [field.id]: e.target.value })}
              sx={{ bgcolor: "#fff" }}
            >
              <MenuItem value="">Select…</MenuItem>
              <MenuItem value="yes">Yes</MenuItem>
              <MenuItem value="no">No</MenuItem>
            </TextField>
          );
        }
        if (field.type === "checkbox") {
          return (
            <FormControlLabel
              key={field.id}
              control={
                <Checkbox
                  checked={!!value}
                  disabled={disabled}
                  onChange={(e) => onChangeValues?.({ ...values, [field.id]: e.target.checked })}
                />
              }
              label={`${field.label}${field.required ? " *" : ""}`}
            />
          );
        }
        if (field.type === "checklist") {
          const opts = field.options.length
            ? field.options
            : [{ id: "done", label: field.label }];
          const selected = Array.isArray(value) ? value : [];
          return (
            <Box key={field.id}>
              <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
                {field.label}
                {field.required ? " *" : ""}
              </Typography>
              <FormGroup>
                {opts.map((opt) => {
                  const oid = String(opt.id || opt.value || opt.label || opt);
                  const olabel = String(opt.label || opt.name || oid);
                  return (
                    <FormControlLabel
                      key={oid}
                      control={
                        <Checkbox
                          checked={selected.includes(oid)}
                          disabled={disabled}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? [...selected, oid]
                              : selected.filter((x) => x !== oid);
                            onChangeValues?.({ ...values, [field.id]: next });
                          }}
                        />
                      }
                      label={olabel}
                    />
                  );
                })}
              </FormGroup>
            </Box>
          );
        }
        return (
          <TextField
            key={field.id}
            fullWidth
            size="small"
            label={field.label}
            required={field.required}
            value={value ?? ""}
            disabled={disabled}
            onChange={(e) => onChangeValues?.({ ...values, [field.id]: e.target.value })}
            sx={{ bgcolor: "#fff" }}
          />
        );
      })}
      <TextField
        fullWidth
        size="small"
        label={t("tasks.pin.commentsOptional")}
        value={remarks || ""}
        disabled={disabled}
        onChange={(e) => onChangeRemarks?.(e.target.value)}
        sx={{ bgcolor: "#fff" }}
      />
    </Stack>
  );
}
