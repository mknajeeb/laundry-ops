import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
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
  getPayoutBatchDetails,
  getPayoutBatches,
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
import { downloadPrintDocumentPdf } from "../contractorForms/contractorPrint";
import {
  ACCOUNTANT_W2_DOCS,
  findDocRecord,
  hasDocOnFile,
  resolvePrimaryDocRecord,
} from "../payroll/accountantW2DocCatalog";
import {
  ACCOUNTANT_DOC_CATEGORY_OPTIONS,
  filterAccountantDocumentUsers,
  mapAccountantDocumentUserOption,
} from "../payroll/accountantDocumentUsers";
import DirectDepositFormPrint, {
  buildDirectDepositPrefill,
} from "../payroll/DirectDepositFormPrint";
import { VEEWASH_BRAND } from "../theme/veewashBrand";
import AccountantScopeFilters from "./AccountantScopeFilters";
import { accountantPeriodStatusLabel } from "../payroll/accountantBatchPick";

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

  const [category, setCategory] = useState("w2");
  const [viewMode, setViewMode] = useState("employee");
  const [batches, setBatches] = useState([]);
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [batchWorkers, setBatchWorkers] = useState([]);
  const [employeeModeBatchWorkers, setEmployeeModeBatchWorkers] = useState([]);
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

  const loadBatches = useCallback(async () => {
    try {
      const res = await getPayoutBatches({ worker_category: "w2" });
      setBatches(res.data?.items || []);
    } catch {
      setBatches([]);
    }
  }, []);

  const loadWorkers = useCallback(async () => {
    try {
      const res = await getTaUsers();
      const list = filterAccountantDocumentUsers(res.data?.users || res.data || [], category).map(
        mapAccountantDocumentUserOption,
      );
      setWorkers(list);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load employees");
    }
  }, [category]);

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
    loadBatches();
    loadWorkers();
  }, [loadBatches, loadWorkers]);

  useEffect(() => {
    if (viewMode === "batch") {
      if (!selectedBatchId) {
        setBatchWorkers([]);
        return;
      }
      let cancelled = false;
      getPayoutBatchDetails(Number(selectedBatchId))
        .then((res) => {
          if (cancelled) return;
          const seen = new Set();
          const list = [];
          for (const ln of res.data?.lines || []) {
            const uid = ln.user_id;
            if (!uid || seen.has(uid)) continue;
            seen.add(uid);
            list.push({
              id: uid,
              label: ln.worker_name_snapshot || `User #${uid}`,
            });
          }
          list.sort((a, b) => String(a.label).localeCompare(String(b.label)));
          setBatchWorkers(list);
        })
        .catch(() => {
          if (!cancelled) setBatchWorkers([]);
        });
      return () => {
        cancelled = true;
      };
    }

    if (!selectedBatchId) {
      setEmployeeModeBatchWorkers([]);
      return;
    }
    let cancelled = false;
    getPayoutBatchDetails(Number(selectedBatchId))
      .then((res) => {
        if (cancelled) return;
        const ids = new Set((res.data?.lines || []).map((ln) => ln.user_id).filter(Boolean));
        setEmployeeModeBatchWorkers(workers.filter((w) => ids.has(w.id)));
      })
      .catch(() => {
        if (!cancelled) setEmployeeModeBatchWorkers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [viewMode, selectedBatchId, workers]);

  useEffect(() => {
    setSelected(null);
  }, [category, viewMode, selectedBatchId]);

  const workerOptions =
    viewMode === "batch"
      ? batchWorkers
      : selectedBatchId
        ? employeeModeBatchWorkers
        : workers;
  const workerLabel =
    category === "system_users" ? "System user" : "W-2 employee";

  const handleViewModeChange = (mode) => {
    setViewMode(mode);
    setSelected(null);
    if (mode === "employee") {
      setSelectedBatchId("");
    }
  };

  useEffect(() => {
    loadEmployee(selected?.id);
  }, [selected?.id, loadEmployee]);

  const downloadDirectDeposit = async () => {
    if (!printRef.current) return;
    const slug =
      String(selected?.label || "employee")
        .trim()
        .replace(/[^\w.-]+/g, "-")
        .replace(/^-+|-+$/g, "") || "employee";
    setBusy("direct_deposit_download");
    setError("");
    try {
      const ok = await downloadPrintDocumentPdf(printRef.current, {
        pageSize: "letter portrait",
        filename: `direct-deposit-${slug}.pdf`,
        title: "Direct Deposit Authorization",
      });
      if (!ok) setError("Could not generate direct deposit PDF.");
    } catch (e) {
      setError(e?.message || "Direct deposit PDF download failed.");
    } finally {
      setBusy("");
    }
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
        <Typography variant="body2" sx={{ opacity: 0.92, maxWidth: 640 }}>
          Print direct deposit from VeeWash. Upload signed copies for the other items. Accountants can
          view and print; admins can upload and manage files.
        </Typography>
      </Paper>

      <AccountantScopeFilters
        viewMode={viewMode}
        onViewModeChange={handleViewModeChange}
        batches={batches}
        selectedBatchId={selectedBatchId}
        onBatchChange={setSelectedBatchId}
        workers={workerOptions}
        selectedWorker={selected}
        onWorkerChange={setSelected}
        workerLabel={workerLabel}
        category={category}
        onCategoryChange={setCategory}
        categoryOptions={ACCOUNTANT_DOC_CATEGORY_OPTIONS}
        weekStartsOn={0}
        periodStart={periodStart}
        periodEnd={periodEnd}
        onPeriodChange={({ start, end, batchId }) => {
          setPeriodStart(start || "");
          setPeriodEnd(end || "");
          if (batchId) setSelectedBatchId(String(batchId));
        }}
        batchStatusLabel={accountantPeriodStatusLabel}
      />

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
                          <Tooltip title="Download PDF">
                            <IconButton
                              size="small"
                              disabled={busy === "direct_deposit_download"}
                              onClick={downloadDirectDeposit}
                            >
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
      ) : viewMode === "batch" && !selectedBatchId ? (
        <Alert severity="info">Select a batch, then choose an employee to manage documents.</Alert>
      ) : (
        <Alert severity="info">
          Select a {category === "system_users" ? "system user" : "W-2 employee"} to manage documents.
        </Alert>
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
        pageSize="letter portrait"
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
