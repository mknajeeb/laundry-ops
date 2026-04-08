import {
  Alert,
  Button,
  Divider,
  FormControl,
  FormControlLabel,
  FormLabel,
  InputLabel,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Add, DeleteOutline } from "@mui/icons-material";
import { I9_LIST_A, I9_LIST_B, I9_LIST_C } from "../../constants/i9AcceptableDocuments";
import { useStreetAutocomplete } from "../GooglePlacesAutocomplete";
import { useI18n } from "../../i18n/I18nContext";
import { maskTaxIdLast4, normalizeTaxIdDigits } from "../../utils/validation";

export function emptyWork() {
  return {
    mailing_address_line1: "",
    address_line1: "",
    address_line2: "",
    city: "",
    state: "",
    zip: "",
    middle_initial: "",
    other_last_name: "",
    job_title: "",
    department: "",
    supervisor_name: "",
    primary_work_location: "",
    language_preference: "",
    /** VF-01 pack: worker classification */
    worker_type: "",
    laundry_experience_yes: "",
    laundry_experience_detail: "",
    essential_duties_ack: false,
    rehire_start_date: "",
  };
}

export function emptyEmergency() {
  return [
    { name: "", relationship: "", phone: "", alt_phone: "" },
    { name: "", relationship: "", phone: "", alt_phone: "" },
  ];
}

export function emptyPreparer() {
  return {
    last_name: "",
    first_name: "",
    middle_initial: "",
    address: "",
    city: "",
    state: "",
    zip: "",
  };
}

export function emptyI9() {
  return {
    legal_first_name: "",
    legal_last_name: "",
    employee_email: "",
    other_last_names: "",
    apt_number: "",
    ssn: "",
    citizenship: "",
    uscis_a_number: "",
    form_i94_admission: "",
    foreign_passport: "",
    work_authorization_expiration: "",
    document_route: "list_a",
    list_a_title: "",
    list_b_title: "",
    list_c_title: "",
    employer_authorized_representative: "",
    preparers: [],
    section2: {},
  };
}

