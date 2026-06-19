import { COMMON_META_FIELDS, schemaForForm } from "./formFieldSchemas";

function FieldInput({ field, value, onChange }) {
  const id = `w2form-${field.key}`;
  if (field.type === "multiline") {
    return (
      <textarea
        id={id}
        className="form-control"
        rows={3}
        value={value ?? ""}
        onChange={(e) => onChange(field.key, e.target.value)}
      />
    );
  }
  if (field.type === "number") {
    return (
      <input
        id={id}
        type="number"
        step="0.01"
        className="form-control"
        value={value ?? ""}
        onChange={(e) => onChange(field.key, e.target.value)}
      />
    );
  }
  if (field.type === "date") {
    return (
      <input
        id={id}
        type="date"
        className="form-control"
        value={value ?? ""}
        onChange={(e) => onChange(field.key, e.target.value)}
      />
    );
  }
  return (
    <input
      id={id}
      type="text"
      className="form-control"
      value={value ?? ""}
      onChange={(e) => onChange(field.key, e.target.value)}
    />
  );
}

function CheckboxGroup({ field, values, onChange }) {
  return (
    <div className="cform-editor-checks">
      {field.options.map((opt) => {
        const key = `${field.key}__${opt.id}`;
        const checked = !!values[key];
        return (
          <label key={key} className="cform-editor-check">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => {
                if (field.single) {
                  for (const o of field.options) {
                    onChange(`${field.key}__${o.id}`, false);
                  }
                }
                onChange(key, e.target.checked);
              }}
            />
            <span>{opt.label}</span>
          </label>
        );
      })}
    </div>
  );
}

export default function W2FormEditor({ formId, values, onChange, showCommon = true }) {
  const schema = schemaForForm(formId);
  const set = (key, val) => onChange({ ...values, [key]: val });

  const commonKeys = new Set(COMMON_META_FIELDS.map((f) => f.key));
  const formFields = (schema.fields || []).filter((f) => !commonKeys.has(f.key));

  return (
    <div className="cform-editor">
      {showCommon ? (
        <div className="cform-editor-grid">
          {COMMON_META_FIELDS.map((field) => (
            <label key={field.key} className="cform-editor-field">
              <span>{field.label}</span>
              <FieldInput field={field} value={values[field.key]} onChange={set} />
            </label>
          ))}
        </div>
      ) : null}
      {formFields.length > 0 ? (
        <div className="cform-editor-grid" style={{ marginTop: showCommon ? "0.75rem" : 0 }}>
          {formFields.map((field) => (
            <label
              key={field.key}
              className={`cform-editor-field${field.type === "checkbox_group" ? " cform-editor-field--full" : ""}`}
            >
              <span>{field.label}</span>
              {field.type === "checkbox_group" ? (
                <CheckboxGroup field={field} values={values} onChange={set} />
              ) : (
                <FieldInput field={field} value={values[field.key]} onChange={set} />
              )}
            </label>
          ))}
        </div>
      ) : null}
    </div>
  );
}
