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
import DeleteIcon from "@mui/icons-material/Delete";
import DownloadIcon from "@mui/icons-material/Download";
import PrintIcon from "@mui/icons-material/Print";
import UploadIcon from "@mui/icons-material/Upload";
import VisibilityIcon from "@mui/icons-material/Visibility";
import {
  deleteTaUserDocument,
  getTaHrEmployerSettings,
  getTaUserDocumentFile,
  getTaUserDocuments,
  getTaUserHrProfile,
  getTaUsers,
  postTaUserDocument,
  putTaUserDocument,
  uploadTaUserDocumentFile,
} from "../api";
import { useAuth } from "../context/AuthContext";
import ContractorPrintPreviewDialog from "../contractorForms/ContractorPrintPreviewDialog";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import {
  ACCOUNTANT_W2_DOCS,
  findDocRecord,
  hasDocOnFile,
  resolvePrimaryDocRecord,
} from "../payroll/accountantW2DocCatalog";
import DirectDepositFormPrint, {
  buildDirectDepositPrefill,
} from "../payroll/DirectDepositFormPrint";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

function isW2Employee(user) {
  const lanes = user?.hr_form_lanes || [];
  return lanes.includes("employee_w2");
}

async function fetchDocumentBlob(userId, record, { download = false } = {}) {
  if (!userId || !record?.id) {
    return { ok: false, error: "No file on record." };
  }
  try {
    const res = await getTaUserDocumentFile(userId, record.id, { download });
    if (res.status < 200 || res.status >= 300) {
      return { ok: false, error: `Could not load file (HTTP ${res.status})` };
    }
    const blob = res.data;
    if (!(blob instanceof Blob) || blob.size === 0) {
      return { ok: false, error: "Invalid file response" };
    }
    return { ok: true, blob };
  } catch (e) {
    return { ok: false, error: e.response?.data?.error || e.message || "Could not load file" };
  }
}

async function openUploadedView(userId, rec) {
  const fetched = await fetchDocumentBlob(userId, rec);
  if (!fetched.ok) return fetched;
  const url = URL.createObjectURL(fetched.blob);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 120000);
  return { ok: true };
}

async function openUploadedPrint(userId, rec) {
  const fetched = await fetchDocumentBlob(userId, rec);
  if (!fetched.ok) return fetched;
  const url = URL.createObjectURL(fetched.blob);
  const w = window.open(url, "_blank", "noopener,noreferrer");
  if (w) {
    const tryPrint = () => {
      try {
        w.focus();
        w.print();
      } catch {
        /* cross-origin PDF may block auto-print */
      }
    };
    w.addEventListener("load", () => setTimeout(tryPrint, 500));
    setTimeout(tryPrint, 1500);
    window.setTimeout(() => URL.revokeObjectURL(url), 120000);
  }
  return { ok: true };
}