function I9DocSelect({ label, value, onChange, options, disabled, required: req }) {
  return (
    <FormControl fullWidth size="small" disabled={disabled} required={!!req}>
      <InputLabel>{label}</InputLabel>
      <Select label={label} value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <MenuItem value="">
          <em>—</em>
        </MenuItem>
        {options.map((o) => (
          <MenuItem key={o} value={o}>
            {o}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

function PreparerFields({
  idx,
  prepRaw,
  setI9,
  canEdit,
  t,
  ep,
  streetAutocompleteEnabled,
}) {
  const prep = { ...ep(), ...prepRaw };
  const { inputRef } = useStreetAutocomplete(
    (p) => {
      setI9((s) => {
        const pr = [...(s.preparers || [])];
        const base = { ...ep(), ...(pr[idx] || {}) };
        pr[idx] = {
          ...base,
          address: p.street || base.address,
          city: p.city || base.city,
          state: p.state || base.state,
          zip: p.zip || base.zip,
        };
        return { ...s, preparers: pr };
      });
    },
    Boolean(canEdit && streetAutocompleteEnabled),
  );

  return (
    <Stack spacing={1}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField
          label={t("hr.i9FamilyName")}
          value={prep.last_name}
          onChange={(e) =>
            setI9((s) => {
              const pr = [...(s.preparers || [])];
              pr[idx] = { ...pr[idx], last_name: e.target.value };
              return { ...s, preparers: pr };
            })
          }
          fullWidth
          size="small"
          disabled={!canEdit}
          required
          placeholder={t("hr.i9FamilyName")}
        />
        <TextField
          label={t("hr.i9GivenName")}
          value={prep.first_name}
          onChange={(e) =>
            setI9((s) => {
              const pr = [...(s.preparers || [])];
              pr[idx] = { ...pr[idx], first_name: e.target.value };
              return { ...s, preparers: pr };
            })
          }
          fullWidth
          size="small"
          disabled={!canEdit}
          required
        />
        <TextField
          label={t("hr.middleInitial")}
          value={prep.middle_initial}
          onChange={(e) =>
            setI9((s) => {
              const pr = [...(s.preparers || [])];
              pr[idx] = { ...pr[idx], middle_initial: e.target.value.slice(0, 1) };
              return { ...s, preparers: pr };
            })
          }
          fullWidth
          size="small"
          disabled={!canEdit}
          inputProps={{ maxLength: 1 }}
        />
      </Stack>
      <TextField
        inputRef={inputRef}
        label={t("hr.addressLine1")}
        value={prep.address}
        onChange={(e) =>
          setI9((s) => {
            const pr = [...(s.preparers || [])];
            pr[idx] = { ...pr[idx], address: e.target.value };
            return { ...s, preparers: pr };
          })
        }
        fullWidth
        size="small"
        disabled={!canEdit}
        required
        helperText={streetAutocompleteEnabled ? t("hr.i9PreparerMapsHint") : undefined}
      />
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField
          label={t("hr.city")}
          value={prep.city}
          onChange={(e) =>
            setI9((s) => {
              const pr = [...(s.preparers || [])];
              pr[idx] = { ...pr[idx], city: e.target.value };
              return { ...s, preparers: pr };
            })
          }
          fullWidth
          size="small"
          disabled={!canEdit}
          required
        />
        <TextField
          label={t("hr.state")}
          value={prep.state}
          onChange={(e) =>
            setI9((s) => {
              const pr = [...(s.preparers || [])];
              pr[idx] = { ...pr[idx], state: e.target.value };
              return { ...s, preparers: pr };
            })
          }
          fullWidth
          size="small"
          disabled={!canEdit}
          required
        />
        <TextField
          label={t("hr.zip")}
          value={prep.zip}
          onChange={(e) =>
            setI9((s) => {
              const pr = [...(s.preparers || [])];
              pr[idx] = { ...pr[idx], zip: e.target.value };
              return { ...s, preparers: pr };
            })
          }
          fullWidth
          size="small"
          disabled={!canEdit}
          required
        />
      </Stack>
    </Stack>
  );
}

export default function I9DetailsForm({
  i9,
  setI9,
  canEdit,
  emptyPreparer: emptyPrep,
  /** Hide name/email/apt captured on Payroll / Basic — server still merges payroll + work_json for PDFs */
  omitIdentityFields = false,
  /** Wire Google Places to preparer street when tab is visible (see User profile Compliance). */
  streetAutocompleteEnabled = true,
  /**
   * Payroll tab TIN digits (session). API never returns full SSN; keep Compliance + Payroll in sync when
   * `omitIdentityFields` is true (User profile).
   */
  payrollTaxIdDigits = "",
  onPayrollTaxIdDigitsChange,
}) {
  const { t } = useI18n();
  const ep = emptyPrep || emptyPreparer;
  const ssnFieldDigits = normalizeTaxIdDigits(i9.ssn || payrollTaxIdDigits || "");

  return (
    <Stack spacing={1.5}>
      {omitIdentityFields ? (
        <Alert severity="info" sx={{ py: 0.5 }}>
          {t("hr.i9IdentityFromPayroll")}
        </Alert>
      ) : null}
      {!omitIdentityFields ? (
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField
          label={t("hr.i9LegalFirst")}
          value={i9.legal_first_name}
          onChange={(e) => setI9((s) => ({ ...s, legal_first_name: e.target.value }))}
          fullWidth
          size="small"
          disabled={!canEdit}
          required
        />
        <TextField
          label={t("hr.i9LegalLast")}
          value={i9.legal_last_name}
          onChange={(e) => setI9((s) => ({ ...s, legal_last_name: e.target.value }))}
          fullWidth
          size="small"
          disabled={!canEdit}
          required
        />
      </Stack>
      ) : null}
      {!omitIdentityFields ? (
      <TextField
        label={t("hr.i9EmployeeEmail")}
        type="email"
        value={i9.employee_email || ""}
        onChange={(e) => setI9((s) => ({ ...s, employee_email: e.target.value }))}
        fullWidth
        size="small"
        disabled={!canEdit}
        required
        helperText={t("hr.i9EmployeeEmailHelp")}
      />
      ) : null}
      {!omitIdentityFields ? (
      <TextField
        label={t("hr.i9OtherLastNames")}
        value={i9.other_last_names}
        onChange={(e) => setI9((s) => ({ ...s, other_last_names: e.target.value }))}
        fullWidth
        size="small"
        disabled={!canEdit}
      />
      ) : null}
      {!omitIdentityFields ? (
      <TextField
        label={t("hr.i9Apt")}
        value={i9.apt_number}
        onChange={(e) => setI9((s) => ({ ...s, apt_number: e.target.value }))}
        fullWidth
        size="small"
        disabled={!canEdit}
      />
      ) : null}
      <TextField
        label={t("hr.i9Ssn")}
        value={ssnFieldDigits}
        onChange={(e) => {
          const v = normalizeTaxIdDigits(e.target.value);
          setI9((s) => ({ ...s, ssn: v }));
          onPayrollTaxIdDigitsChange?.(v);
        }}
        fullWidth
        size="small"
        disabled={!canEdit}
        required
        placeholder="123456789"
        helperText={
          ssnFieldDigits.length >= 4
            ? `${t("hr.i9SsnHelp")} ${maskTaxIdLast4(ssnFieldDigits)}`
            : t("hr.i9SsnHelp")
        }
      />
      <FormControl
        disabled={!canEdit}
        required
        sx={{
          width: "100%",
          alignItems: "stretch",
          "& .MuiFormControlLabel-root": { alignItems: "flex-start", ml: 0, mr: 0 },
          "& .MuiRadio-root": { pt: 0.35 },
          "& .MuiFormControlLabel-label": { whiteSpace: "normal", lineHeight: 1.35, fontSize: "0.875rem" },
        }}
      >
        <FormLabel required>{t("hr.i9Citizenship")}</FormLabel>
        <RadioGroup value={i9.citizenship} onChange={(e) => setI9((s) => ({ ...s, citizenship: e.target.value }))}>
          <FormControlLabel value="1" control={<Radio size="small" />} label={t("hr.i9Cit1")} />
          <FormControlLabel value="2" control={<Radio size="small" />} label={t("hr.i9Cit2")} />
          <FormControlLabel value="3" control={<Radio size="small" />} label={t("hr.i9Cit3")} />
          <FormControlLabel value="4" control={<Radio size="small" />} label={t("hr.i9Cit4")} />
        </RadioGroup>
      </FormControl>
      {i9.citizenship === "3" ? (
        <TextField
          label={t("hr.i9UscisA")}
          value={i9.uscis_a_number}
          onChange={(e) => setI9((s) => ({ ...s, uscis_a_number: e.target.value }))}
          fullWidth
          size="small"
          disabled={!canEdit}
          required
        />
      ) : null}
      {i9.citizenship === "4" ? (
        <Stack spacing={1}>
          <TextField
            label={t("hr.i9WorkAuthExp")}
            type="date"
            value={i9.work_authorization_expiration || ""}
            onChange={(e) => setI9((s) => ({ ...s, work_authorization_expiration: e.target.value }))}
            InputLabelProps={{ shrink: true }}
            fullWidth
            size="small"
            disabled={!canEdit}
            required
          />
          <TextField
            label={t("hr.i9I94")}
            value={i9.form_i94_admission}
            onChange={(e) => setI9((s) => ({ ...s, form_i94_admission: e.target.value }))}
            fullWidth
            size="small"
            disabled={!canEdit}
            required
          />
          <TextField
            label={t("hr.i9Passport")}
            value={i9.foreign_passport}
            onChange={(e) => setI9((s) => ({ ...s, foreign_passport: e.target.value }))}
            fullWidth
            size="small"
            disabled={!canEdit}
            required
          />
        </Stack>
      ) : null}
      <Divider />
      <FormControl disabled={!canEdit} required>
        <FormLabel required>{t("hr.i9DocRoute")}</FormLabel>
        <RadioGroup value={i9.document_route} onChange={(e) => setI9((s) => ({ ...s, document_route: e.target.value }))}>
          <FormControlLabel value="list_a" control={<Radio size="small" />} label={t("hr.i9RouteA")} />
          <FormControlLabel value="list_bc" control={<Radio size="small" />} label={t("hr.i9RouteBC")} />
        </RadioGroup>
      </FormControl>
      {i9.document_route === "list_a" ? (
        <I9DocSelect
          label={t("hr.i9ListA")}
          value={i9.list_a_title}
          onChange={(v) => setI9((s) => ({ ...s, list_a_title: v }))}
          options={I9_LIST_A}
          disabled={!canEdit}
          required
        />
      ) : (
        <Stack spacing={1}>
          <I9DocSelect
            label={t("hr.i9ListB")}
            value={i9.list_b_title}
            onChange={(v) => setI9((s) => ({ ...s, list_b_title: v }))}
            options={I9_LIST_B}
            disabled={!canEdit}
            required
          />
          <I9DocSelect
            label={t("hr.i9ListC")}
            value={i9.list_c_title}
            onChange={(v) => setI9((s) => ({ ...s, list_c_title: v }))}
            options={I9_LIST_C}
            disabled={!canEdit}
            required
          />
        </Stack>
      )}
      <TextField
        label={t("hr.i9EmployerRep")}
        value={i9.employer_authorized_representative}
        onChange={(e) => setI9((s) => ({ ...s, employer_authorized_representative: e.target.value }))}
        fullWidth
        size="small"
        disabled={!canEdit}
        required
        placeholder="Last, First, Title"
      />
      <Divider />
      <Typography variant="subtitle2">{t("hr.i9Preparers")}</Typography>
      <Typography variant="caption" color="text.secondary">
        {t("hr.i9PreparerNote")}
      </Typography>
      {(i9.preparers || []).map((prepRaw, idx) => (
          <Paper key={idx} variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
              <Typography variant="caption" fontWeight={600}>
                {t("hr.i9PreparerPrefix")} {idx + 1}
              </Typography>
              {canEdit ? (
                <Button
                  size="small"
                  color="inherit"
                  startIcon={<DeleteOutline />}
                  onClick={() =>
                    setI9((s) => ({
                      ...s,
                      preparers: (s.preparers || []).filter((_, j) => j !== idx),
                    }))
                  }
                >
                  {t("common.delete")}
                </Button>
              ) : null}
            </Stack>
            {idx === 1 ? (
              <Alert severity="info" sx={{ mb: 1 }}>
                {t("hr.i9PreparerRow2Pdf")}
              </Alert>
            ) : null}
            <PreparerFields
              idx={idx}
              prepRaw={prepRaw}
              setI9={setI9}
              canEdit={canEdit}
              t={t}
              ep={ep}
              streetAutocompleteEnabled={streetAutocompleteEnabled}
            />
          </Paper>
        ))}
      {canEdit && (i9.preparers || []).length < 4 ? (
        <Button startIcon={<Add />} variant="outlined" onClick={() => setI9((s) => ({ ...s, preparers: [...(s.preparers || []), ep()] }))}>
          {t("hr.i9AddPreparer")}
        </Button>
      ) : null}
    </Stack>
  );
}
