import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Divider,
  Grid,
  MenuItem,
  Paper,
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
  getContractorPrefill,
  getContractors,
  postContractorPaymentSummary,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import packetMarkdown from "../contractorForms/veewash_1099_contractor_packet.md?raw";
import { CONTRACTOR_FORMS, findContractorForm } from "../contractorForms/formCatalog";
import { applyPrefillToMarkdown, markdownToPrintHtml } from "../contractorForms/prefillMarkdown";
import { buildFormMarkdown, parsePacketSections } from "../contractorForms/parsePacket";
import "../contractorForms/contractorPrint.css";

const PAYMENT_METHODS = ["Check", "ACH", "Zelle", "Venmo", "Cash", "Other"];

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function BiweeklySummaryPrint({ prefill, payment, extras }) {
  const snap = payment.form_snapshot || prefill;
  const name = snap.full_name || prefill.full_name || "";
  const pm = payment.payment_method || prefill.payment_method || "";
  return (
    <div className="contractor-print-root">
      <Typography component="p" sx={{ fontWeight: 700, fontSize: "14pt", mb: 1 }}>
        VeeWash / Washpro
      </Typography>
      <Typography component="p" sx={{ mb: 2 }}>
        {prefill.company_address || "10438 Jamaica Avenue, Richmond Hill, NY 11418"}
      </Typography>
      <h2>Contractor Payment Summary</h2>
      <p>
        <strong>Contractor Name:</strong> {name}
      </p>
      <p>
        <strong>Invoice Period:</strong> From {payment.pay_period_start || "________"} To{" "}
        {payment.pay_period_end || "________"}
      </p>
      <p>
        <strong>Invoice Date:</strong> {payment.invoice_date || todayIso()}
      </p>
      <table className="contractor-payment-table">
        <tbody>
          <tr>
            <td>Approved service hours</td>
            <td>{Number(payment.approved_service_hours || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Service rate</td>
            <td>${Number(payment.service_rate || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Service amount</td>
            <td>${Number(payment.service_amount || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Health &amp; Safety Credit hours, if any</td>
            <td>{Number(payment.health_safety_credit_hours || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Health &amp; Safety Credit amount, if any</td>
            <td>${Number(payment.health_safety_credit_amount || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Adjustments, if any</td>
            <td>${Number(payment.adjustments || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>
              <strong>Total contractor payment</strong>
            </td>
            <td>
              <strong>${Number(payment.total_payment || 0).toFixed(2)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        <strong>Payment Method:</strong> {pm || "________________"}
      </p>
      <p>
        <strong>Payment Reference:</strong> {payment.payment_reference || "________________"}
      </p>
      {payment.notes ? (
        <p>
          <strong>Notes:</strong>
          <br />
          {payment.notes}
        </p>
      ) : null}
      <p style={{ marginTop: "1rem", fontSize: "10pt" }}>
        Contractor confirms that this invoice/payment summary accurately reflects approved service
        time and payment, unless Contractor notifies the Company of an error. This payment summary
        confirms contractor payment only and does not waive any legal rights.
      </p>
      <div className="sig-block">
        <div>
          <strong>Contractor Signature</strong>
          <div className="sig-line" />
          <strong>Date</strong>
          <div className="sig-line" />
        </div>
        <div>
          <strong>Company Signature</strong>
          <div className="sig-line" />
          <strong>Date</strong>
          <div className="sig-line" />
        </div>
      </div>
      {extras?.company_representative ? (
        <p style={{ fontSize: "9pt", marginTop: "1rem" }}>
          Prepared by: {extras.company_representative}
        </p>
      ) : null}
    </div>
  );
}

function MarkdownFormPrint({ html }) {
  return (
    <div
      className="contractor-print-root"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default function ContractorManagementPanel() {
  const { t } = useI18n();
  const printRef = useRef(null);
  const sections = useMemo(() => parsePacketSections(packetMarkdown), []);

  const [contractors, setContractors] = useState([]);
  const [selected, setSelected] = useState(null);
  const [prefill, setPrefill] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(0);
  const [activeFormId, setActiveFormId] = useState("biweekly_payment_summary");
  const [formExtras, setFormExtras] = useState({
    issued_by: "",
    company_representative: "",
    effective_date: todayIso(),
    notice_date: todayIso(),
  });
  const [savedSummaries, setSavedSummaries] = useState([]);
  const [saving, setSaving] = useState(false);

  const [payment, setPayment] = useState({
    pay_period_start: "",
    pay_period_end: "",
    invoice_date: todayIso(),
    approved_service_hours: "",
    service_rate: "",
    health_safety_credit_hours: "",
    adjustments: "",
    payment_method: "",
    payment_reference: "",
    notes: "",
    service_amount: 0,
    health_safety_credit_amount: 0,
    total_payment: 0,
  });

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

  const loadContractor = useCallback(async (userId) => {
    if (!userId) {
      setPrefill(null);
      return;
    }
    setError("");
    try {
      const [preRes, sumRes] = await Promise.all([
        getContractorPrefill(userId),
        getContractorPaymentSummaries(userId).catch(() => ({ data: { items: [] } })),
      ]);
      const pre = preRes.data || {};
      setPrefill(pre);
      setSavedSummaries(sumRes.data?.items || []);
      setPayment((p) => ({
        ...p,
        service_rate: pre.rate_per_hour != null ? String(pre.rate_per_hour) : p.service_rate,
        payment_method: pre.payment_method || p.payment_method,
      }));
      setFormExtras((ex) => ({
        ...ex,
        effective_date: pre.start_date || ex.effective_date,
      }));
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Failed to load contractor");
    }
  }, []);

  useEffect(() => {
    if (selected?.user_id) loadContractor(selected.user_id);
  }, [selected?.user_id, loadContractor]);

  const recalcPayment = useCallback(async (next) => {
    const body = {
      approved_service_hours: next.approved_service_hours || 0,
      service_rate: next.service_rate || 0,
      health_safety_credit_hours: next.health_safety_credit_hours || 0,
      adjustments: next.adjustments || 0,
    };
    try {
      const res = await computeContractorPayment(body);
      const d = res.data || {};
      setPayment((p) => ({
        ...p,
        ...next,
        service_amount: d.service_amount ?? 0,
        health_safety_credit_amount: d.health_safety_credit_amount ?? 0,
        total_payment: d.total_payment ?? 0,
      }));
    } catch {
      const hours = Number(next.approved_service_hours) || 0;
      const rate = Number(next.service_rate) || 0;
      const hs = Number(next.health_safety_credit_hours) || 0;
      const adj = Number(next.adjustments) || 0;
      const sa = Math.round(hours * rate * 100) / 100;
      const hsa = Math.round(hs * rate * 100) / 100;
      setPayment((p) => ({
        ...p,
        ...next,
        service_amount: sa,
        health_safety_credit_amount: hsa,
        total_payment: Math.round((sa + hsa + adj) * 100) / 100,
      }));
    }
  }, []);

  const onPaymentField = (key, value) => {
    const next = { ...payment, [key]: value };
    if (
      ["approved_service_hours", "service_rate", "health_safety_credit_hours", "adjustments"].includes(
        key,
      )
    ) {
      recalcPayment(next);
    } else {
      setPayment(next);
    }
  };

  const formDef = findContractorForm(activeFormId);
  const formMarkdown = useMemo(() => {
    if (!formDef) return "";
    return buildFormMarkdown(sections, formDef.sections);
  }, [formDef, sections]);

  const formHtml = useMemo(() => {
    if (!formMarkdown || activeFormId === "biweekly_payment_summary") return "";
    const merged = applyPrefillToMarkdown(formMarkdown, prefill || {}, formExtras);
    return markdownToPrintHtml(merged);
  }, [formMarkdown, prefill, formExtras, activeFormId]);

  const doPrint = () => {
    window.print();
  };

  const saveAndPrintSummary = async () => {
    if (!selected?.user_id) return;
    setSaving(true);
    setError("");
    try {
      const snapshot = { ...(prefill || {}), ...formExtras, _snapshot_note: "Form values at print time" };
      const body = {
        ...payment,
        approved_service_hours: Number(payment.approved_service_hours) || 0,
        service_rate: Number(payment.service_rate) || 0,
        health_safety_credit_hours: Number(payment.health_safety_credit_hours) || 0,
        adjustments: Number(payment.adjustments) || 0,
        clock_hours_source: "manual",
        form_snapshot_json: snapshot,
      };
      const res = await postContractorPaymentSummary(selected.user_id, body);
      setSavedSummaries((prev) => [res.data, ...prev]);
      setTimeout(() => window.print(), 300);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const contractorOptions = contractors.map((c) => ({
    ...c,
    label: `${c.full_name || "Contractor"}${c.contractor_id ? ` (${c.contractor_id})` : ""}`,
  }));

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
          isOptionEqualToValue={(a, b) => a?.user_id === b?.user_id}
          renderInput={(params) => (
            <TextField {...params} label={t("contractor.selectLabel")} placeholder={t("contractor.selectHint")} />
          )}
          sx={{ maxWidth: 520 }}
        />
        {prefill ? (
          <Box sx={{ mt: 2 }}>
            <Typography variant="body2" color="text.secondary">
              {t("contractor.masterNote")}
            </Typography>
            <Grid container spacing={1} sx={{ mt: 0.5 }}>
              <Grid item xs={12} sm={6} md={4}>
                <Typography variant="caption" color="text.secondary">
                  {t("contractor.fieldName")}
                </Typography>
                <Typography variant="body2">{prefill.full_name || "—"}</Typography>
              </Grid>
              <Grid item xs={12} sm={6} md={4}>
                <Typography variant="caption" color="text.secondary">
                  {t("contractor.fieldRate")}
                </Typography>
                <Typography variant="body2">
                  {prefill.rate_per_hour != null ? `$${prefill.rate_per_hour}/hr` : "—"}
                </Typography>
              </Grid>
              <Grid item xs={12} sm={6} md={4}>
                <Typography variant="caption" color="text.secondary">
                  {t("contractor.fieldStatus")}
                </Typography>
                <Typography variant="body2">{prefill.status || "—"}</Typography>
              </Grid>
            </Grid>
            {!prefill.is_contractor ? (
              <Alert severity="warning" sx={{ mt: 1 }}>
                {t("contractor.not1099Warning")}
              </Alert>
            ) : null}
          </Box>
        ) : null}
      </Paper>

      {selected && prefill ? (
        <>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} className="no-print">
            <Tab label={t("contractor.tabPayment")} />
            <Tab label={t("contractor.tabForms")} />
          </Tabs>

          {tab === 0 ? (
            <Paper sx={{ p: 2 }} className="no-print">
              <Typography variant="h6" sx={{ mb: 1 }}>
                {t("contractor.paymentTitle")}
              </Typography>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="date"
                    label={t("contractor.periodStart")}
                    InputLabelProps={{ shrink: true }}
                    value={payment.pay_period_start}
                    onChange={(e) => onPaymentField("pay_period_start", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="date"
                    label={t("contractor.periodEnd")}
                    InputLabelProps={{ shrink: true }}
                    value={payment.pay_period_end}
                    onChange={(e) => onPaymentField("pay_period_end", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="date"
                    label={t("contractor.invoiceDate")}
                    InputLabelProps={{ shrink: true }}
                    value={payment.invoice_date}
                    onChange={(e) => onPaymentField("invoice_date", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    inputProps={{ min: 0, step: 0.25 }}
                    label={t("contractor.approvedHours")}
                    helperText={t("contractor.manualHoursHint")}
                    value={payment.approved_service_hours}
                    onChange={(e) => onPaymentField("approved_service_hours", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    inputProps={{ min: 0, step: 0.01 }}
                    label={t("contractor.serviceRate")}
                    value={payment.service_rate}
                    onChange={(e) => onPaymentField("service_rate", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    inputProps={{ min: 0, step: 0.25 }}
                    label={t("contractor.hsCreditHours")}
                    value={payment.health_safety_credit_hours}
                    onChange={(e) => onPaymentField("health_safety_credit_hours", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    inputProps={{ step: 0.01 }}
                    label={t("contractor.adjustments")}
                    value={payment.adjustments}
                    onChange={(e) => onPaymentField("adjustments", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    select
                    label={t("contractor.paymentMethod")}
                    value={payment.payment_method}
                    onChange={(e) => onPaymentField("payment_method", e.target.value)}
                  >
                    <MenuItem value="">—</MenuItem>
                    {PAYMENT_METHODS.map((m) => (
                      <MenuItem key={m} value={m}>
                        {m}
                      </MenuItem>
                    ))}
                  </TextField>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <TextField
                    fullWidth
                    size="small"
                    label={t("contractor.paymentRef")}
                    value={payment.payment_reference}
                    onChange={(e) => onPaymentField("payment_reference", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12}>
                  <TextField
                    fullWidth
                    size="small"
                    multiline
                    minRows={2}
                    label={t("contractor.notes")}
                    value={payment.notes}
                    onChange={(e) => onPaymentField("notes", e.target.value)}
                  />
                </Grid>
                <Grid item xs={12}>
                  <Typography variant="body1">
                    <strong>{t("contractor.total")}:</strong> $
                    {Number(payment.total_payment || 0).toFixed(2)}
                    <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 2 }}>
                      ({t("contractor.serviceAmt")}: ${Number(payment.service_amount || 0).toFixed(2)}
                      {payment.health_safety_credit_amount
                        ? ` · ${t("contractor.hsAmt")}: $${Number(payment.health_safety_credit_amount).toFixed(2)}`
                        : ""}
                      )
                    </Typography>
                  </Typography>
                </Grid>
              </Grid>
              <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                <Button
                  variant="contained"
                  startIcon={<SaveIcon />}
                  disabled={saving}
                  onClick={saveAndPrintSummary}
                >
                  {saving ? t("common.saving") : t("contractor.saveAndPrint")}
                </Button>
                <Button variant="outlined" startIcon={<PrintIcon />} onClick={doPrint}>
                  {t("contractor.printPreview")}
                </Button>
              </Stack>
              {savedSummaries.length ? (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="subtitle2">{t("contractor.recentSummaries")}</Typography>
                  {savedSummaries.slice(0, 5).map((s) => (
                    <Typography key={s.id} variant="body2" color="text.secondary">
                      #{s.id} {s.pay_period_start || "?"} – {s.pay_period_end || "?"} · $
                      {Number(s.total_payment || 0).toFixed(2)}
                    </Typography>
                  ))}
                </Box>
              ) : null}
            </Paper>
          ) : null}

          {tab === 1 ? (
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
                  {formDef?.description ? (
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      {formDef.description}
                    </Typography>
                  ) : null}
                  <Grid container spacing={1} sx={{ mb: 2 }}>
                    <Grid item xs={12} sm={6}>
                      <TextField
                        fullWidth
                        size="small"
                        label={t("contractor.issuedBy")}
                        value={formExtras.issued_by}
                        onChange={(e) =>
                          setFormExtras((ex) => ({ ...ex, issued_by: e.target.value }))
                        }
                      />
                    </Grid>
                    <Grid item xs={12} sm={6}>
                      <TextField
                        fullWidth
                        size="small"
                        label={t("contractor.companyRep")}
                        value={formExtras.company_representative}
                        onChange={(e) =>
                          setFormExtras((ex) => ({
                            ...ex,
                            company_representative: e.target.value,
                          }))
                        }
                      />
                    </Grid>
                    <Grid item xs={12} sm={6}>
                      <TextField
                        fullWidth
                        size="small"
                        type="date"
                        InputLabelProps={{ shrink: true }}
                        label={t("contractor.effectiveDate")}
                        value={formExtras.effective_date}
                        onChange={(e) =>
                          setFormExtras((ex) => ({ ...ex, effective_date: e.target.value }))
                        }
                      />
                    </Grid>
                    <Grid item xs={12} sm={6}>
                      <TextField
                        fullWidth
                        size="small"
                        type="date"
                        InputLabelProps={{ shrink: true }}
                        label={t("contractor.noticeDate")}
                        value={formExtras.notice_date}
                        onChange={(e) =>
                          setFormExtras((ex) => ({ ...ex, notice_date: e.target.value }))
                        }
                      />
                    </Grid>
                  </Grid>
                  <Button variant="contained" startIcon={<PrintIcon />} onClick={doPrint}>
                    {t("contractor.printForm")}
                  </Button>
                </Paper>
              </Grid>
            </Grid>
          ) : null}

          <Box ref={printRef} className="contractor-print-area">
            {tab === 0 ? (
              <BiweeklySummaryPrint prefill={prefill} payment={payment} extras={formExtras} />
            ) : null}
            {tab === 1 && activeFormId === "biweekly_payment_summary" ? (
              <BiweeklySummaryPrint prefill={prefill} payment={payment} extras={formExtras} />
            ) : null}
            {tab === 1 && activeFormId !== "biweekly_payment_summary" && formHtml ? (
              <MarkdownFormPrint html={formHtml} />
            ) : null}
          </Box>
        </>
      ) : (
        <Alert severity="info">{t("contractor.pickContractor")}</Alert>
      )}
    </Stack>
  );
}
