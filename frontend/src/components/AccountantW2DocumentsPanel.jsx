import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import PrintIcon from "@mui/icons-material/Print";
import UploadIcon from "@mui/icons-material/Upload";
import VisibilityIcon from "@mui/icons-material/Visibility";
import { createRoot } from "react-dom/client";
import {
  getTaHrEmployerSettings,
  getTaUserDocuments,
  getTaUserHrForm,
  getTaUserHrProfile,
  getTaUsers,
  postTaUserDocument,
  putTaUserDocument,
} from "../api";
import { useAuth } from "../context/AuthContext";
import ContractorPrintPreviewDialog from "../contractorForms/ContractorPrintPreviewDialog";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import {
  ACCOUNTANT_W2_DOCS,
  findDocRecord,
} from "../payroll/accountantW2DocCatalog";
import DirectDepositFormPrint, {
  buildDirectDepositPrefill,
} from "../payroll/DirectDepositFormPrint";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

async function saveBlobResponse(res, fallbackName) {
  const blob = res?.data;
  if (!(blob instanceof Blob)) return { ok: false, error: "Invalid response" };
  const ct = String(res.headers?.["content-type"] || blob.type || "");
  if (ct.includes("json")) {
    try {
      const text = await blob.text();
      const j = JSON.parse(text);
      if (j?.error) return { ok: false, error: j.error };
    } catch {
      /* fall through */
    }
  }
  const name =
    res.headers?.["x-suggested-filename"] ||
    res.headers?.["content-disposition"]?.match(/filename="([^"]+)"/)?.[1] ||
    fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name || fallbackName;
  a.click();
  URL.revokeObjectURL(url);
  return { ok: true };
}

function isW2Employee(user) {
  const lanes = user?.hr_form_lanes || [];
  if (lanes.includes("employee_w2")) return true;
  if (lanes.includes("contractor_1099") && !lanes.includes("employee_w2")) return false;
  return true;
}

