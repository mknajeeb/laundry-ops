import {
  Box,
  Checkbox,
  FormControlLabel,
  FormGroup,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

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
      options: Array.isArray(f.options) ? f.options : [],
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

/** Client-side required check before submit. */
export function validateInputClient(schema, values, remarks) {
  for (const field of normalizeInputSchema(schema)) {
    if (!field.required) continue;
    const raw = values?.[field.id];
    if (field.type === "checkbox" && !raw) {
      return `${field.label} is required`;
    }
    if (field.type === "checklist" && (!Array.isArray(raw) || !raw.length)) {
      return `${field.label} is required`;
    }
    if (field.type !== "checkbox" && field.type !== "checklist" && (raw === "" || raw == null)) {
      return `${field.label} is required`;
    }
  }
  return "";
}

export function formatCompletionInput(completionInput) {
  if (!completionInput) return null;
  const values = completionInput.values || completionInput;
  if (!values || typeof values !== "object") return null;
  const parts = Object.entries(values).map(([k, v]) => {
    if (Array.isArray(v)) return `${k}: ${v.join(", ")}`;
    if (typeof v === "boolean") return `${k}: ${v ? "Yes" : "No"}`;
    return `${k}: ${v}`;
  });
  if (completionInput.remarks) parts.push(`Notes: ${completionInput.remarks}`);
  return parts.join(" · ");
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
  const fields = normalizeInputSchema(schema);
  if (!fields.length) {
    return (
      <TextField
        fullWidth
        size="small"
        label="Comments (optional)"
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
        const value = values?.[field.id];
        if (field.type === "number") {
          return (
            <TextField
              key={field.id}
              fullWidth
              size="small"
              type="number"
              label={field.label}
              required={field.required}
              value={value ?? ""}
              disabled={disabled}
              onChange={(e) => onChangeValues?.({ ...values, [field.id]: e.target.value })}
              sx={{ bgcolor: "#fff" }}
            />
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
        label="Comments (optional)"
        value={remarks || ""}
        disabled={disabled}
        onChange={(e) => onChangeRemarks?.(e.target.value)}
        sx={{ bgcolor: "#fff" }}
      />
    </Stack>
  );
}
