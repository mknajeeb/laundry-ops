import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { ArrowBack, ExpandMore } from "@mui/icons-material";
import {
  deleteTaUserDocument,
  getTaHrEmployerSettings,
  getTaUserDocuments,
  getTaUserHrFormsInventory,
  getTaUserHrProfile,
  postTaUserHrForm,
  postTaUserDocument,
  putTaHrEmployerSettings,
  putTaUserDocument,
  putTaUserHrProfile,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import I9DetailsForm, { emptyI9, emptyPreparer, emptyWork, emptyEmergency } from "../components/hr/I9DetailsForm";

function localeLabel(code, t) {
  if (code === "en") return t("hub.localeEn");
  if (code === "es") return t("hub.localeEs");
  if (code === "bilingual") return t("hub.localeBilingual");
  return code;
}

async function saveBlobResponse(res, fallbackName) {
  const blob = res.data;
  if (!(blob instanceof Blob)) return { ok: false, error: "Invalid response" };
  const head = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
  const looksPdf = head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46;
  const looksZip = head[0] === 0x50 && head[1] === 0x4b;
  if (!looksPdf && !looksZip) {
    const text = await blob.text();
    try {
      const j = JSON.parse(text);
      return { ok: false, error: typeof j.error === "string" ? j.error : "Download failed" };
    } catch {
      return { ok: false, error: text.trim().slice(0, 240) || "Download failed" };
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fallbackName;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  return { ok: true };
}

export default function PayrollFormsHubPage({ user: sessionUser }) {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { hasPerm } = useAuth();
  const uid = Number(userId);
  const canEdit = hasPerm("users.edit");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [inventoryLoadError, setInventoryLoadError] = useState("");
  const [inventory, setInventory] = useState({ lanes_detected: [], forms: [] });
  const [tabLane, setTabLane] = useState("employee_w2");
  const [payroll, setPayroll] = useState(null);
  const [preferredName, setPreferredName] = useState("");
  const [dob, setDob] = useState("");
  const [altPhone, setAltPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [work, setWork] = useState(() => emptyWork());
  const [emergency, setEmergency] = useState(() => emptyEmergency());
  const [employerName, setEmployerName] = useState("");
  const [employerAddress, setEmployerAddress] = useState("");
  const [employerEin, setEmployerEin] = useState("");
  const [i9, setI9] = useState(() => emptyI9());
  const [docRows, setDocRows] = useState([]);
  const [docLoading, setDocLoading] = useState(false);
  const [dlBusy, setDlBusy] = useState("");
  const [docDraft, setDocDraft] = useState({
    document_code: "I9",
    document_name: "Form I-9",
    status: "received",
    issued_on: "",
    expires_on: "",
    file_uri: "",
    notes: "",
  });

  const title = useMemo(() => {
    const p = payroll || {};
    const n = [p.first_name, p.last_name].filter(Boolean).join(" ");
    return n || `User #${uid}`;
  }, [payroll, uid]);

  const buildHrPayload = () => ({
    preferred_name: preferredName || null,
    date_of_birth: dob || null,
    alternate_phone: altPhone || null,
    notes: notes || null,
    work_json: { ...work, i9 },
    emergency_contacts_json: emergency.filter(
      (r) => r.name || r.phone || r.relationship || r.alt_phone,
    ),
  });

  const load = useCallback(async () => {
    if (!uid) return;
    setLoading(true);
    setError("");
    setInventoryLoadError("");
    try {
      const [hrRes, orgRes, invRes] = await Promise.all([
        getTaUserHrProfile(uid),
        getTaHrEmployerSettings().catch(() => ({ data: {} })),
        getTaUserHrFormsInventory(uid).catch((e) => {
          const d = e?.response?.data;
          const msg =
            d && typeof d === "object" && d.error != null
              ? String(d.error)
              : typeof d === "string"
                ? d
                : e?.message || "";
          setInventoryLoadError(msg.trim());
          return { data: { lanes_detected: [], forms: [] } };
        }),
      ]);
      const data = hrRes.data || {};
      if (data.error) {
        setError(data.error);
        setPayroll(null);
        return;
      }
      setPayroll(data.payroll || {});
      const h = data.hr || {};
      setPreferredName(h.preferred_name || "");
      const rawDob = h.date_of_birth;
      if (rawDob) setDob(String(rawDob).slice(0, 10));
      else setDob("");
      setAltPhone(h.alternate_phone || "");
      setNotes(h.notes || "");
      const rawW = h.work_json && typeof h.work_json === "object" ? h.work_json : {};
      const { i9: loadedI9, ...workRest } = rawW;
      setWork({ ...emptyWork(), ...workRest });
      setI9({ ...emptyI9(), ...(loadedI9 && typeof loadedI9 === "object" ? loadedI9 : {}) });
      const em = Array.isArray(h.emergency_contacts_json) ? h.emergency_contacts_json : emptyEmergency();
      const pad = [...em];
      while (pad.length < 2) pad.push({ name: "", relationship: "", phone: "", alt_phone: "" });
      setEmergency(pad.slice(0, 2));
      const o = orgRes.data || {};
      setEmployerName(o.employer_name || "");
      setEmployerAddress(o.employer_address || "");
      setEmployerEin(o.employer_ein || "");
      const inv = invRes.data || {};
      setInventory({
        lanes_detected: Array.isArray(inv.lanes_detected) ? inv.lanes_detected : [],
        forms: Array.isArray(inv.forms) ? inv.forms : [],
      });
      setDocLoading(true);
      try {
        const dr = await getTaUserDocuments(uid);
        setDocRows(Array.isArray(dr?.data?.items) ? dr.data.items : []);
      } catch {
        setDocRows([]);
      } finally {
        setDocLoading(false);
      }
    } catch (e) {
      const msg = e?.response?.data?.error || e?.message || "Failed to load";
      setError(typeof msg === "string" ? msg : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [uid]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!payroll?.user_id) return;
    setI9((prev) => {
      if (prev.legal_first_name || prev.legal_last_name) return prev;
      const fn = (payroll.first_name || "").trim();
      const ln = (payroll.last_name || "").trim();
      const disp = (payroll.washpro_display_name || "").trim();
      if (fn && ln && fn !== ln) return { ...prev, legal_first_name: fn, legal_last_name: ln };
      if (disp) {
        const parts = disp.split(/\s+/).filter(Boolean);
        const g = parts[0] || "";
        const fam = parts.length > 1 ? parts.slice(1).join(" ") : g;
        return { ...prev, legal_first_name: g, legal_last_name: fam };
      }
      if (fn || ln) return { ...prev, legal_first_name: fn || ln, legal_last_name: ln || fn };
      return prev;
    });
  }, [payroll?.user_id, payroll?.first_name, payroll?.last_name, payroll?.washpro_display_name]);

  useEffect(() => {
    const lanes = inventory.lanes_detected || [];
    if (lanes.length === 1) setTabLane(lanes[0]);
  }, [inventory.lanes_detected]);

  const tabForms = useMemo(
    () => (inventory.forms || []).filter((f) => f.lane === tabLane),
    [inventory.forms, tabLane],
  );

  const saveProfile = async () => {
    if (!canEdit) return;
    setSaving(true);
    setError("");
    try {
      await putTaUserHrProfile(uid, buildHrPayload());
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const saveEmployer = async () => {
    if (!canEdit) return;
    setSaving(true);
    setError("");
    try {
      await putTaHrEmployerSettings({
        employer_name: employerName,
        employer_address: employerAddress,
        employer_ein: employerEin,
      });
    } catch (e) {
      setError(e?.response?.data?.error || "Employer settings failed");
    } finally {
      setSaving(false);
    }
  };

  const downloadForm = async (form, locale) => {
    if (!canEdit) return;
    const formId = form.id;
    const key = `${formId}-${locale}`;
    setDlBusy(key);
    setError("");
    try {
      try {
        await putTaUserHrProfile(uid, buildHrPayload());
      } catch (saveErr) {
        const msg =
          saveErr?.response?.data?.error ||
          saveErr?.message ||
          t("hub.saveBeforeDownloadFailed");
        setError(typeof msg === "string" ? msg : t("hub.saveBeforeDownloadFailed"));
        return;
      }
      const res = await postTaUserHrForm(uid, formId, { locale });
      const ct = (res.headers?.["content-type"] || "").toLowerCase();
      const ext =
        form.kind === "internal_docx" || ct.includes("wordprocessingml") || ct.includes("msword")
          ? ".docx"
          : ".pdf";
      const name = `${formId}_${locale}${ext}`;
      const out = await saveBlobResponse(res, name);
      if (!out.ok) setError(out.error || "Download failed");
    } catch (e) {
      let msg = "Download failed";
      if (e?.response?.data instanceof Blob) {
        try {
          const text = await e.response.data.text();
          const j = JSON.parse(text);
          msg = typeof j.error === "string" ? j.error : msg;
        } catch {
          msg = e?.response?.statusText || msg;
        }
      } else {
        msg = e?.response?.data?.error || e?.message || msg;
      }
      setError(typeof msg === "string" ? msg : "Download failed");
    } finally {
      setDlBusy("");
    }
  };

  const addDocument = async () => {
    if (!canEdit) return;
    try {
      await postTaUserDocument(uid, docDraft);
      setDocDraft({
        document_code: "I9",
        document_name: "Form I-9",
        status: "received",
        issued_on: "",
        expires_on: "",
        file_uri: "",
        notes: "",
      });
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Document add failed");
    }
  };

  const patchDocument = async (id, patch) => {
    if (!canEdit) return;
    try {
      await putTaUserDocument(uid, id, patch);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Document update failed");
    }
  };

  const removeDocument = async (id) => {
    if (!canEdit) return;
    try {
      await deleteTaUserDocument(uid, id);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Document delete failed");
    }
  };

  const isAdmin = (sessionUser?.roles || []).map((r) => String(r).toUpperCase()).includes("ADMIN");
  if (!isAdmin) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="warning">{t("people.onlyAdmin")}</Alert>
      </Box>
    );
  }

  const showW2 = (inventory.lanes_detected || []).includes("employee_w2");
  const show1099 = (inventory.lanes_detected || []).includes("contractor_1099");

  return (
    <Box sx={{ p: { xs: 1, md: 2 }, maxWidth: 960, mx: "auto", pb: 10 }}>
      <Stack direction="row" alignItems="flex-start" spacing={1} sx={{ mb: 2 }}>
        <Button startIcon={<ArrowBack />} size="small" onClick={() => navigate("/employees")}>
          {t("common.back")}
        </Button>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5" sx={{ fontWeight: 700, letterSpacing: "-0.02em" }}>
            {t("hub.title")}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {title} — {t("hub.subtitle")}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }}>
            {(inventory.lanes_detected || []).map((ln) => (
              <Chip key={ln} size="small" label={ln === "employee_w2" ? t("hub.tabW2") : t("hub.tab1099")} color="primary" variant="outlined" />
            ))}
          </Stack>
        </Box>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {inventoryLoadError ? (
        <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setInventoryLoadError("")}>
          {t("hub.inventoryLoadFailed")}: {inventoryLoadError}
        </Alert>
      ) : null}
      {!loading && !showW2 && !show1099 ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t("hub.noPacket")}
        </Alert>
      ) : null}

      {loading ? (
        <Typography color="text.secondary">{t("common.loading")}</Typography>
      ) : (
        <Stack spacing={2.5}>
          <Paper
            elevation={0}
            sx={{
              p: 2.5,
              borderRadius: 3,
              border: "1px solid",
              borderColor: "divider",
              background: (theme) =>
                `linear-gradient(145deg, ${theme.palette.primary.main}10 0%, ${theme.palette.background.paper} 40%)`,
            }}
          >
            <Typography variant="overline" color="primary" sx={{ fontWeight: 700 }}>
              {t("hub.coreTitle")}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {t("hub.coreHint")}
            </Typography>
            <Stack spacing={2}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {t("hr.employerBlock")}
              </Typography>
              <Stack spacing={1.5}>
                <TextField
                  label={t("hr.employerName")}
                  value={employerName}
                  onChange={(e) => setEmployerName(e.target.value)}
                  fullWidth
                  size="small"
                  disabled={!canEdit}
                />
                <TextField
                  label={t("hr.employerAddress")}
                  value={employerAddress}
                  onChange={(e) => setEmployerAddress(e.target.value)}
                  fullWidth
                  size="small"
                  multiline
                  minRows={2}
                  disabled={!canEdit}
                />
                <TextField
                  label={t("hr.employerEin")}
                  value={employerEin}
                  onChange={(e) => setEmployerEin(e.target.value)}
                  fullWidth
                  size="small"
                  disabled={!canEdit}
                />
                <Button variant="outlined" disabled={!canEdit || saving} onClick={saveEmployer} sx={{ alignSelf: "flex-start" }}>
                  {t("hr.saveEmployer")}
                </Button>
              </Stack>
              <Divider />
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {t("hr.workerBlock")}
              </Typography>
              <Stack spacing={1.5}>
                <TextField label={t("hr.preferredName")} value={preferredName} onChange={(e) => setPreferredName(e.target.value)} fullWidth size="small" disabled={!canEdit} />
                <TextField
                  label={t("hr.dateOfBirth")}
                  type="date"
                  value={dob}
                  onChange={(e) => setDob(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                  size="small"
                  disabled={!canEdit}
                />
                <TextField label={t("hr.altPhone")} value={altPhone} onChange={(e) => setAltPhone(e.target.value)} fullWidth size="small" disabled={!canEdit} />
                <Typography variant="caption" color="text.secondary">
                  {t("hr.mailingHint")}
                </Typography>
                <TextField
                  label={t("hr.addressLine1")}
                  value={work.address_line1 || work.mailing_address_line1}
                  onChange={(e) => setWork((w) => ({ ...w, address_line1: e.target.value, mailing_address_line1: e.target.value }))}
                  fullWidth
                  size="small"
                  disabled={!canEdit}
                />
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                  <TextField label={t("hr.city")} value={work.city} onChange={(e) => setWork((w) => ({ ...w, city: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                  <TextField label={t("hr.state")} value={work.state} onChange={(e) => setWork((w) => ({ ...w, state: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                  <TextField label={t("hr.zip")} value={work.zip} onChange={(e) => setWork((w) => ({ ...w, zip: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                </Stack>
                <TextField
                  label={t("hr.middleInitial")}
                  value={work.middle_initial}
                  onChange={(e) => setWork((w) => ({ ...w, middle_initial: e.target.value.slice(0, 1) }))}
                  fullWidth
                  size="small"
                  disabled={!canEdit}
                  inputProps={{ maxLength: 1 }}
                />
                <TextField label={t("hr.jobTitle")} value={work.job_title} onChange={(e) => setWork((w) => ({ ...w, job_title: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                <TextField label={t("hr.department")} value={work.department} onChange={(e) => setWork((w) => ({ ...w, department: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                <TextField label={t("hr.supervisor")} value={work.supervisor_name} onChange={(e) => setWork((w) => ({ ...w, supervisor_name: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                <TextField label={t("hr.primaryLocation")} value={work.primary_work_location} onChange={(e) => setWork((w) => ({ ...w, primary_work_location: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                <TextField label={t("hr.language")} value={work.language_preference} onChange={(e) => setWork((w) => ({ ...w, language_preference: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
              </Stack>
              <Divider />
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {t("hr.emergency")}
              </Typography>
              {emergency.map((row, i) => (
                <Stack key={i} spacing={1} sx={{ mb: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    {i === 0 ? t("hr.contact1") : t("hr.contact2")}
                  </Typography>
                  <TextField label={t("hr.ecName")} value={row.name} onChange={(e) => setEmergency((rows) => rows.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))} fullWidth size="small" disabled={!canEdit} />
                  <TextField label={t("hr.ecRelation")} value={row.relationship} onChange={(e) => setEmergency((rows) => rows.map((r, j) => (j === i ? { ...r, relationship: e.target.value } : r)))} fullWidth size="small" disabled={!canEdit} />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                    <TextField label={t("hr.ecPhone")} value={row.phone} onChange={(e) => setEmergency((rows) => rows.map((r, j) => (j === i ? { ...r, phone: e.target.value } : r)))} fullWidth size="small" disabled={!canEdit} />
                    <TextField label={t("hr.ecAltPhone")} value={row.alt_phone} onChange={(e) => setEmergency((rows) => rows.map((r, j) => (j === i ? { ...r, alt_phone: e.target.value } : r)))} fullWidth size="small" disabled={!canEdit} />
                  </Stack>
                </Stack>
              ))}
              <Divider />
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {t("hr.notes")}
              </Typography>
              <TextField value={notes} onChange={(e) => setNotes(e.target.value)} fullWidth multiline minRows={2} size="small" disabled={!canEdit} />
            </Stack>
          </Paper>

          {showW2 || show1099 ? (
            <Paper variant="outlined" sx={{ borderRadius: 3, overflow: "hidden" }}>
              <Tabs
                value={tabLane}
                onChange={(_, v) => setTabLane(v)}
                variant="fullWidth"
                sx={{ borderBottom: 1, borderColor: "divider", px: 1 }}
              >
                {showW2 ? <Tab value="employee_w2" label={t("hub.tabW2")} /> : null}
                {show1099 ? <Tab value="contractor_1099" label={t("hub.tab1099")} /> : null}
              </Tabs>
              <Box sx={{ p: 2 }}>
                {tabForms.length === 0 ? (
                  <Typography color="text.secondary">{t("hub.noFormsInTab")}</Typography>
                ) : (
                  tabForms.map((form) => (
                    <Accordion key={form.id} defaultExpanded={form.id === "uscis_i9"} disableGutters sx={{ "&:before": { display: "none" }, mb: 1, borderRadius: "12px !important", border: "1px solid", borderColor: "divider" }}>
                      <AccordionSummary expandIcon={<ExpandMore />}>
                        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap sx={{ pr: 1 }}>
                          <Typography sx={{ fontWeight: 600 }}>{form.title}</Typography>
                          <Chip size="small" label={form.kind === "internal_docx" ? t("hub.internal") : t("hub.official")} variant="outlined" />
                          {form.fill_strategy === "print_only" ? <Chip size="small" label={t("hub.printOnly")} /> : null}
                        </Stack>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Stack spacing={2}>
                          {form.id === "uscis_i9" ? (
                            <>
                              <Typography variant="body2" color="text.secondary">
                                {t("hr.i9BlockHelp")}
                              </Typography>
                              <I9DetailsForm i9={i9} setI9={setI9} canEdit={canEdit} emptyPreparer={emptyPreparer} />
                            </>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              {form.kind === "internal_docx" ? t("hub.internalBlurb") : t("hub.officialBlurb")}
                            </Typography>
                          )}
                          <Stack direction="row" flexWrap="wrap" gap={1}>
                            {(form.locales || []).map((L) =>
                              L.available ? (
                                <Button
                                  key={L.locale}
                                  variant={L.prefill_supported ? "contained" : "outlined"}
                                  size="small"
                                  disabled={!canEdit || !!dlBusy}
                                  onClick={() => downloadForm(form, L.locale)}
                                >
                                  {L.prefill_supported
                                    ? `${t("hub.downloadPrefill")} (${localeLabel(L.locale, t)})`
                                    : `${t("hub.downloadFile")} (${localeLabel(L.locale, t)})`}
                                </Button>
                              ) : null,
                            )}
                          </Stack>
                        </Stack>
                      </AccordionDetails>
                    </Accordion>
                  ))
                )}
              </Box>
            </Paper>
          ) : null}

          <Paper sx={{ p: 2, borderRadius: 3 }}>
            <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
              {t("hr.docsTitle")}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {t("hr.docsBlurb")}
            </Typography>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 1 }}>
              <TextField
                label={t("hr.docsCode")}
                value={docDraft.document_code}
                onChange={(e) => setDocDraft((d) => ({ ...d, document_code: e.target.value.toUpperCase() }))}
                size="small"
                fullWidth
                disabled={!canEdit}
              />
              <TextField
                label={t("hr.docsName")}
                value={docDraft.document_name}
                onChange={(e) => setDocDraft((d) => ({ ...d, document_name: e.target.value }))}
                size="small"
                fullWidth
                disabled={!canEdit}
              />
              <Button variant="outlined" onClick={addDocument} disabled={!canEdit}>
                {t("common.add")}
              </Button>
            </Stack>
            {docLoading ? (
              <Typography color="text.secondary">{t("common.loading")}</Typography>
            ) : (
              <Stack spacing={1}>
                {docRows.map((r) => (
                  <Paper key={r.id} variant="outlined" sx={{ p: 1, borderRadius: 2 }}>
                    <Stack direction={{ xs: "column", md: "row" }} spacing={1}>
                      <TextField
                        label={t("hr.docsStatus")}
                        value={r.status || ""}
                        onChange={(e) => patchDocument(r.id, { status: e.target.value })}
                        size="small"
                        fullWidth
                        disabled={!canEdit}
                      />
                      <TextField
                        label={t("hr.docsIssued")}
                        type="date"
                        value={(r.issued_on || "").slice(0, 10)}
                        onChange={(e) => patchDocument(r.id, { issued_on: e.target.value })}
                        size="small"
                        InputLabelProps={{ shrink: true }}
                        fullWidth
                        disabled={!canEdit}
                      />
                      <TextField
                        label={t("hr.docsExpires")}
                        type="date"
                        value={(r.expires_on || "").slice(0, 10)}
                        onChange={(e) => patchDocument(r.id, { expires_on: e.target.value })}
                        size="small"
                        InputLabelProps={{ shrink: true }}
                        fullWidth
                        disabled={!canEdit}
                      />
                      <TextField
                        label={t("hr.docsFile")}
                        value={r.file_uri || ""}
                        onChange={(e) => patchDocument(r.id, { file_uri: e.target.value })}
                        size="small"
                        fullWidth
                        disabled={!canEdit}
                      />
                      <Button color="error" onClick={() => removeDocument(r.id)} disabled={!canEdit}>
                        {t("common.delete")}
                      </Button>
                    </Stack>
                  </Paper>
                ))}
                {!docRows.length ? <Typography color="text.secondary">{t("hr.docsEmpty")}</Typography> : null}
              </Stack>
            )}
          </Paper>

          <Paper sx={{ p: 2, position: "sticky", bottom: 16, borderRadius: 3, boxShadow: 3 }}>
            <Button variant="contained" size="large" fullWidth disabled={!canEdit || saving} onClick={saveProfile}>
              {saving ? t("common.saving") : t("hub.saveSharedProfile")}
            </Button>
          </Paper>
        </Stack>
      )}
    </Box>
  );
}
