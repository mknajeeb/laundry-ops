import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  CircularProgress,
  Grid,
  Link,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import PrintIcon from "@mui/icons-material/Print";
import {
  getHrFormsOrgSummary,
  getTaUserHrForm,
  getTaUserHrProfile,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import ContractorPrintPreviewDialog from "../contractorForms/ContractorPrintPreviewDialog";
import ContractorPrintShell from "../contractorForms/ContractorPrintShell";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import { parsePacketSections } from "../contractorForms/parsePacket";
import "../contractorForms/contractorPrint.css";
import packetMarkdown from "./veewash_w2_workforce_forms.md?raw";
import { editorFormIdFor, findW2Form, W2_FORMS } from "./formCatalog";
import { emptyFormValues } from "./formFieldSchemas";
import { buildW2MultiSectionPrintHtml } from "./prefillMarkdown";
import { buildW2PrefillFromHrProfile } from "./w2Prefill";
import W2FormEditor from "./W2FormEditor";

function MarkdownFormPrint({ html }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}

async function saveBlobResponse(res, fallbackName) {
  const blob = res?.data;
  if (!(blob instanceof Blob) || blob.size === 0) {
    return { ok: false, error: "Empty download" };
  }
  const suggested = res.headers?.["x-suggested-filename"];
  const name = suggested || fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
  return { ok: true };
}

export default function W2EmployeeFormsPanel() {
  const { t } = useI18n();
  const printRef = useRef(null);
  const sections = useMemo(() => parsePacketSections(packetMarkdown), []);

  const [employees, setEmployees] = useState([]);
  const [selected, setSelected] = useState(null);
  const [prefill, setPrefill] = useState(null);
  const [loading, setLoading] = useState(true);
  const [profileLoading, setProfileLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeFormId, setActiveFormId] = useState("handbook_acknowledgment");
  const [formFieldValues, setFormFieldValues] = useState({});
  const [printPreviewOpen, setPrintPreviewOpen] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);

  const loadEmployees = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getHrFormsOrgSummary();
      const rows = (res.data || []).filter((row) =>
        (row.lanes_detected || []).includes("employee_w2"),
      );
      setEmployees(
        rows.map((row) => ({
          user_id: row.user_id,
          label: `${row.name || "Employee"}${row.employee_id ? ` (${row.employee_id})` : ""}`,
          name: row.name,
          employee_id: row.employee_id,
        })),
      );
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to load W-2 employees");
      setEmployees([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadEmployees();
  }, [loadEmployees]);

  useEffect(() => {
    const uid = selected?.user_id;
    if (!uid) {
      setPrefill(null);
      return;
    }
    setProfileLoading(true);
    setError("");
    getTaUserHrProfile(uid)
      .then((res) => {
        if (res.data?.error) {
          setError(res.data.error);
          setPrefill(null);
          return;
        }
        setPrefill(buildW2PrefillFromHrProfile(res.data));
      })
      .catch((e) => {
        setError(e?.response?.data?.error || e.message || "Failed to load employee profile");
        setPrefill(null);
      })
      .finally(() => setProfileLoading(false));
  }, [selected?.user_id]);

  const formDef = findW2Form(activeFormId);
  const editorId = editorFormIdFor(formDef);
  const activeFormValues = useMemo(
    () => formFieldValues[editorId] || emptyFormValues(editorId, prefill || {}),
    [formFieldValues, editorId, prefill],
  );

  const formHtml = useMemo(() => {
    if (!formDef?.sections?.length) return "";
    return buildW2MultiSectionPrintHtml(
      sections,
      formDef.sections,
      prefill || {},
      activeFormValues,
      {
        formId: activeFormId,
        editorFormId: editorId,
        formValues: activeFormValues,
      },
    );
  }, [formDef, sections, prefill, activeFormValues, activeFormId, editorId]);

  const printTitle = formDef?.title || t("w2.formsTitle");

  const doPrint = () => {
    requestAnimationFrame(() => {
      openPrintWindow(printRef.current);
    });
  };

  const downloadWorkforcePack = async () => {
    const uid = selected?.user_id;
    const pack = findW2Form("workforce_pack");
    if (!uid || !pack?.catalogFormId) return;
    setDownloadBusy(true);
    setError("");
    try {
      const res = await getTaUserHrForm(uid, pack.catalogFormId, pack.locale || "bilingual");
      if (res.status >= 400) {
        setError(res.error || "Download failed");
        return;
      }
      const ct = (res.headers?.["content-type"] || "").toLowerCase();
      const ext =
        ct.includes("wordprocessingml") || ct.includes("msword")
          ? ".docx"
          : ct.includes("pdf")
            ? ".pdf"
            : ".docx";
      const out = await saveBlobResponse(res, `${pack.catalogFormId}${ext}`);
      if (!out.ok) setError(out.error || "Download failed");
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Download failed");
    } finally {
      setDownloadBusy(false);
    }
  };

  const canWork = selected && prefill && !profileLoading;

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Alert severity="info" className="no-print">
        {t("w2.panelIntro")}
      </Alert>

      <Paper sx={{ p: 2 }} className="no-print">
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          {t("w2.selectTitle")}
        </Typography>
        <Autocomplete
          options={employees}
          loading={loading}
          value={selected}
          onChange={(_, v) => setSelected(v)}
          getOptionLabel={(o) => o?.label || ""}
          isOptionEqualToValue={(a, b) => a?.user_id === b?.user_id}
          renderInput={(params) => (
            <TextField
              {...params}
              label={t("w2.selectLabel")}
              placeholder={t("w2.selectHint")}
            />
          )}
          sx={{ maxWidth: 560 }}
        />
        {profileLoading ? (
          <Box sx={{ mt: 2, display: "flex", alignItems: "center", gap: 1 }}>
            <CircularProgress size={18} />
            <Typography variant="body2" color="text.secondary">
              {t("w2.loadingProfile")}
            </Typography>
          </Box>
        ) : null}
        {prefill ? (
          <Box sx={{ mt: 2 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} useFlexGap flexWrap="wrap">
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t("w2.fieldName")}
                </Typography>
                <Typography variant="body2">{prefill.full_name || "—"}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t("w2.fieldTitle")}
                </Typography>
                <Typography variant="body2">{prefill.job_title || "—"}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t("w2.fieldLocation")}
                </Typography>
                <Typography variant="body2">{prefill.primary_location || "—"}</Typography>
              </Box>
            </Stack>
            {selected?.user_id ? (
              <Link
                component={RouterLink}
                to={`/employees/${selected.user_id}/hr`}
                variant="body2"
                sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, mt: 1.5 }}
              >
                {t("w2.openEmployeeHrHub")}
                <OpenInNewIcon sx={{ fontSize: 16 }} />
              </Link>
            ) : null}
          </Box>
        ) : null}
      </Paper>

      {canWork ? (
        <>
          <Grid container spacing={2} className="no-print" sx={{ width: "100%", minWidth: 0, m: 0 }}>
            <Grid item xs={12} md={4} sx={{ minWidth: 0 }}>
              <Paper sx={{ p: 1.5 }}>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  {t("w2.formsList")}
                </Typography>
                <Stack spacing={0.5}>
                  {W2_FORMS.map((f) => (
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
            <Grid item xs={12} md={8} sx={{ minWidth: 0 }}>
              <Paper sx={{ p: 2, overflow: "hidden" }}>
                <Typography variant="h6" sx={{ mb: 0.5 }}>
                  {formDef?.title}
                </Typography>
                {formDef?.description ? (
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    {formDef.description}
                  </Typography>
                ) : null}
                {formDef?.downloadOnly ? (
                  <Stack spacing={2}>
                    <Typography variant="body2">
                      {t("w2.workforcePackBlurb")}
                    </Typography>
                    <Button
                      variant="contained"
                      startIcon={<DownloadIcon />}
                      disabled={downloadBusy}
                      onClick={downloadWorkforcePack}
                    >
                      {downloadBusy ? t("w2.downloadBusy") : t("w2.downloadWorkforcePack")}
                    </Button>
                  </Stack>
                ) : (
                  <>
                    <W2FormEditor
                      formId={editorId}
                      values={activeFormValues}
                      onChange={(next) =>
                        setFormFieldValues((prev) => ({ ...prev, [editorId]: next }))
                      }
                    />
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
                      <Button variant="outlined" startIcon={<PrintIcon />} onClick={() => setPrintPreviewOpen(true)}>
                        {t("contractor.printPreview")}
                      </Button>
                      <Button variant="contained" startIcon={<PrintIcon />} onClick={doPrint}>
                        {t("w2.printForm")}
                      </Button>
                    </Stack>
                  </>
                )}
              </Paper>
            </Grid>
          </Grid>

          <ContractorPrintPreviewDialog
            open={printPreviewOpen}
            onClose={() => setPrintPreviewOpen(false)}
            title={printTitle}
            printRef={printRef}
          />
          {!formDef?.downloadOnly ? (
            <Box
              ref={printRef}
              className="contractor-print-area"
              sx={{ position: "absolute", left: -9999, top: 0, width: "7.5in", visibility: "hidden" }}
            >
              <ContractorPrintShell prefill={prefill || { company_name: "VeeWash" }} documentTitle={printTitle}>
                {formHtml ? <MarkdownFormPrint html={formHtml} /> : null}
              </ContractorPrintShell>
            </Box>
          ) : null}
        </>
      ) : !loading && !profileLoading ? (
        <Alert severity="info">{t("w2.pickEmployee")}</Alert>
      ) : null}
    </Stack>
  );
}
