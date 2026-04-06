import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { ArrowBack } from "@mui/icons-material";
import {
  getTaHrEmployerSettings,
  postTaUserHrFormI9,
  getTaUserHrProfile,
  putTaHrEmployerSettings,
  putTaUserHrProfile,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function emptyWork() {
  return {
    mailing_address_line1: "",
    address_line1: "",
    city: "",
    state: "",
    zip: "",
    middle_initial: "",
    job_title: "",
    department: "",
    supervisor_name: "",
    primary_work_location: "",
    language_preference: "",
  };
}

function emptyEmergency() {
  return [
    { name: "", relationship: "", phone: "", alt_phone: "" },
    { name: "", relationship: "", phone: "", alt_phone: "" },
  ];
}

export default function HrCompliancePage({ user: sessionUser }) {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { hasPerm } = useAuth();
  const uid = Number(userId);
  const canEdit = hasPerm("users.edit");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
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
  const [i9Loading, setI9Loading] = useState(false);

  const title = useMemo(() => {
    const p = payroll || {};
    const n = [p.first_name, p.last_name].filter(Boolean).join(" ");
    return n || `User #${uid}`;
  }, [payroll, uid]);

  const load = useCallback(async () => {
    if (!uid) return;
    setLoading(true);
    setError("");
    try {
      const [hrRes, orgRes] = await Promise.all([
        getTaUserHrProfile(uid),
        getTaHrEmployerSettings().catch(() => ({ data: {} })),
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
      if (rawDob) {
        const s = String(rawDob).slice(0, 10);
        setDob(s);
      } else setDob("");
      setAltPhone(h.alternate_phone || "");
      setNotes(h.notes || "");
      const w = h.work_json && typeof h.work_json === "object" ? h.work_json : {};
      setWork({ ...emptyWork(), ...w });
      const em = Array.isArray(h.emergency_contacts_json) ? h.emergency_contacts_json : emptyEmergency();
      const pad = [...em];
      while (pad.length < 2) pad.push({ name: "", relationship: "", phone: "", alt_phone: "" });
      setEmergency(pad.slice(0, 2));
      const o = orgRes.data || {};
      setEmployerName(o.employer_name || "");
      setEmployerAddress(o.employer_address || "");
      setEmployerEin(o.employer_ein || "");
    } catch (e) {
      const msg = e?.response?.data?.error || e?.message || "Failed to load HR profile";
      setError(typeof msg === "string" ? msg : "Failed to load HR profile");
    } finally {
      setLoading(false);
    }
  }, [uid]);

  useEffect(() => {
    load();
  }, [load]);

  const saveProfile = async () => {
    if (!canEdit) return;
    setSaving(true);
    setError("");
    try {
      await putTaUserHrProfile(uid, {
        preferred_name: preferredName || null,
        date_of_birth: dob || null,
        alternate_phone: altPhone || null,
        notes: notes || null,
        work_json: work,
        emergency_contacts_json: emergency.filter(
          (r) => r.name || r.phone || r.relationship || r.alt_phone,
        ),
      });
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

  const downloadI9 = async () => {
    if (!canEdit) return;
    setI9Loading(true);
    setError("");
    try {
      const res = await postTaUserHrFormI9(uid);
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `i9-prefill-${uid}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      let msg = "I-9 download failed";
      if (e?.response?.data instanceof Blob) {
        try {
          const text = await e.response.data.text();
          const j = JSON.parse(text);
          msg = j.error || msg;
        } catch {
          msg = e?.response?.statusText || msg;
        }
      } else msg = e?.response?.data?.error || e?.message || msg;
      setError(msg);
    } finally {
      setI9Loading(false);
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

  return (
    <Box sx={{ p: { xs: 1, md: 2 }, maxWidth: 900 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <Button startIcon={<ArrowBack />} size="small" onClick={() => navigate("/employees")}>
          {t("common.back")}
        </Button>
        <Typography variant="h5" sx={{ flex: 1 }}>
          {t("hr.title")}: {title}
        </Typography>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <Typography color="text.secondary">{t("common.loading")}</Typography>
      ) : (
        <Stack spacing={3}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
              {t("hr.employerBlock")}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {t("hr.employerHelp")}
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
              <Button variant="outlined" disabled={!canEdit || saving} onClick={saveEmployer}>
                {t("hr.saveEmployer")}
              </Button>
            </Stack>
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
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
              <Divider />
              <Typography variant="body2" color="text.secondary">
                {t("hr.mailingHint")}
              </Typography>
              <TextField label={t("hr.addressLine1")} value={work.address_line1 || work.mailing_address_line1} onChange={(e) => setWork((w) => ({ ...w, address_line1: e.target.value, mailing_address_line1: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                <TextField label={t("hr.city")} value={work.city} onChange={(e) => setWork((w) => ({ ...w, city: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                <TextField label={t("hr.state")} value={work.state} onChange={(e) => setWork((w) => ({ ...w, state: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
                <TextField label={t("hr.zip")} value={work.zip} onChange={(e) => setWork((w) => ({ ...w, zip: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
              </Stack>
              <TextField label={t("hr.middleInitial")} value={work.middle_initial} onChange={(e) => setWork((w) => ({ ...w, middle_initial: e.target.value.slice(0, 1) }))} fullWidth size="small" disabled={!canEdit} inputProps={{ maxLength: 1 }} />
              <TextField label={t("hr.jobTitle")} value={work.job_title} onChange={(e) => setWork((w) => ({ ...w, job_title: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
              <TextField label={t("hr.department")} value={work.department} onChange={(e) => setWork((w) => ({ ...w, department: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
              <TextField label={t("hr.supervisor")} value={work.supervisor_name} onChange={(e) => setWork((w) => ({ ...w, supervisor_name: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
              <TextField label={t("hr.primaryLocation")} value={work.primary_work_location} onChange={(e) => setWork((w) => ({ ...w, primary_work_location: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
              <TextField label={t("hr.language")} value={work.language_preference} onChange={(e) => setWork((w) => ({ ...w, language_preference: e.target.value }))} fullWidth size="small" disabled={!canEdit} />
            </Stack>
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
              {t("hr.emergency")}
            </Typography>
            {emergency.map((row, i) => (
              <Stack key={i} spacing={1} sx={{ mb: 2 }}>
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
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
              {t("hr.notes")}
            </Typography>
            <TextField value={notes} onChange={(e) => setNotes(e.target.value)} fullWidth multiline minRows={2} size="small" disabled={!canEdit} />
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
              {t("hr.forms")}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {t("hr.formsBlurb")}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" disabled={!canEdit || i9Loading} onClick={downloadI9}>
                {t("hr.downloadI9")}
              </Button>
            </Stack>
          </Paper>

          <Stack direction="row" spacing={1}>
            <Button variant="contained" disabled={!canEdit || saving} onClick={saveProfile}>
              {t("hr.saveProfile")}
            </Button>
          </Stack>
        </Stack>
      )}
    </Box>
  );
}