export default function AccountantW2DocumentsPanel() {
  const { hasPerm } = useAuth();
  const canUpload = hasPerm("users.edit") || hasPerm("ta.settings");
  const printRef = useRef(null);

  const [workers, setWorkers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [records, setRecords] = useState([]);
  const [prefill, setPrefill] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [uploadOpen, setUploadOpen] = useState(null);
  const [uploadUri, setUploadUri] = useState("");
  const [printPreviewOpen, setPrintPreviewOpen] = useState(false);

  const loadWorkers = useCallback(async () => {
    try {
      const res = await getTaUsers();
      const list = (res.data?.users || res.data || [])
        .filter(isW2Employee)
        .map((u) => ({
          id: u.id,
          label: `${u.first_name || ""} ${u.last_name || ""}`.trim() || u.email || `#${u.id}`,
        }));
      setWorkers(list);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load employees");
    }
  }, []);

  const loadEmployee = useCallback(async (userId) => {
    if (!userId) {
      setRecords([]);
      setPrefill(null);
      return;
    }
    setError("");
    try {
      const [docsRes, hrRes, orgRes] = await Promise.all([
        getTaUserDocuments(userId),
        getTaUserHrProfile(userId),
        getTaHrEmployerSettings().catch(() => ({ data: {} })),
      ]);
      setRecords(docsRes.data?.items || docsRes.data || []);
      const data = hrRes.data || {};
      setPrefill(
        buildDirectDepositPrefill(
          data.payroll || {},
          data.hr || {},
          data.org_settings || orgRes.data || {},
        ),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load employee files");
    }
  }, []);

  useEffect(() => {
    loadWorkers();
  }, [loadWorkers]);

  useEffect(() => {
    loadEmployee(selected?.id);
  }, [selected?.id, loadEmployee]);

  const downloadHrForm = async (formId, openAfter = false) => {
    if (!selected?.id) return;
    setBusy(formId);
    try {
      const res = await getTaUserHrForm(selected.id, formId, "en");
      if (openAfter && res?.data instanceof Blob) {
        const url = URL.createObjectURL(res.data);
        window.open(url, "_blank", "noopener,noreferrer");
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        return;
      }
      const out = await saveBlobResponse(res, `${formId}-${selected.id}.pdf`);
      if (!out.ok) setError(out.error || "Download failed");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Download failed");
    } finally {
      setBusy("");
    }
  };

  const openUploaded = (rec) => {
    const uri = rec?.file_uri;
    if (!uri) {
      setError("No file uploaded for this document yet.");
      return;
    }
    window.open(uri, "_blank", "noopener,noreferrer");
  };

  const printDirectDeposit = () => {
    if (!prefill) return;
    const host = document.createElement("div");
    const root = createRoot(host);
    root.render(<DirectDepositFormPrint prefill={prefill} />);
    requestAnimationFrame(() => {
      openPrintWindow(host);
      setTimeout(() => root.unmount(), 2000);
    });
  };

  const saveUpload = async () => {
    if (!canUpload || !selected?.id || !uploadOpen) return;
    const uri = uploadUri.trim();
    if (!uri) {
      setError("Paste a file URL to upload.");
      return;
    }
    setBusy(uploadOpen.code);
    try {
      const ex = findDocRecord(records, uploadOpen.code);
      if (ex?.id) {
        await putTaUserDocument(selected.id, ex.id, {
          ...ex,
          file_uri: uri,
          status: "received",
        });
      } else {
        await postTaUserDocument(selected.id, {
          document_code: uploadOpen.code,
          document_name: uploadOpen.label,
          status: "received",
          file_uri: uri,
          source_kind: "uploaded",
        });
      }
      setUploadOpen(null);
      setUploadUri("");
      await loadEmployee(selected.id);
    } catch (e) {
      setError(e.response?.data?.error || "Upload failed");
    } finally {
      setBusy("");
    }
  };

  const docActions = useMemo(
    () =>
      ACCOUNTANT_W2_DOCS.map((doc) => {
        const rec = findDocRecord(records, doc.code);
        const hasFile = !!rec?.file_uri;
        return { ...doc, rec, hasFile };
      }),
    [records],
  );

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper
        elevation={0}
        sx={{
          p: 2.5,
          borderRadius: 2,
          background: VEEWASH_BRAND.gradient,
          color: "#fff",
          boxShadow: VEEWASH_BRAND.shadow,
        }}
      >
        <Typography variant="overline" sx={{ opacity: 0.9, letterSpacing: 1.2, fontWeight: 700 }}>
          Accountant · W-2
        </Typography>
        <Typography variant="h6" sx={{ fontWeight: 800, mb: 0.5 }}>
          Employee Documents
        </Typography>
        <Typography variant="body2" sx={{ opacity: 0.92, mb: 2, maxWidth: 640 }}>
          Download the VeeWash direct deposit form or view statutory HR files. Accountants can view
          and print; admins can upload signed copies.
        </Typography>
        <Autocomplete
          options={workers}
          value={selected}
          onChange={(_, v) => setSelected(v)}
          getOptionLabel={(o) => o?.label || ""}
          renderInput={(params) => (
            <TextField
              {...params}
              label="W-2 employee"
              size="small"
              placeholder="Search by name"
              sx={{
                maxWidth: 420,
                bgcolor: "rgba(255,255,255,0.98)",
                borderRadius: 1,
                "& .MuiOutlinedInput-root": { borderRadius: 1 },
              }}
            />
          )}
        />
      </Paper>

      {selected ? (
        <TableContainer
          component={Paper}
          elevation={0}
          sx={{
            borderRadius: 2,
            border: `1px solid ${VEEWASH_BRAND.border}`,
            overflow: "hidden",
          }}
        >
          <Table size="small">
            <TableHead>
              <TableRow
                sx={{
                  bgcolor: VEEWASH_BRAND.primaryLight,
                  "& th": { fontWeight: 700, color: VEEWASH_BRAND.primaryDark, borderBottom: `2px solid ${VEEWASH_BRAND.primary}` },
                }}
              >
                <TableCell>Document</TableCell>
                <TableCell width={120}>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {docActions.map((doc) => (
                <TableRow
                  key={doc.code}
                  hover
                  sx={{
                    "&:nth-of-type(even)": { bgcolor: alpha(VEEWASH_BRAND.primary, 0.03) },
                  }}
                >
                  <TableCell sx={{ fontWeight: 500 }}>{doc.label}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={
                        doc.kind === "generated"
                          ? "Ready"
                          : doc.hasFile
                            ? "On file"
                            : "Missing"
                      }
                      color={
                        doc.kind === "generated" || doc.hasFile ? "success" : "warning"
                      }
                      variant="outlined"
                      sx={{
                        fontWeight: 600,
                        borderColor:
                          doc.kind === "generated" || doc.hasFile
                            ? VEEWASH_BRAND.teal
                            : undefined,
                      }}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={0.5} justifyContent="flex-end" flexWrap="wrap" useFlexGap>
                      {doc.kind === "generated" ? (
                        <>
                          <Tooltip title="Print">
                            <IconButton size="small" onClick={() => setPrintPreviewOpen(true)}>
                              <PrintIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Download (print to PDF)">
                            <IconButton size="small" onClick={printDirectDeposit}>
                              <DownloadIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </>
                      ) : null}

                      {doc.kind === "hr_form" ? (
                        <>
                          <Button
                            size="small"
                            color="primary"
                            sx={{ color: VEEWASH_BRAND.primaryDark }}
                            startIcon={<VisibilityIcon />}
                            disabled={busy === doc.formId}
                            onClick={() => downloadHrForm(doc.formId, true)}
                          >
                            View
                          </Button>
                          <Button
                            size="small"
                            startIcon={<DownloadIcon />}
                            disabled={busy === doc.formId}
                            onClick={() => downloadHrForm(doc.formId, false)}
                          >
                            Download
                          </Button>
                        </>
                      ) : null}

                      {doc.kind === "uploaded" && doc.hasFile ? (
                        <>
                          <Button size="small" startIcon={<VisibilityIcon />} onClick={() => openUploaded(doc.rec)}>
                            View
                          </Button>
                          <Button size="small" startIcon={<PrintIcon />} onClick={() => openUploaded(doc.rec)}>
                            Print
                          </Button>
                          {!doc.viewPrintOnly ? (
                            <Button size="small" startIcon={<DownloadIcon />} onClick={() => openUploaded(doc.rec)}>
                              Download
                            </Button>
                          ) : null}
                        </>
                      ) : null}

                      {canUpload && doc.allowUpload ? (
                        <Button
                          size="small"
                          startIcon={<UploadIcon />}
                          onClick={() => {
                            setUploadOpen(doc);
                            setUploadUri(doc.rec?.file_uri || "");
                          }}
                        >
                          Upload
                        </Button>
                      ) : null}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Alert severity="info">Select a W-2 employee to manage documents.</Alert>
      )}

      <Box ref={printRef} sx={{ display: "none" }} aria-hidden>
        {prefill ? <DirectDepositFormPrint prefill={prefill} /> : null}
      </Box>

      <ContractorPrintPreviewDialog
        open={printPreviewOpen}
        onClose={() => setPrintPreviewOpen(false)}
        title="Direct Deposit Authorization"
      >
        {prefill ? <DirectDepositFormPrint prefill={prefill} /> : null}
      </ContractorPrintPreviewDialog>

      <Dialog open={!!uploadOpen} onClose={() => setUploadOpen(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Upload — {uploadOpen?.label}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Paste a secure link to the signed document (Google Drive, Dropbox, S3, etc.).
          </Typography>
          <TextField
            fullWidth
            size="small"
            label="File URL"
            value={uploadUri}
            onChange={(e) => setUploadUri(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUploadOpen(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveUpload} disabled={!!busy}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
