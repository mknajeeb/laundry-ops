import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  Grid,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import PrintIcon from "@mui/icons-material/Print";
import SaveIcon from "@mui/icons-material/Save";
import {
  computeContractorPayment,
  getContractorPaymentSummaries,
  getContractorPaymentYtd,
  getContractorPrefill,
  getContractors,
  postContractorPaymentRecord,
  postContractorPaymentSummary,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import ContractorDocumentsPanel from "./ContractorDocumentsPanel";
import packetMarkdown from "../contractorForms/veewash_1099_contractor_packet.md?raw";
import ContractorFormEditor from "../contractorForms/ContractorFormEditor";
import ContractorEngagementLetterPrint from "../contractorForms/ContractorEngagementLetterPrint";
import ContractorInvoicePaymentPrint, {
  calcServiceAmount,
  emptyPaymentRecord,
} from "../contractorForms/ContractorInvoicePaymentPrint";
import ContractorPrintShell from "../contractorForms/ContractorPrintShell";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import { CONTRACTOR_FORMS, findContractorForm } from "../contractorForms/formCatalog";
import { emptyFormValues } from "../contractorForms/formFieldSchemas";
import { buildMultiSectionPrintHtml } from "../contractorForms/prefillMarkdown";
import { parsePacketSections } from "../contractorForms/parsePacket";
import "../contractorForms/contractorPrint.css";

const PAYMENT_METHODS = ["Check", "ACH", "Zelle", "Venmo", "Cash", "Other"];
const MANUAL_OPTION = { user_id: null, label: "Manual entry (no profile)", manual: true };

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function MarkdownFormPrint({ html }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}

export default function ContractorManagementPanel() {
  const { t } = useI18n();
  const { user: authUser } = useAuth();
  const printRef = useRef(null);
  const sections = useMemo(() => parsePacketSections(packetMarkdown), []);

  const [contractors, setContractors] = useState([]);
  const [selected, setSelected] = useState(null);
  const [prefill, setPrefill] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(0);
  const [activeFormId, setActiveFormId] = useState("written_warning");
  const [formFieldValues, setFormFieldValues] = useState({});
  const [savedRecords, setSavedRecords] = useState([]);
  const [saving, setSaving] = useState(false);
  const [ytdPrior, setYtdPrior] = useState(0);
  const [record, setRecord] = useState(() => emptyPaymentRecord({}, "regular"));

  const loadContractors = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getContractors();
      setContractors(res.data?.contractors || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Failed to load contractors");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadContractors();
  }, [loadContractors]);

  const contractorType = record.contractor_type || "regular";
  const isRegular = contractorType === "regular";
  const isManual = selected?.manual === true;

  const loadContractor = useCallback(
    async (userId) => {
      if (!userId) {
        setPrefill(null);
        return;
      }
      setError("");
      try {
        const year = new Date().getFullYear();
        const [preRes, sumRes, ytdRes] = await Promise.all([
          getContractorPrefill(userId),
          getContractorPaymentSummaries(userId).catch(() => ({ data: { items: [] } })),
          getContractorPaymentYtd(userId, year).catch(() => ({
            data: { total_paid_ytd: 0, year },
          })),
        ]);
        const pre = {
          ...(preRes.data || {}),
          organization_logo_url:
            preRes.data?.organization_logo_url || authUser?.organization_logo_url || null,
        };
        setPrefill(pre);
        setSavedRecords(sumRes.data?.items || []);
        const ytd = Number(ytdRes.data?.total_paid_ytd) || 0;
        setYtdPrior(ytd);
        const kind =
          pre.worker_kind === "short_term"
            ? "temp"
            : pre.worker_kind === "1099"
              ? "regular"
              : "regular";
        setRecord((r) => ({
          ...emptyPaymentRecord(pre, kind),
          ...r,
          contractor_type: kind,
          worker_name: pre.full_name || r.worker_name,
          worker_phone: pre.phone || r.worker_phone,
          worker_email: pre.email || r.worker_email,
          service_rate: pre.rate_per_hour != null ? String(pre.rate_per_hour) : r.service_rate,
          payment_method: pre.payment_method || r.payment_method,
          total_paid_ytd_prior: String(ytd),
        }));
        setFormFieldValues((prev) => {
          const next = { ...prev };
          for (const f of CONTRACTOR_FORMS) {
            if (!next[f.id]) next[f.id] = emptyFormValues(f.id, pre);
          }
          return next;
        });
      } catch (e) {
        setError(e.response?.data?.error || e.message || "Failed to load contractor");
      }
    },
    [authUser?.organization_logo_url],
  );

  useEffect(() => {
    if (selected?.manual) {
      setPrefill(null);
      setYtdPrior(0);
      setSavedRecords([]);
      setRecord(emptyPaymentRecord({}, "one_time"));
      return;
    }
    if (selected?.user_id) loadContractor(selected.user_id);
    else {
      setPrefill(null);
      setRecord(emptyPaymentRecord({}, "regular"));
    }
  }, [selected?.user_id, selected?.manual, loadContractor]);

  const recalcAmounts = useCallback(
    async (next) => {
      const hours = next.approved_hours;
      const rate = next.service_rate;
      const hs = isRegular ? next.health_safety_credit_hours : 0;
      const adj = next.adjustment_amount;
      try {
        const res = await computeContractorPayment({
          approved_service_hours: hours || 0,
          service_rate: rate || 0,
          health_safety_credit_hours: hs || 0,
          adjustments: adj || 0,
        });
        const d = res.data || {};
        setRecord((r) => ({
          ...r,
          ...next,
          service_amount: d.service_amount ?? 0,
          health_safety_credit_amount: d.health_safety_credit_amount ?? 0,
          total_amount_due: d.total_payment ?? 0,
        }));
      } catch {
        const sa = calcServiceAmount(hours, rate);
        const hsa = isRegular
          ? calcServiceAmount(hs, rate)
          : 0;
        const total =
          Math.round((sa + hsa + (Number(adj) || 0)) * 100) / 100;
        setRecord((r) => ({
          ...r,
          ...next,
          service_amount: sa,
          health_safety_credit_amount: hsa,
          total_amount_due: total,
        }));
      }
    },
    [isRegular],
  );

  const onRecordField = (key, value) => {
    const next = { ...record, [key]: value };
    if (key === "approved_hours" || key === "service_rate") {
      const sa = calcServiceAmount(next.approved_hours, next.service_rate);
      next.service_amount = sa;
      if (!next.amount_paid && sa > 0) next.amount_paid = String(sa);
    }
    if (
      ["approved_hours", "service_rate", "health_safety_credit_hours", "adjustment_amount"].includes(
        key,
      )
    ) {
      recalcAmounts(next);
    } else {
      setRecord(next);
    }
  };

  const onContractorType = (type) => {
    const next = { ...record, contractor_type: type };
    if (type !== "regular") {
      next.health_safety_credit_hours = "";
      next.health_safety_credit_amount = 0;
    }
    recalcAmounts(next);
  };

  const formDef = findContractorForm(activeFormId);
  const activeFormValues = useMemo(
    () => formFieldValues[activeFormId] || emptyFormValues(activeFormId, prefill || {}),
    [formFieldValues, activeFormId, prefill],
  );

  const formHtml = useMemo(() => {
    if (!formDef?.sections?.length) return "";
    return buildMultiSectionPrintHtml(
      sections,
      formDef.sections,
      prefill || {},
      activeFormValues,
      { formId: activeFormId, formValues: activeFormValues },
    );
  }, [formDef, sections, prefill, activeFormValues, activeFormId]);

  const [engagementLetter, setEngagementLetter] = useState({
    first_work_date: "",
    last_work_date: "",
    services_description: "Laundry support / folding",
    avg_weekly_pay: "",
    avg_monthly_pay: "",
    total_paid_period: "",
  });

  const printTitle = useMemo(() => {
    if (tab === 0) return "Contractor Invoice & Payment Receipt";
    if (tab === 2) return formDef?.title || "";
    return "";
  }, [tab, formDef]);

  const doPrint = () => {
    requestAnimationFrame(() => {
      openPrintWindow(printRef.current);
    });
  };

  const savePaymentRecord = async () => {
    setSaving(true);
    setError("");
    try {
      const body = {
        ...record,
        user_id: selected?.manual ? null : selected?.user_id,
        approved_service_hours: Number(record.approved_hours) || 0,
        approved_hours: Number(record.approved_hours) || 0,
        adjustments: Number(record.adjustment_amount) || 0,
        adjustment_amount: Number(record.adjustment_amount) || 0,
        health_safety_credit_hours: isRegular
          ? Number(record.health_safety_credit_hours) || 0
          : 0,
        service_rate: Number(record.service_rate) || 0,
        total_amount_due: Number(record.total_amount_due) || 0,
        amount_paid: Number(record.amount_paid) || 0,
        total_payment: Number(record.amount_paid) || Number(record.total_amount_due) || 0,
        pay_period_start: record.work_period_start,
        pay_period_end: record.work_period_end,
        source_type: "manual",
        status: "paid",
        form_snapshot_json: { ...(prefill || {}), ...record },
      };
      let res;
      if (selected?.user_id && !selected?.manual) {
        res = await postContractorPaymentSummary(selected.user_id, body);
      } else {
        res = await postContractorPaymentRecord(body);
      }
      setSavedRecords((prev) => [res.data, ...prev]);
      const newPrior =
        (Number(record.total_paid_ytd_prior) || 0) + (Number(record.amount_paid) || 0);
      setYtdPrior(newPrior);
      setRecord((r) => ({ ...r, total_paid_ytd_prior: String(newPrior) }));
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const contractorOptions = [
    MANUAL_OPTION,
    ...contractors.map((c) => {
      const tag =
        c.worker_kind === "short_term"
          ? ` · ${t("contractor.shortTermTag")}`
          : "";
      return {
        ...c,
        label: `${c.full_name || "Worker"}${c.contractor_id ? ` (${c.contractor_id})` : ""}${tag}`,
      };
    }),
  ];

  const ytdIncluding =
    (Number(record.total_paid_ytd_prior) || 0) + (Number(record.amount_paid) || 0);

  const canWork = selected && (selected.manual || prefill);

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2 }} className="no-print">
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          {t("contractor.selectTitle")}
        </Typography>
        <Autocomplete
          options={contractorOptions}
          loading={loading}
          value={selected}
          onChange={(_, v) => setSelected(v)}
          getOptionLabel={(o) => o?.label || ""}
          isOptionEqualToValue={(a, b) =>
            a?.manual === b?.manual && a?.user_id === b?.user_id
          }
          renderInput={(params) => (
            <TextField
              {...params}
              label={t("contractor.selectLabel")}
              placeholder={t("contractor.selectHint")}
            />
          )}
          sx={{ maxWidth: 560 }}
        />
        {prefill && !isManual ? (
          <Box sx={{ mt: 2 }}>
            <Grid container spacing={1}>
              <Grid item xs={12} sm={4}>
                <Typography variant="caption" color="text.secondary">
                  {t("contractor.fieldName")}
                </Typography>
                <Typography variant="body2">{prefill.full_name || "—"}</Typography>
              </Grid>
              <Grid item xs={12} sm={4}>
                <Typography variant="caption" color="text.secondary">
                  {t("contractor.fieldRate")}
                </Typography>
                <Typography variant="body2">
                  {prefill.rate_per_hour != null ? `$${prefill.rate_per_hour}/hr` : "—"}
                </Typography>
              </Grid>
              <Grid item xs={12} sm={4}>
                <Typography variant="caption" color="text.secondary">
                  Emergency contact
                </Typography>
                <Typography variant="body2">{prefill.emergency_contact || "—"}</Typography>
              </Grid>
            </Grid>
          </Box>
        ) : null}
      </Paper>

      {canWork ? (
        <>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} className="no-print">
            <Tab label="Invoice & Payment Receipt" />
            <Tab label="Documents" disabled={isManual} />
            <Tab label={t("contractor.tabForms")} />
          </Tabs>

          {tab === 0 ? (
            <Paper sx={{ p: 2 }} className="no-print">
              <Typography variant="h6" sx={{ mb: 1 }}>
                Contractor Invoice &amp; Payment Receipt
              </Typography>
              <FormControl sx={{ mb: 2 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Contractor type
                </Typography>
                <RadioGroup
                  row
                  value={contractorType}
                  onChange={(e) => onContractorType(e.target.value)}
                >
                  <FormControlLabel
                    value="regular"
                    control={<Radio size="small" />}
                    label="Regular Contractor"
                  />
                  <FormControlLabel
                    value="temp"
                    control={<Radio size="small" />}
                    label="Temporary / Short-Term"
                  />
                  <FormControlLabel
                    value="one_time"
                    control={<Radio size="small" />}
                    label="One-Time"
                  />
                </RadioGroup>
              </FormControl>

              <Typography variant="subtitle2" color="primary" sx={{ mt: 1 }}>
                Part 1 — Invoice / Work Summary (no signature required)
              </Typography>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12} sm={6}>
                  <TextField
                    fullWidth
                    size="small"
                    label="Worker name"
                    value={record.worker_name}
                    onChange={(e) => onRecordField("worker_name", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    label="Phone"
                    value={record.worker_phone}
                    onChange={(e) => onRecordField("worker_phone", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    label="Email"
                    value={record.worker_email}
                    onChange={(e) => onRecordField("worker_email", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="date"
                    InputLabelProps={{ shrink: true }}
                    label={t("contractor.periodStart")}
                    value={record.work_period_start}
                    onChange={(e) => onRecordField("work_period_start", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="date"
                    InputLabelProps={{ shrink: true }}
                    label={t("contractor.periodEnd")}
                    value={record.work_period_end}
                    onChange={(e) => onRecordField("work_period_end", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12}>
                  <TextField
                    fullWidth
                    size="small"
                    multiline
                    minRows={2}
                    label="Work performed"
                    value={record.work_performed}
                    onChange={(e) => onRecordField("work_performed", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    label="Approved hours"
                    helperText={t("contractor.manualHoursHint")}
                    value={record.approved_hours}
                    onChange={(e) => onRecordField("approved_hours", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    label={t("contractor.serviceRate")}
                    value={record.service_rate}
                    onChange={(e) => onRecordField("service_rate", e.target.value)}
                  />
                </Grid>
                {isRegular ? (
                  <Grid item xs={12} sm={3}>
                    <TextField
                      fullWidth
                      size="small"
                      type="number"
                      label={t("contractor.hsCreditHours")}
                      value={record.health_safety_credit_hours}
                      onChange={(e) =>
                        onRecordField("health_safety_credit_hours", e.target.value)
                      }
                    />
                  </Grid>
                ) : null}
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    label={t("contractor.adjustments")}
                    value={record.adjustment_amount}
                    onChange={(e) => onRecordField("adjustment_amount", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12}>
                  <Typography variant="body1">
                    <strong>Total amount due:</strong> $
                    {Number(record.total_amount_due || 0).toFixed(2)}
                    <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 2 }}>
                      YTD before: ${Number(record.total_paid_ytd_prior || 0).toFixed(2)} · Including
                      this payment: ${ytdIncluding.toFixed(2)}
                    </Typography>
                  </Typography>
                </Grid>
              </Grid>

              <Typography variant="subtitle2" color="primary" sx={{ mt: 2 }}>
                Part 2 — Payment Receipt (signature required on printed copy)
              </Typography>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    label="Amount paid"
                    value={record.amount_paid}
                    onChange={(e) => onRecordField("amount_paid", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    select
                    label={t("contractor.paymentMethod")}
                    value={record.payment_method}
                    onChange={(e) => onRecordField("payment_method", e.target.value)}
                  >
                    <MenuItem value="">—</MenuItem>
                    {PAYMENT_METHODS.map((m) => (
                      <MenuItem key={m} value={m}>
                        {m}
                      </MenuItem>
                    ))}
                  </TextField>
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    label={t("contractor.paymentRef")}
                    value={record.payment_reference}
                    onChange={(e) => onRecordField("payment_reference", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="date"
                    InputLabelProps={{ shrink: true }}
                    label={t("contractor.receiptPaymentDate")}
                    value={record.payment_date}
                    onChange={(e) => onRecordField("payment_date", e.target.value)}
                  />
                </Grid>
              </Grid>

              <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                <Button
                  variant="contained"
                  startIcon={<SaveIcon />}
                  disabled={saving}
                  onClick={savePaymentRecord}
                >
                  {saving ? t("common.saving") : "Save payment record"}
                </Button>
                <Button variant="outlined" startIcon={<PrintIcon />} onClick={doPrint}>
                  {t("contractor.printPreview")}
                </Button>
              </Stack>
              {savedRecords.length ? (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="subtitle2">Recent payment records</Typography>
                  {savedRecords.slice(0, 8).map((s) => (
                    <Typography key={s.id} variant="body2" color="text.secondary">
                      #{s.id}{" "}
                      {s.pay_period_start || s.work_period_start || "?"} –{" "}
                      {s.pay_period_end || s.work_period_end || "?"} · $
                      {Number(s.amount_paid ?? s.total_payment ?? 0).toFixed(2)}
                    </Typography>
                  ))}
                </Box>
              ) : null}
            </Paper>
          ) : null}

          {tab === 1 ? (
            <Paper sx={{ p: 2 }} className="no-print">
              <ContractorDocumentsPanel
                userId={selected?.user_id}
                contractorType={contractorType}
                ytdTotal={ytdIncluding}
              />
            </Paper>
          ) : null}

          {tab === 2 ? (
            <Grid container spacing={2} className="no-print">
              <Grid item xs={12} md={4}>
                <Paper sx={{ p: 1.5 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    {t("contractor.formsList")}
                  </Typography>
                  <Stack spacing={0.5}>
                    {CONTRACTOR_FORMS.map((f) => (
                      <Button
                        key={f.id}
                        size="small"
                        variant={activeFormId === f.id ? "contained" : "text"}
                        sx={{ justifyContent: "flex-start", textAlign: "left" }}
                        onClick={() => setActiveFormId(f.id)}
                        disabled={isManual && f.id === "first_time_packet"}
                      >
                        {f.title}
                      </Button>
                    ))}
                  </Stack>
                </Paper>
              </Grid>
              <Grid item xs={12} md={8}>
                <Paper sx={{ p: 2 }}>
                  <Typography variant="h6" sx={{ mb: 1 }}>
                    {formDef?.title}
                  </Typography>
                  {activeFormId === "engagement_verification_letter" ? (
                    <Stack spacing={1} sx={{ mb: 2 }}>
                      <TextField
                        size="small"
                        type="date"
                        label="First work date"
                        InputLabelProps={{ shrink: true }}
                        value={engagementLetter.first_work_date}
                        onChange={(e) =>
                          setEngagementLetter((l) => ({ ...l, first_work_date: e.target.value }))
                        }
                      />
                      <TextField
                        size="small"
                        type="date"
                        label="Last work date"
                        InputLabelProps={{ shrink: true }}
                        value={engagementLetter.last_work_date}
                        onChange={(e) =>
                          setEngagementLetter((l) => ({ ...l, last_work_date: e.target.value }))
                        }
                      />
                      <TextField
                        size="small"
                        label="Services description"
                        value={engagementLetter.services_description}
                        onChange={(e) =>
                          setEngagementLetter((l) => ({
                            ...l,
                            services_description: e.target.value,
                          }))
                        }
                      />
                      <TextField
                        size="small"
                        type="number"
                        label="Total paid in period ($)"
                        value={engagementLetter.total_paid_period}
                        onChange={(e) =>
                          setEngagementLetter((l) => ({ ...l, total_paid_period: e.target.value }))
                        }
                      />
                    </Stack>
                  ) : (
                    <ContractorFormEditor
                      formId={activeFormId}
                      values={activeFormValues}
                      onChange={(next) =>
                        setFormFieldValues((prev) => ({ ...prev, [activeFormId]: next }))
                      }
                    />
                  )}
                  <Button
                    variant="contained"
                    startIcon={<PrintIcon />}
                    sx={{ mt: 2 }}
                    onClick={doPrint}
                  >
                    {t("contractor.printForm")}
                  </Button>
                </Paper>
              </Grid>
            </Grid>
          ) : null}

          <Box ref={printRef} className="contractor-print-area">
            <ContractorPrintShell prefill={prefill || { company_name: "VeeWash" }} documentTitle={printTitle}>
              {tab === 0 ? (
                <ContractorInvoicePaymentPrint record={record} prefill={prefill} />
              ) : null}
              {tab === 2 && activeFormId === "engagement_verification_letter" ? (
                <ContractorEngagementLetterPrint
                  prefill={prefill}
                  letter={{
                    ...engagementLetter,
                    worker_name: record.worker_name,
                    worker_category: record.contractor_type,
                    worker_category_label:
                      record.contractor_type === "temp"
                        ? "Temp Contractor"
                        : "1099 Contractor",
                  }}
                />
              ) : null}
              {tab === 2 && activeFormId !== "engagement_verification_letter" && formHtml ? (
                <MarkdownFormPrint html={formHtml} />
              ) : null}
            </ContractorPrintShell>
          </Box>
        </>
      ) : (
        <Alert severity="info">{t("contractor.pickContractor")}</Alert>
      )}
    </Stack>
  );
}