async function downloadUploaded(userId, rec, label) {
  const fetched = await fetchDocumentBlob(userId, rec, { download: true });
  if (!fetched.ok) return fetched;
  const url = URL.createObjectURL(fetched.blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = label || "document";
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { ok: true };
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
  const [uploadFile, setUploadFile] = useState(null);
  const [printPreviewOpen, setPrintPreviewOpen] = useState(false);
  const uploadInputRef = useRef(null);

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

  const printDirectDeposit = () => {
    if (!printRef.current) return;
    openPrintWindow(printRef.current, { pageSize: "A4 portrait" });
  };

  const saveUpload = async () => {
    if (!canUpload || !selected?.id || !uploadOpen) return;
    if (!uploadFile) {
      setError("Choose a file to upload.");
      return;
    }
    setBusy(uploadOpen.code);
    setError("");
    try {
      const up = await uploadTaUserDocumentFile(selected.id, uploadFile);
      const uri = up.data?.file_uri;
      if (!uri) {
        setError("Upload did not return a file location.");
        return;
      }
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
      setUploadFile(null);
      await loadEmployee(selected.id);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Upload failed");
    } finally {
      setBusy("");
    }
  };

  const removeDocument = async (doc) => {
    if (!canUpload || !selected?.id || !doc.rec?.id) return;
    if (!window.confirm(`Remove uploaded file for ${doc.label}?`)) return;
    setBusy(doc.code);
    setError("");
    try {
      await deleteTaUserDocument(selected.id, doc.rec.id);
      await loadEmployee(selected.id);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete failed");
    } finally {
      setBusy("");
    }
  };

  const docActions = useMemo(
    () =>
      ACCOUNTANT_W2_DOCS.map((doc) => {
        const rec = resolvePrimaryDocRecord(records, doc.code);
        const hasFile = hasDocOnFile(records, doc.code);
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
          Print direct deposit from VeeWash. Upload signed copies for the other items. Accountants can
          view and print; admins can upload and manage files.
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
                  "& th": {
                    fontWeight: 700,
                    color: VEEWASH_BRAND.primaryDark,
                    borderBottom: `2px solid ${VEEWASH_BRAND.primary}`,
                  },
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
                    <Stack
                      direction="row"
                      spacing={0.5}
                      justifyContent="flex-end"
                      flexWrap="wrap"
                      useFlexGap
                    >
                      {doc.kind === "generated" ? (
                        <>
                          <Tooltip title="Print preview">
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

                      {doc.kind === "uploaded" && doc.hasFile ? (
                        <>
                          <Button
                            size="small"
                            startIcon={<VisibilityIcon />}
                            disabled={busy === doc.code}
                            onClick={async () => {
                              const result = await openUploadedView(selected.id, doc.rec);
                              if (!result.ok) setError(result.error || "No file on record.");
                            }}
                          >
                            View
                          </Button>
                          <Button
                            size="small"
                            startIcon={<PrintIcon />}
                            disabled={busy === doc.code}
                            onClick={async () => {
                              const result = await openUploadedPrint(selected.id, doc.rec);
                              if (!result.ok) setError(result.error || "No file on record.");
                            }}
                          >
                            Print
                          </Button>
                          {canUpload ? (
                            <>
                              <Button
                                size="small"
                                startIcon={<DownloadIcon />}
                                disabled={busy === doc.code}
                                onClick={async () => {
                                  const result = await downloadUploaded(selected.id, doc.rec, doc.label);
                                  if (!result.ok) setError(result.error || "Download failed.");
                                }}
                              >
                                Download
                              </Button>
                              <Button
                                size="small"
                                color="error"
                                startIcon={<DeleteIcon />}
                                disabled={busy === doc.code}
                                onClick={() => removeDocument(doc)}
                              >
                                Delete
                              </Button>
                            </>
                          ) : null}
                        </>
                      ) : null}

                      {canUpload && doc.allowUpload ? (
                        <Button
                          size="small"
                          startIcon={<UploadIcon />}
                          disabled={busy === doc.code}
                          onClick={() => {
                            setUploadOpen(doc);
                            setUploadFile(null);
                          }}
                        >
                          {doc.hasFile ? "Replace" : "Upload"}
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

      <Box
        ref={printRef}
        sx={{ position: "absolute", left: -9999, top: 0, visibility: "hidden", width: "186mm" }}
        aria-hidden
      >
        {prefill ? <DirectDepositFormPrint prefill={prefill} /> : null}
      </Box>

      <ContractorPrintPreviewDialog
        open={printPreviewOpen}
        onClose={() => setPrintPreviewOpen(false)}
        title="Direct Deposit Authorization"
        printRef={printRef}
        pageSize="A4 portrait"
      />

      <Dialog
        open={!!uploadOpen}
        onClose={() => {
          setUploadOpen(null);
          setUploadFile(null);
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Upload — {uploadOpen?.label}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Choose a signed PDF or image from your computer (max 15 MB).
          </Typography>
          <input
            ref={uploadInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,application/pdf,image/*"
            style={{ display: "none" }}
            onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
          />
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button variant="outlined" onClick={() => uploadInputRef.current?.click()}>
              Browse…
            </Button>
            <Typography variant="body2" color="text.secondary">
              {uploadFile ? uploadFile.name : "No file selected"}
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setUploadOpen(null);
              setUploadFile(null);
            }}
          >
            Cancel
          </Button>
          <Button variant="contained" onClick={saveUpload} disabled={!!busy || !uploadFile}>
            Upload
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
