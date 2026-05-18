import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { ArrowBack, ExpandMore } from "@mui/icons-material";
import {
  deleteTaUserDocument,
  getTaUserDocuments,
  getTaUserHrFormsInventory,
  getTaUserHrProfile,
  getTaUserHrForm,
  postTaUserDocument,
  putTaUserDocument,
  putTaUserHrProfile,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { getFormChecklistLines } from "../constants/hrFormChecklists";
import I9DetailsForm, {
  emptyI9,
  emptyPreparer,
  emptyWork,
  emptyEmergency,
  sanitizeI9Preparers,
} from "../components/hr/I9DetailsForm";
import { hrModule } from "../components/hr/hrModuleStyles";
import { mergePayrollMailingIntoWork, parseHrWorkJson } from "../utils/mailingMerge";

function isInternalReferenceForm(form) {
  if (!form) return false;
  const k = String(form.kind || "");
  const fs = String(form.fill_strategy || "");
  return (
    k === "internal_reference_pdf" ||
    k === "internal_docx" ||
    fs === "reference_pdf" ||
    fs === "docx_template"
  );
}

function localeLabel(code, t) {
  if (code === "en") return t("hub.localeEn");
  if (code === "es") return t("hub.localeEs");
  if (code === "bilingual") return t("hub.localeBilingual");
  return code;
}

function laneTabLabel(lane, t) {
  if (lane === "employee_w2") return t("hub.tabW2");
  if (lane === "contractor_1099") return t("hub.tab1099");
  if (lane === "temp_worker") return t("hub.tabTemp");
  return lane;
}

function formPrefillMissing(formId, payroll, work, i9, t) {
  const miss = [];
  const fn = String((payroll && payroll.first_name) || "").trim();
  const ln = String((payroll && payroll.last_name) || "").trim();
  const addr1 = String((work && (work.address_line1 || work.mailing_address_line1)) || "").trim();
  const city = String((work && work.city) || "").trim();
  const st = String((work && work.state) || "").trim();
  const zip = String((work && (work.zip || work.zip_code)) || "").trim();
  const hasTin = String((payroll && payroll.itin_ssn_last4) || "").trim() || String((i9 && i9.ssn) || "").trim();
  if (!fn) miss.push(t("profile.firstName"));
  if (!ln) miss.push(t("profile.lastName"));
  if (formId === "uscis_i9") {
    const legalFirst = String((i9 && i9.legal_first_name) || "").trim() || fn;
    const legalLast = String((i9 && i9.legal_last_name) || "").trim() || ln;
    if (!legalFirst) miss.push(t("hr.i9LegalFirst"));
    if (!legalLast) miss.push(t("hr.i9LegalLast"));
    if (!String((i9 && i9.citizenship) || "").trim()) miss.push(t("hr.i9Citizenship"));
    if (!addr1) miss.push(t("hr.addressLine1"));
    if (!city) miss.push(t("hr.city"));
    if (!st) miss.push(t("hr.state"));
    if (!zip) miss.push(t("hr.zip"));
    return miss;
  }
  if (formId === "irs_w4" || formId === "irs_w9" || formId === "ny_it2104") {
    if (!addr1) miss.push(t("hr.addressLine1"));
    if (!city) miss.push(t("hr.city"));
    if (!st) miss.push(t("hr.state"));
    if (!zip) miss.push(t("hr.zip"));
    if (!hasTin) miss.push(t("hub.prefillTin"));
  }
  return miss;
}

function documentMetadataObject(row) {
  const m = row?.metadata_json;
  if (m && typeof m === "object" && !Array.isArray(m)) return { ...m };
  if (typeof m === "string") {
    try {
      const o = JSON.parse(m);
      if (o && typeof o === "object" && !Array.isArray(o)) return { ...o };
    } catch {
      /* ignore */
    }
  }
  return {};
}

function hrDownloadFailureHint(e) {
  if (e?.response) return "";
  const msg = String(e?.message || "");
  if (msg === "Network Error" || e?.code === "ERR_NETWORK") {
    return " Check your connection and try again (hard-refresh if this persists after a deploy).";
  }
  if (e?.code === "ECONNABORTED" || /timeout/i.test(msg)) {
    return " The request timed out — the API may be cold-starting; try again.";
  }
  return "";
}

async function saveBlobResponse(res, fallbackName) {
  if (res.status != null && (res.status < 200 || res.status >= 300)) {
    const blob = res.data;
    if (blob instanceof Blob) {
      try {
        const text = await blob.text();
        const j = JSON.parse(text);
        if (typeof j.error === "string" && j.error.trim()) {
          return { ok: false, error: j.error.trim() };
        }
      } catch {
        /* fall through */
      }
    }
    return { ok: false, error: `Download failed (HTTP ${res.status})` };
  }
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

/** variant: `page` (full HR route) or `embedded` (User profile section 5). */
export function PayrollFormsHubCore({
  userId: uidProp,
  user: sessionUser,
  variant = "page",
  /** Embedded in employee workspace: I-9 data is edited on Compliance Data tab — omit i9 from hub saves to avoid wiping it. */
  suppressI9Capture = false,
  /** Increment after profile workspace Save so embedded hub reloads HR JSON. */
  profileSaveTick = 0,
}) {
  const params = useParams();
  const uid = Number(uidProp ?? params.userId);
  const navigate = useNavigate();
  const { t } = useI18n();
  const { hasPerm } = useAuth();
  const canEdit = hasPerm("users.edit");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [inventoryLoadError, setInventoryLoadError] = useState("");
  const [inventory, setInventory] = useState({ lanes_detected: [], forms: [], tax_year_filter: null });
  const [tabLane, setTabLane] = useState("employee_w2");
  const [payroll, setPayroll] = useState(null);
  const [preferredName, setPreferredName] = useState("");
  const [dob, setDob] = useState("");
  const [altPhone, setAltPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [work, setWork] = useState(() => emptyWork());
  const [emergency, setEmergency] = useState(() => emptyEmergency());
  const [i9, setI9] = useState(() => emptyI9());
  const [docRows, setDocRows] = useState([]);
  const [docLoading, setDocLoading] = useState(false);
  const [dlBusy, setDlBusy] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [formBulkPick, setFormBulkPick] = useState({});
  const [docPrintPick, setDocPrintPick] = useState({});
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

  const workEffective = useMemo(() => mergePayrollMailingIntoWork(work, payroll), [work, payroll]);

  /** Lines merged into W-4 / W-9 (server reads full SSN from DB when present). */
  const pdfPrefillSummary = useMemo(() => {
    const p = payroll || {};
    const w = workEffective || {};
    const rows = [];
    const nm = [p.first_name, p.last_name].filter(Boolean).join(" ").trim();
    if (nm) rows.push({ k: "name", label: t("hub.prefillLegalName"), value: nm });
    const pem = String(p.email || "").trim();
    if (pem) rows.push({ k: "email", label: t("people.colEmail"), value: pem });
    const pmob = String(p.mobile || "").trim();
    if (pmob) rows.push({ k: "mobile", label: t("hub.prefillMobile"), value: pmob });
    const mi = (w.middle_initial || "").trim();
    if (mi) rows.push({ k: "mi", label: t("hr.middleInitial"), value: mi });
    const a1 = (w.address_line1 || w.mailing_address_line1 || "").trim();
    const addrFallback = !a1 ? String(p.address || "").trim() : "";
    if (a1) rows.push({ k: "a1", label: t("hr.addressLine1"), value: a1 });
    else if (addrFallback) rows.push({ k: "a1", label: t("hub.prefillPayrollAddress"), value: addrFallback });
    const z = String(w.zip || w.zip_code || "").trim();
    const tail = [w.city, [w.state, z].filter(Boolean).join(" ")].filter(Boolean).join(", ").trim();
    if (tail) rows.push({ k: "csz", label: t("hub.prefillCityStateZip"), value: tail });
    const last4 = (p.itin_ssn_last4 || "").trim();
    if (last4)
      rows.push({
        k: "tin",
        label: t("hub.prefillTin"),
        value: `***-**-${last4}`,
        hint: t("hub.prefillTinServerHint"),
      });
    else
      rows.push({
        k: "tin",
        label: t("hub.prefillTin"),
        value: t("hub.prefillTinEmpty"),
        hint: t("hub.prefillTinEmptyHint"),
      });
    if (tabLane !== "contractor_1099") {
      return rows.filter((r) => r.k !== "tin");
    }
    return rows;
  }, [payroll, workEffective, t, tabLane]);

  const buildHrPayload = () => {
    const wj = { ...work };
    // Profile-only tax elections: do not POST from the hub (hub does not edit them).
    // Sending them back can overwrite stored W-4/NY data when local state is stale or empty.
    delete wj.w4;
    delete wj.ny_it2104;
    if (!suppressI9Capture) wj.i9 = i9;
    return {
      preferred_name: preferredName || null,
      date_of_birth: dob || null,
      alternate_phone: altPhone || null,
      notes: notes || null,
      work_json: wj,
      emergency_contacts_json: emergency.filter(
        (r) => r.name || r.phone || r.relationship || r.alt_phone,
      ),
    };
  };

  const load = useCallback(async () => {
    if (!uid) return;
    setLoading(true);
    setError("");
    setInventoryLoadError("");
    setDocLoading(true);
    try {
      const [hrRes, invRes, docRes] = await Promise.all([
        getTaUserHrProfile(uid),
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
        getTaUserDocuments(uid).catch(() => ({ data: { items: [] } })),
      ]);
      const data = hrRes.data || {};
      if (data.error) {
        setError(data.error);
        setPayroll(null);
        setDocRows([]);
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
      const rawW = parseHrWorkJson(h.work_json);
      const { i9: loadedI9, ...workRest } = rawW;
      let workMerged = { ...emptyWork(), ...workRest };
      const pay = data.payroll || {};
      const payAddr = String(pay.address || "").trim();
      if (
        !(String(workMerged.address_line1 || workMerged.mailing_address_line1 || "").trim()) &&
        payAddr
      ) {
        const firstLine = payAddr.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)[0] || payAddr;
        workMerged = { ...workMerged, address_line1: firstLine, mailing_address_line1: firstLine };
      }
      setWork(workMerged);
      const baseI9 = {
        ...emptyI9(),
        ...(loadedI9 && typeof loadedI9 === "object" ? loadedI9 : {}),
        preparers: sanitizeI9Preparers(
          (loadedI9 && typeof loadedI9 === "object" ? loadedI9.preparers : null) || [],
        ),
      };
      const payEmail = String(pay.email || "").trim();
      setI9({ ...baseI9, employee_email: baseI9.employee_email || payEmail });
      const em = Array.isArray(h.emergency_contacts_json) ? h.emergency_contacts_json : emptyEmergency();
      const pad = [...em];
      while (pad.length < 2) pad.push({ name: "", relationship: "", phone: "", alt_phone: "" });
      setEmergency(pad.slice(0, 2));
      const inv = invRes.data || {};
      setInventory({
        lanes_detected: Array.isArray(inv.lanes_detected) ? inv.lanes_detected : [],
        forms: Array.isArray(inv.forms) ? inv.forms : [],
        tax_year_filter: inv.tax_year_filter || null,
      });
      const picks = {};
      for (const f of Array.isArray(inv.forms) ? inv.forms : []) {
        picks[f.id] = true;
      }
      setFormBulkPick(picks);
      setDocRows(Array.isArray(docRes?.data?.items) ? docRes.data.items : []);
    } catch (e) {
      const msg = e?.response?.data?.error || e?.message || "Failed to load";
      setError(typeof msg === "string" ? msg : "Failed to load");
    } finally {
      setLoading(false);
      setDocLoading(false);
    }
  }, [uid]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (profileSaveTick > 0) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when profile workspace saved
  }, [profileSaveTick]);

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

  const formMissingMap = useMemo(() => {
    const out = {};
    for (const f of inventory.forms || []) out[f.id] = formPrefillMissing(f.id, payroll, workEffective, i9, t);
    return out;
  }, [inventory.forms, payroll, workEffective, i9, t]);

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

  const downloadForm = async (form, locale) => {
    if (!canEdit) return;
    const formId = form.id;
    const key = `${formId}-${locale}`;
    setDlBusy(key);
    setError("");
    try {
      const res = await getTaUserHrForm(uid, formId, locale);
      const ct = (res.headers?.["content-type"] || "").toLowerCase();
      const ext =
        isInternalReferenceForm(form) || ct.includes("pdf")
          ? ".pdf"
          : ct.includes("wordprocessingml") || ct.includes("msword")
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
      const hint = hrDownloadFailureHint(e);
      setError(typeof msg === "string" ? `${msg}${hint}` : "Download failed");
    } finally {
      setDlBusy("");
    }
  };

  const downloadAllPrefillsForTab = async () => {
    if (!canEdit) return;
    const targets = [];
    for (const form of tabForms) {
      if (!formBulkPick[form.id]) continue;
      const missing = formMissingMap[form.id] || [];
      if (missing.length) continue;
      for (const L of form.locales || []) {
        if (L.available && L.prefill_supported) targets.push({ form, locale: L.locale });
      }
    }
    if (!targets.length) {
      setError(t("hub.bulkPrefillNone"));
      return;
    }
    setBulkBusy(true);
    setError("");
    try {
      for (const { form, locale } of targets) {
        const key = `${form.id}-${locale}`;
        setDlBusy(key);
        try {
          const res = await getTaUserHrForm(uid, form.id, locale);
          const ct = (res.headers?.["content-type"] || "").toLowerCase();
          const ext =
            isInternalReferenceForm(form) || ct.includes("pdf")
              ? ".pdf"
              : ct.includes("wordprocessingml") || ct.includes("msword")
                ? ".docx"
                : ".pdf";
          const name = `${form.id}_${locale}${ext}`;
          const out = await saveBlobResponse(res, name);
          if (!out.ok) {
            setError(out.error || "Download failed");
            return;
          }
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
          const hint = hrDownloadFailureHint(e);
          setError(typeof msg === "string" ? `${msg}${hint}` : "Download failed");
          return;
        }
        await new Promise((r) => setTimeout(r, 400));
      }
    } finally {
      setDlBusy("");
      setBulkBusy(false);
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

  const openUrlsForPrint = () => {
    const urls = [];
    for (const r of docRows) {
      if (!docPrintPick[r.id]) continue;
      const meta = documentMetadataObject(r);
      if (r.file_uri) urls.push(r.file_uri);
      if (meta.evidence_uri) urls.push(meta.evidence_uri);
    }
    if (!urls.length) {
      setError(t("hub.printPickNone"));
      return;
    }
    for (const u of urls) {
      try {
        window.open(u, "_blank", "noopener,noreferrer");
      } catch {
        /* ignore */
      }
    }
  };

  const togglePickAllDocs = (on) => {
    const next = {};
    for (const r of docRows) next[r.id] = on;
    setDocPrintPick(next);
  };

  const showW2 = (inventory.lanes_detected || []).includes("employee_w2");
  const show1099 = (inventory.lanes_detected || []).includes("contractor_1099");
  const showTemp = (inventory.lanes_detected || []).includes("temp_worker");

  const embedded = variant === "embedded";
  const taxY = inventory.tax_year_filter;

  return (
    <Box
      sx={{
        ...(embedded
          ? {}
          : {
              ...hrModule.pageCanvas,
            }),
        p: { xs: 1, md: embedded ? 0 : 0 },
        maxWidth: embedded ? "none" : 1180,
        mx: "auto",
        pb: embedded ? 2 : 6,
        pt: embedded ? 0 : { xs: 2, md: 3 },
        px: embedded ? { xs: 1, md: 0 } : { xs: 1.5, sm: 2, md: 3 },
      }}
    >
      {!embedded ? (
        <Paper elevation={0} sx={{ ...hrModule.hero, mb: 2.75 }}>
          <Stack direction="row" alignItems="flex-start" spacing={2}>
            <IconButton
              aria-label={t("common.back")}
              onClick={() => navigate("/employees")}
              size="small"
              sx={{
                color: "inherit",
                bgcolor: "rgba(255,255,255,0.18)",
                "&:hover": { bgcolor: "rgba(255,255,255,0.28)" },
              }}
            >
              <ArrowBack fontSize="small" />
            </IconButton>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={hrModule.heroOverline}>{t("hub.pageKicker")}</Typography>
              <Typography variant="h4" component="h1" sx={hrModule.heroTitle}>
                {title}
              </Typography>
              <Typography variant="body2" sx={hrModule.heroSubtitle}>
                {t("hub.subtitle")}
              </Typography>
              <Stack direction="row" flexWrap="wrap" gap={0.75} sx={{ mt: 1.5 }} alignItems="center">
                {(inventory.lanes_detected || []).map((ln) => (
                  <Chip key={ln} size="small" label={laneTabLabel(ln, t)} sx={hrModule.statChip} />
                ))}
                {taxY ? (
                  <Chip
                    size="small"
                    label={t("hub.taxYearFilter").replace("{year}", taxY)}
                    sx={{ ...hrModule.statChip, opacity: 0.95 }}
                  />
                ) : null}
              </Stack>
            </Box>
          </Stack>
        </Paper>
      ) : (
        <Box sx={{ mb: 2 }}>
          <Typography variant="overline" sx={{ ...hrModule.heroOverline, color: "primary.main" }}>
            {t("hub.pageKicker")}
          </Typography>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, letterSpacing: "-0.02em" }}>
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t("hub.title")}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }} alignItems="center">
            {(inventory.lanes_detected || []).map((ln) => (
              <Chip key={ln} size="small" label={laneTabLabel(ln, t)} color="primary" variant="outlined" />
            ))}
            {taxY ? <Chip size="small" variant="outlined" label={t("hub.taxYearFilter").replace("{year}", taxY)} /> : null}
          </Stack>
        </Box>
      )}

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
      {!loading && !showW2 && !show1099 && !showTemp ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t("hub.noPacket")}
        </Alert>
      ) : null}

      {loading ? (
        <Box
          sx={{
            py: 10,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 2,
          }}
        >
          <CircularProgress size={40} thickness={4} />
          <Typography variant="body2" color="text.secondary">
            {t("common.loading")}
          </Typography>
        </Box>
      ) : (
        <Stack direction="column" spacing={2.5} alignItems="flex-start">
          {embedded ? (
            <Alert severity="info" sx={{ width: "100%", borderRadius: 2 }}>
              {t("hub.embeddedContextHint")}
            </Alert>
          ) : (
            <Alert
              severity="info"
              sx={{ width: "100%", borderRadius: 2 }}
              action={
                <Button color="inherit" size="small" onClick={() => navigate(`/employees/${uid}`)}>
                  {t("hub.openPeopleProfile")}
                </Button>
              }
            >
              {t("hub.pageSingleSourceHint")}
            </Alert>
          )}

          <Stack spacing={2.5} sx={{ flex: 1, minWidth: 0, width: "100%" }}>
            <Paper elevation={0} sx={(theme) => ({ ...hrModule.filterBar(theme), p: 2.25 })}>
              <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 0.5, letterSpacing: "-0.02em" }}>
                {t("hub.prefillPreviewTitle")}
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
                {t("hub.prefillPreviewBlurb")}
              </Typography>
              <Stack spacing={1}>
                {pdfPrefillSummary.map((row) => (
                  <Box key={row.k}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                      {row.label}
                    </Typography>
                    <Typography variant="body2" sx={{ fontWeight: row.k === "name" ? 600 : 500 }}>
                      {row.value}
                    </Typography>
                    {row.hint ? (
                      <Typography variant="caption" color="text.secondary">
                        {row.hint}
                      </Typography>
                    ) : null}
                  </Box>
                ))}
              </Stack>
            </Paper>

          {showW2 || show1099 || showTemp ? (
            <Paper
              elevation={0}
              sx={(theme) => ({
                ...hrModule.tableCard(theme),
                overflow: "hidden",
              })}
            >
              <Tabs
                value={tabLane}
                onChange={(_, v) => setTabLane(v)}
                variant="fullWidth"
                sx={(theme) => hrModule.tabs(theme)}
              >
                {showW2 ? <Tab value="employee_w2" label={t("hub.tabW2")} /> : null}
                {show1099 ? <Tab value="contractor_1099" label={t("hub.tab1099")} /> : null}
                {showTemp ? <Tab value="temp_worker" label={t("hub.tabTemp")} /> : null}
              </Tabs>
              <Box sx={{ px: 2, pt: 1.5, pb: 0 }}>
                <Stack direction="row" flexWrap="wrap" gap={1} alignItems="center">
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={!canEdit || bulkBusy || !!dlBusy || tabLane === "temp_worker"}
                    onClick={downloadAllPrefillsForTab}
                  >
                    {bulkBusy ? t("hub.bulkPrefillBusy") : t("hub.bulkPrefillSelected")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      const next = {};
                      for (const f of tabForms) next[f.id] = true;
                      setFormBulkPick((p) => ({ ...p, ...next }));
                    }}
                  >
                    {t("hub.selectAllFormsTab")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      const next = {};
                      for (const f of tabForms) next[f.id] = false;
                      setFormBulkPick((p) => ({ ...p, ...next }));
                    }}
                  >
                    {t("hub.clearFormPicks")}
                  </Button>
                </Stack>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                  {t("hub.bulkPrefillHint")}
                </Typography>
              </Box>
              <Box sx={{ p: 2 }}>
                {tabLane === "temp_worker" ? (
                  <Typography color="text.secondary">{t("hub.tempNoForms")}</Typography>
                ) : tabForms.length === 0 ? (
                  <Typography color="text.secondary">{t("hub.noFormsInTab")}</Typography>
                ) : (
                  tabForms.map((form) => (
                    <Accordion
                      key={form.id}
                      defaultExpanded={form.id === "uscis_i9"}
                      disableGutters
                      sx={{
                        "&:before": { display: "none" },
                        mb: 1,
                        borderRadius: "14px !important",
                        border: "1px solid",
                        borderColor: "divider",
                        overflow: "hidden",
                        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                      }}
                    >
                      <AccordionSummary
                        expandIcon={<ExpandMore />}
                        sx={{
                          bgcolor: (theme) => (theme.palette.mode === "dark" ? "rgba(255,255,255,0.04)" : "grey.50"),
                          minHeight: 52,
                          "&.Mui-expanded": { minHeight: 52 },
                        }}
                      >
                        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap sx={{ pr: 1 }}>
                          {form.fill_strategy === "acroform" ? (
                            <Checkbox
                              size="small"
                              checked={!!formBulkPick[form.id]}
                              onChange={(e) => {
                                e.stopPropagation();
                                setFormBulkPick((p) => ({ ...p, [form.id]: e.target.checked }));
                              }}
                              onClick={(e) => e.stopPropagation()}
                            />
                          ) : (
                            <Box sx={{ width: 28 }} />
                          )}
                          <Typography sx={{ fontWeight: 600 }}>{form.title}</Typography>
                          <Chip
                            size="small"
                            label={isInternalReferenceForm(form) ? t("hub.internalPdfRef") : t("hub.official")}
                            variant="outlined"
                          />
                          {form.fill_strategy === "print_only" ? <Chip size="small" label={t("hub.printOnly")} /> : null}
                          {form.tax_year ? <Chip size="small" label={`TY ${form.tax_year}`} variant="outlined" /> : null}
                        </Stack>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Stack spacing={2}>
                          {getFormChecklistLines(form.id, t, form.title).length ? (
                            <Box>
                              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                                {t("hub.checklistTitle")}
                              </Typography>
                              <Box component="ul" sx={{ pl: 2.2, m: 0, mt: 0.5 }}>
                                {getFormChecklistLines(form.id, t, form.title).map((line) => (
                                  <Typography key={line} component="li" variant="body2" color="text.secondary">
                                    {line}
                                  </Typography>
                                ))}
                              </Box>
                            </Box>
                          ) : null}
                          {form.id === "uscis_i9" ? (
                            suppressI9Capture ? (
                              <Alert severity="info">{t("hub.i9CaptureInComplianceTab")}</Alert>
                            ) : (
                              <>
                                <Typography variant="body2" color="text.secondary">
                                  {t("hr.i9BlockHelp")}
                                </Typography>
                                <I9DetailsForm
                                  i9={i9}
                                  setI9={setI9}
                                  canEdit={canEdit}
                                  emptyPreparer={emptyPreparer}
                                  omitIdentityFields={embedded}
                                />
                              </>
                            )
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              {isInternalReferenceForm(form) ? t("hub.internalBlurb") : t("hub.officialBlurb")}
                            </Typography>
                          )}
                          <Stack direction="row" flexWrap="wrap" gap={1}>
                            {(form.locales || []).map((L) =>
                              L.available ? (
                                <Button
                                  key={L.locale}
                                  variant={L.prefill_supported ? "contained" : "outlined"}
                                  size="small"
                                  disabled={
                                    !canEdit ||
                                    !!dlBusy ||
                                    (L.prefill_supported && (formMissingMap[form.id] || []).length > 0)
                                  }
                                  onClick={() => downloadForm(form, L.locale)}
                                >
                                  {L.prefill_supported
                                    ? `${t("hub.downloadPrefill")} (${localeLabel(L.locale, t)})`
                                    : `${t("hub.downloadFile")} (${localeLabel(L.locale, t)})`}
                                </Button>
                              ) : null,
                            )}
                          </Stack>
                          {(formMissingMap[form.id] || []).length ? (
                            <Typography variant="caption" color="warning.main">
                              {t("hub.prefillBlockedMissing")} {(formMissingMap[form.id] || []).join(", ")}
                            </Typography>
                          ) : null}
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
            <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 1 }} alignItems="center">
              <Button size="small" variant="outlined" onClick={() => togglePickAllDocs(true)} disabled={!docRows.length}>
                {t("hub.docSelectAll")}
              </Button>
              <Button size="small" onClick={() => togglePickAllDocs(false)} disabled={!docRows.length}>
                {t("hub.docSelectNone")}
              </Button>
              <Button size="small" color="secondary" variant="contained" onClick={openUrlsForPrint} disabled={!docRows.length}>
                {t("hub.openSelectedForPrint")}
              </Button>
              <Typography variant="caption" color="text.secondary">
                {t("hub.openSelectedForPrintHint")}
              </Typography>
            </Stack>
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
                  <Paper
                    key={r.id}
                    variant="outlined"
                    sx={(theme) => ({
                      p: 1,
                      borderRadius: 2,
                      borderWidth: r.file_uri || documentMetadataObject(r).evidence_uri ? 2 : 1,
                      borderColor:
                        r.file_uri || documentMetadataObject(r).evidence_uri ? theme.palette.success.main : undefined,
                      bgcolor:
                        r.file_uri || documentMetadataObject(r).evidence_uri
                          ? theme.palette.mode === "dark"
                            ? "rgba(46,125,50,0.12)"
                            : "rgba(46,125,50,0.08)"
                          : undefined,
                    })}
                  >
                    <Stack direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "flex-start" }}>
                      <Checkbox
                        size="small"
                        checked={!!docPrintPick[r.id]}
                        onChange={(e) => setDocPrintPick((p) => ({ ...p, [r.id]: e.target.checked }))}
                        sx={{ pt: 0.5 }}
                      />
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
                      <TextField
                        label={t("hub.evidenceUri")}
                        value={documentMetadataObject(r).evidence_uri || ""}
                        onChange={(e) =>
                          patchDocument(r.id, {
                            metadata_json: {
                              ...documentMetadataObject(r),
                              evidence_uri: e.target.value.trim() || null,
                            },
                          })
                        }
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

          {embedded ? (
            <Paper
              sx={(theme) => ({
                p: 2,
                position: "sticky",
                bottom: 16,
                borderRadius: 3,
                border: `1px solid ${theme.palette.divider}`,
                boxShadow: theme.palette.mode === "dark" ? "0 -4px 24px rgba(0,0,0,0.35)" : "0 -4px 24px rgba(15,23,42,0.08)",
                bgcolor: theme.palette.background.paper,
              })}
            >
              <Button variant="contained" size="large" fullWidth disabled={!canEdit || saving} onClick={saveProfile}>
                {saving ? t("common.saving") : t("hub.saveFormDataForDownloads")}
              </Button>
            </Paper>
          ) : null}
          </Stack>
        </Stack>
      )}
    </Box>
  );
}

export default function PayrollFormsHubPage({ user }) {
  const { userId } = useParams();
  return <PayrollFormsHubCore user={user} userId={Number(userId)} variant="page" suppressI9Capture />;
}
