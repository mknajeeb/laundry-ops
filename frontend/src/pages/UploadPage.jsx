import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  FormControlLabel,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { Refresh } from "@mui/icons-material";
import {
  addUploadBatchRow,
  confirmUploadBatch,
  deleteUploadBatch,
  deleteUploadBatchRow,
  getRinseBagExportConfig,
  getUploadBatches,
  getCurrentUploadBatch,
  getUploadBatchRows,
  getRinseImportUploadBatchJob,
  cancelRinseImportUploadBatchJob,
  overrideUploadBatchRow,
  postRinseBagExport,
  startRinseImportUploadBatchJob,
  uploadOrders,
  uploadPortalOrdersCsv,
} from "../api";
import StagingOrderManagementTable from "../components/StagingOrderManagementTable";
import { useAuth } from "../context/AuthContext";
import { formatCalendarDateLabel, toDateInputValue } from "../utils/datetimeFormat";

const EMPTY_FORM = {
  date_clean: "",
  name_clean: "",
  weight_num: "",
  service_type: "WF",
  rush_type: "NON-RUSH",
  row_status: "OVERRIDDEN",
  reason: "",
};

function UploadPage({ user }) {
  const { hasPerm } = useAuth();
  const [file, setFile] = useState(null);
  const [portalCsvFile, setPortalCsvFile] = useState(null);
  const [batchDate, setBatchDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [batch, setBatch] = useState(null);
  const [batches, setBatches] = useState([]);
  const [rows, setRows] = useState([]);
  const [viewTab, setViewTab] = useState("REVIEW");
  const [rowStatusFilter, setRowStatusFilter] = useState("ALL");

  const [editOpen, setEditOpen] = useState(false);
  const [editRowId, setEditRowId] = useState(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState(EMPTY_FORM);

  const [message, setMessage] = useState({ type: "info", text: "" });

  const [rinseExportLoading, setRinseExportLoading] = useState(false);
  const [rinseImportJobId, setRinseImportJobId] = useState(null);
  const [rinseImportStopBusy, setRinseImportStopBusy] = useState(false);
  const [rinseExportHint, setRinseExportHint] = useState("");
  const [portalScrapeLog, setPortalScrapeLog] = useState("");
  const [rinseImportProgressNote, setRinseImportProgressNote] = useState("");
  /** Optional: narrow one job to a slice of Rinse list pages (see Azure / per-page jobs). */
  const [rinseImportPageStart, setRinseImportPageStart] = useState("");
  const [rinseImportMaxPages, setRinseImportMaxPages] = useState("");
  /** One Playwright run per N list pages, then merge — sequential, single job, one draft commit. */
  const [rinseImportSequential, setRinseImportSequential] = useState(false);
  const [rinseImportSeqChunkPages, setRinseImportSeqChunkPages] = useState("1");
  const [rinseImportMaxSeqChunks, setRinseImportMaxSeqChunks] = useState("");
  const [showFullPortalScrapeLog, setShowFullPortalScrapeLog] = useState(false);
  const portalLogRef = useRef(null);

  const rinseImportTicketNo = useMemo(() => {
    const m = String(rinseImportProgressNote || "").match(/\bticket\s+(\d+)/i);
    return m ? parseInt(m[1], 10) : null;
  }, [rinseImportProgressNote]);

  const isRinseExportAdmin = useMemo(() => {
    const r = (user?.roles || []).map((x) => String(x).toUpperCase());
    return r.includes("ADMIN") || r.includes("SUPER_ADMIN") || r.includes("PLATFORM_ADMIN");
  }, [user?.roles]);
  const canRunPortalScrape = isRinseExportAdmin || hasPerm("upload.create");

  const isConfirmed = (batch?.state || "").toUpperCase() === "CONFIRMED";
  const isDraft = (batch?.state || "").toUpperCase() === "DRAFT";

  const formatBatchLabel = (row) => {
    if (!row) return "No active batch";
    const dtSource = row.created_at || row.updated_at || row.confirmed_at || row.closed_at;
    const dt = dtSource ? new Date(dtSource) : null;
    const dtLabel = dt && !Number.isNaN(dt.getTime())
      ? dt.toLocaleString(undefined, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "No time";
    return `Batch #${row.id} • ${dtLabel}`;
  };

  const filteredRows = useMemo(() => {
    if (rowStatusFilter === "ALL") return rows;
    return rows.filter((r) => String(r.row_status || "").toUpperCase() === rowStatusFilter);
  }, [rows, rowStatusFilter]);

  const rowSummary = useMemo(() => {
    const byStatus = {
      ACCEPTED: 0,
      OVERRIDDEN: 0,
      REJECTED_DUPLICATE: 0,
      NEEDS_ATTENTION: 0,
      DELETED: 0,
    };

    rows.forEach((r) => {
      const key = String(r.row_status || "").toUpperCase();
      if (Object.prototype.hasOwnProperty.call(byStatus, key)) byStatus[key] += 1;
    });

    return byStatus;
  }, [rows]);

  const loadRows = async (batchId, statusFilter = "") => {
    if (!batchId) {
      setRows([]);
      return;
    }

    try {
      setLoadingRows(true);
      const res = await getUploadBatchRows(batchId, statusFilter === "ALL" ? "" : statusFilter);
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      console.error(error);
      setRows([]);
      setMessage({ type: "error", text: "Failed to load batch rows." });
    } finally {
      setLoadingRows(false);
    }
  };

  const loadCurrentBatch = async (statusFilter = rowStatusFilter) => {
    try {
      const res = await getCurrentUploadBatch();
      const current = res?.data || null;
      setBatch(current);

      if (current?.batch_date) {
        const d = toDateInputValue(current.batch_date);
        if (d) setBatchDate(d);
      }

      if (current?.id) {
        await loadRows(current.id, statusFilter);
        setViewTab("REVIEW");
      } else {
        setRows([]);
      }
    } catch (error) {
      console.error(error);
      setMessage({ type: "error", text: "Failed to load current batch." });
    }
  };

  const loadBatchHistory = async () => {
    try {
      const res = await getUploadBatches(15);
      setBatches(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    loadCurrentBatch("ALL");
    loadBatchHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!showFullPortalScrapeLog) return;
    const el = portalLogRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [portalScrapeLog, showFullPortalScrapeLog]);

  useEffect(() => {
    if (!canRunPortalScrape) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getRinseBagExportConfig();
        if (cancelled) return;
        const d = res.data || {};
        let hint = d.hint || "";
        if (!d.enabled) {
          if (d.rinse_export_env_key_present === false) {
            hint +=
              " Workers may not see the flag until you Restart the API App Service (Save settings first). SSH can show printenv=1 before gunicorn reloads.";
          } else {
            hint +=
              " Set Value to 1 (no quotes), Save, then Restart the App Service.";
          }
        }
        setRinseExportHint(hint.trim());
      } catch {
        if (!cancelled) setRinseExportHint("");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canRunPortalScrape]);

  const uploadFile = async () => {
    if (!file) {
      setMessage({ type: "warning", text: "Please choose a file first." });
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("batch_date", batchDate);

    try {
      setLoading(true);
      const res = await uploadOrders(formData);
      setMessage({
        type: "success",
        text: `Draft uploaded. Accepted: ${res.data.rows_inserted}, Rejected: ${res.data.rejected_rows}, Needs Attention: ${res.data.needs_attention_rows}`,
      });
      await loadCurrentBatch("ALL");
      await loadBatchHistory();
    } catch (error) {
      console.error(error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        "Upload failed";
      setMessage({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  };

  const uploadPortalCsv = async () => {
    if (!portalCsvFile) {
      setMessage({ type: "warning", text: "Choose a portal CSV (.csv) first." });
      return;
    }
    const formData = new FormData();
    formData.append("file", portalCsvFile);
    formData.append("batch_date", batchDate);
    try {
      setLoading(true);
      const res = await uploadPortalOrdersCsv(formData);
      setMessage({
        type: "success",
        text: `Portal CSV draft uploaded. Accepted: ${res.data.rows_inserted}, Rejected: ${res.data.rejected_rows}, Needs Attention: ${res.data.needs_attention_rows}`,
      });
      await loadCurrentBatch("ALL");
      await loadBatchHistory();
    } catch (error) {
      console.error(error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        "Portal CSV upload failed";
      setMessage({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  };

  const openEdit = (row) => {
    setEditRowId(row.id);
    setEditForm({
      date_clean: String(row.date_clean || "").slice(0, 10),
      name_clean: row.name_clean || "",
      weight_num: row.weight_num ?? "",
      service_type: row.service_type || "WF",
      rush_type: row.rush_type || "NON-RUSH",
      row_status: row.row_status || "OVERRIDDEN",
      reason: row.reason || "",
    });
    setEditOpen(true);
  };

  const saveEdit = async () => {
    if (!batch?.id || !editRowId) return;

    try {
      setLoading(true);
      await overrideUploadBatchRow(batch.id, editRowId, {
        ...editForm,
        weight_num: editForm.weight_num === "" ? null : Number(editForm.weight_num),
      });
      setEditOpen(false);
      setMessage({ type: "success", text: "Row updated." });
      await loadCurrentBatch(rowStatusFilter);
      await loadBatchHistory();
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Row update failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (rowId) => {
    if (!batch?.id) return;

    try {
      setLoading(true);
      await deleteUploadBatchRow(batch.id, rowId);
      setMessage({ type: "success", text: "Row deleted from batch." });
      await loadCurrentBatch(rowStatusFilter);
      await loadBatchHistory();
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Delete failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async () => {
    if (!batch?.id) return;

    try {
      setLoading(true);
      await addUploadBatchRow(batch.id, {
        ...addForm,
        weight_num: addForm.weight_num === "" ? null : Number(addForm.weight_num),
      });
      setAddOpen(false);
      setAddForm(EMPTY_FORM);
      setMessage({ type: "success", text: "Row added to batch." });
      await loadCurrentBatch(rowStatusFilter);
      await loadBatchHistory();
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Add row failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!batch?.id) return;

    try {
      setLoading(true);
      await confirmUploadBatch(batch.id, false);
      setMessage({ type: "success", text: "Batch confirmed and applied to staging." });
      await loadCurrentBatch(rowStatusFilter);
      await loadBatchHistory();
      window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"));
    } catch (error) {
      const status = error?.response?.status;
      const data = error?.response?.data || {};

      if (status === 409 && data.attention_count) {
        const ok = window.confirm(
          `${data.attention_count} rows still need attention. Confirm anyway?`
        );
        if (ok) {
          await confirmUploadBatch(batch.id, true);
          setMessage({ type: "success", text: "Batch force-confirmed and applied." });
          await loadCurrentBatch(rowStatusFilter);
          await loadBatchHistory();
          window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"));
        }
      } else {
        setMessage({
          type: "error",
          text: data.error || "Batch confirm failed.",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const onFilterChange = async (nextFilter) => {
    setRowStatusFilter(nextFilter);
    await loadRows(batch?.id, nextFilter);
  };

  const runRinseBagExport = async () => {
    const ok = window.confirm(
      "Run Rinse cleaner-tickets export on the server? This can take several minutes. Your browser must stay open until the download starts."
    );
    if (!ok) return;

    try {
      setRinseExportLoading(true);
      setMessage({ type: "info", text: "Running Rinse export on server…" });
      const res = await postRinseBagExport();
      const cd = res.headers["content-disposition"] || "";
      let filename = `rinse-bag-export-${Date.now()}.csv`;
      const star = /filename\*=UTF-8''([^;\n]+)/i.exec(cd);
      const quoted = /filename="([^"]+)"/i.exec(cd);
      const plain = /filename=([^;\n]+)/i.exec(cd);
      if (star) {
        filename = decodeURIComponent(star[1].trim());
      } else if (quoted) {
        filename = quoted[1].trim();
      } else if (plain) {
        filename = plain[1].trim().replace(/^["']|["']$/g, "");
      }
      if (!filename.endsWith(".csv")) filename += ".csv";
      const blob = new Blob([res.data], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      setMessage({
        type: "success",
        text: `Downloaded ${filename}. Bag-ID export for bag / QR workflows. For order staging, use portal CSV upload or “Run portal scrape & load draft” above.`,
      });
      const cfg = await getRinseBagExportConfig();
      setRinseExportHint(cfg.data?.hint || "");
    } catch (error) {
      console.error(error);
      let text = error?.response?.data?.error || error?.message || "Rinse export failed.";
      const data = error?.response?.data;
      if (data instanceof Blob) {
        try {
          const raw = await data.text();
          try {
            const j = JSON.parse(raw);
            if (j?.error) text = j.error;
            if (j?.stdout_tail) text = `${text}\n${String(j.stdout_tail).slice(-800)}`;
            if (j?.stderr_tail) text = `${text}\n${String(j.stderr_tail).slice(-1200)}`;
          } catch {
            if (raw && raw.trim()) {
              const snippet = raw.trim().slice(0, 800);
              if (
                /<html/i.test(snippet) ||
                /Internal Server Error/i.test(snippet) ||
                /502 Bad Gateway/i.test(snippet) ||
                /504 Gateway/i.test(snippet)
              ) {
                text =
                  "Rinse export failed: the API returned a generic HTML error (not JSON). " +
                  "Common causes: Azure/proxy timeout (~2–4 min), Gunicorn worker killed (OOM/timeout), or an uncaught server crash. " +
                  "Check Azure → laundryops-api → Log stream. Try RINSE_MAX_PAGES=3 for a shorter run, " +
                  "ensure GUNICORN_TIMEOUT≥1200 on the API, and use a larger App Service SKU if the worker runs out of memory.";
              } else {
                text = snippet;
              }
            }
          }
        } catch {
          /* ignore */
        }
      }
      setMessage({ type: "error", text });
    } finally {
      setRinseExportLoading(false);
    }
  };

  const runRinseImportToBatch = async () => {
    const ok = window.confirm("Run server scrape into draft for the batch date above?");
    if (!ok) return;

    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    try {
      setRinseExportLoading(true);
      setPortalScrapeLog("");
      setRinseImportProgressNote("");
      setShowFullPortalScrapeLog(false);
      setMessage({ type: "info", text: "Rinse • starting…" });
      const jobBody = { batch_date: batchDate };
      const ps = String(rinseImportPageStart || "").trim();
      const mp = String(rinseImportMaxPages || "").trim();
      if (ps !== "") {
        const n = parseInt(ps, 10);
        if (!Number.isNaN(n)) jobBody.page_start = n;
      }
      if (rinseImportSequential) {
        const c = parseInt(String(rinseImportSeqChunkPages || "1").trim(), 10);
        if (!Number.isNaN(c) && c >= 1) jobBody.sequential_chunk_pages = c;
        const mxc = String(rinseImportMaxSeqChunks || "").trim();
        if (mxc !== "") {
          const n = parseInt(mxc, 10);
          if (!Number.isNaN(n) && n >= 1) jobBody.max_sequential_chunks = n;
        }
      } else if (mp !== "") {
        const n = parseInt(mp, 10);
        if (!Number.isNaN(n)) jobBody.max_pages = n;
      }
      const startRes = await startRinseImportUploadBatchJob(jobBody);
      const jobId = startRes.data?.job_id;
      if (!jobId) {
        setMessage({ type: "error", text: "Server did not return a job id for Rinse import." });
        return;
      }
      setRinseImportJobId(jobId);

      const deadline = Date.now() + 55 * 60 * 1000;
      /** If API never marks the job failed, stop spinning when MySQL updated_at stops moving.
       * Large imports: after the last list page, parse + draft commit can take many minutes without a new "ticket N" line. */
      const STUCK_RUNNING_MS = 12 * 60 * 1000;
      let lastUpdatedAt = null;
      let runningQuietSince = null;

      while (Date.now() < deadline) {
        const st = await getRinseImportUploadBatchJob(jobId);
        const row = st.data || {};
        const status = row.status;
        const note = row.progress_note || status || "…";
        setRinseImportProgressNote(String(row.progress_note || ""));
        const updatedAt = row.updated_at != null ? String(row.updated_at) : "";
        const outLog = row.stdout_tail != null ? String(row.stdout_tail) : "";
        const errLog = row.stderr_tail != null ? String(row.stderr_tail).trim() : "";
        let combined = errLog ? `${outLog}\n--- stderr ---\n${errLog}` : outLog;
        if (!combined.trim() && (status === "running" || status === "queued")) {
          combined =
            (note && String(note).trim()) ||
            "Server is running Playwright; live log lines appear once rinse.com emits output (often after the browser starts).";
        }
        setPortalScrapeLog(combined);
        if (status === "running" || status === "queued") {
          const tm = String(note).match(/\bticket\s+(\d+)/i);
          let short = "Rinse • working…";
          if (tm) short = `Rinse • ticket ${tm[1]}`;
          else if (/\[prep\]/i.test(String(note))) short = "Rinse • preparing…";
          else if (status === "queued") short = "Rinse • queued…";
          setMessage({ type: "info", text: short });
        }

        if (status === "running") {
          if (updatedAt !== lastUpdatedAt) {
            lastUpdatedAt = updatedAt;
            runningQuietSince = Date.now();
          } else if (runningQuietSince != null && Date.now() - runningQuietSince > STUCK_RUNNING_MS) {
            setMessage({ type: "error", text: "Rinse • stuck (no API updates)" });
            return;
          }
        } else {
          lastUpdatedAt = null;
          runningQuietSince = null;
        }

        if (status === "cancelled") {
          setMessage({
            type: "info",
            text: row.message || row.progress_note || "Rinse import was stopped. No new rows were committed after the stop point.",
          });
          return;
        }

        if (status === "succeeded") {
          const d = row.result || {};
          setMessage({
            type: "success",
            text: `Rinse import complete. Accepted: ${d.rows_inserted ?? 0}, Rejected: ${d.rejected_rows ?? 0}, Needs attention: ${d.needs_attention_rows ?? 0}.`,
          });
          await loadCurrentBatch("ALL");
          await loadBatchHistory();
          const cfg = await getRinseBagExportConfig();
          setRinseExportHint(cfg.data?.hint || "");
          return;
        }

        if (status === "failed") {
          let text =
            row.error ||
            row.stderr_tail ||
            row.stdout_tail ||
            "Rinse import failed (see Azure Log stream for details).";
          if (typeof text === "string" && text.length > 1200) {
            text = `${text.slice(0, 1200)}…`;
          }
          setMessage({ type: "error", text });
          return;
        }

        /* Queued: pick up "running" quickly. Running: poll slower to halve OPTIONS+XHR load on the API. */
        const pollMs = status === "queued" ? 1200 : status === "running" ? 4500 : 2000;
        await sleep(pollMs);
      }

      setMessage({ type: "error", text: "Rinse • wait timeout (55m)" });
    } catch (error) {
      console.error(error);
      const d = error?.response?.data;
      let text =
        d?.error ||
        d?.message ||
        error?.message ||
        "Rinse import failed.";
      if (
        error?.response?.status === 503 &&
        d &&
        Object.prototype.hasOwnProperty.call(d, "rinse_export_env_key_present")
      ) {
        if (d.rinse_export_env_key_present === false) {
          text =
            "Rinse import is off: the running API workers do not see RINSE_BAG_EXPORT_ENABLED. On this API App Service, set the app setting to 1, Save, then Restart (gunicorn must reload; SSH printenv alone does not update workers).";
        } else if (Number(d.rinse_export_env_value_len) === 0) {
          text =
            "Rinse import is off: the flag is empty in the API environment. Set Value to 1, Save, then Restart.";
        } else {
          text =
            "Rinse import is off: the value is not treated as on. Use 1 (no quotes), Save, then Restart.";
        }
      }
      const msg = String(error?.message || "");
      const code = error?.code;
      if (!error?.response && (code === "ECONNABORTED" || code === "ERR_CANCELED" || /network error|canceled/i.test(msg))) {
        text =
          "A request to the API timed out or was canceled while the import was running. " +
          "Often this is the parallel “current batch” call (nav badge) when the server is busy — the Rinse job may still be running. " +
          "Refresh this page in a minute and check Azure Log stream; if you saw HTTP 202 with a job id, the scrape can finish without this tab staying open.";
      }
      setMessage({ type: "error", text });
    } finally {
      setRinseImportJobId(null);
      setRinseImportProgressNote("");
      setRinseExportLoading(false);
    }
  };

  const stopRinsePortalImport = async () => {
    const jid = rinseImportJobId;
    if (!jid || rinseImportStopBusy) return;
    try {
      setRinseImportStopBusy(true);
      const res = await cancelRinseImportUploadBatchJob(jid);
      const already = res?.data?.already;
      setMessage({
        type: "info",
        text: already ? "Rinse • stop already sent" : "Rinse • stopping…",
      });
    } catch (error) {
      console.error(error);
      const st = error?.response?.status;
      const d = error?.response?.data;
      const msg =
        st === 409
          ? "Stop: job already finished."
          : d?.error || error?.message || "Stop request failed (check network / login).";
      setMessage({ type: "error", text: msg });
    } finally {
      setRinseImportStopBusy(false);
    }
  };

  const handleDeleteBatch = async (batchId) => {
    const ok = window.confirm(
      `Delete batch #${batchId}? This removes the batch and will also clean matching staging/final/checkout/processing records.`
    );
    if (!ok) return;

    try {
      setLoading(true);
      const res = await deleteUploadBatch(batchId, true);
      if (batch?.id === batchId) {
        setBatch(null);
        setRows([]);
      }
      const c = res?.data?.cascade_deleted || {};
      setMessage({
        type: "success",
        text: `Batch #${batchId} deleted. Cleared staging:${c.orders_staging || 0}, final:${c.orders_final || 0}, checkout:${c.checkout_log || 0}, processing:${c.order_processing || 0}.`,
      });
      await loadCurrentBatch("ALL");
      await loadBatchHistory();
      window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"));
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Batch delete failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box className="page">
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography sx={{ fontSize: 28, fontWeight: 500 }}>Upload Orders</Typography>
        <Button
          variant="text"
          size="small"
          startIcon={<Refresh />}
          onClick={() => {
            loadCurrentBatch("ALL");
            loadBatchHistory();
          }}
          disabled={loading || loadingRows}
        >
          Refresh
        </Button>
      </Stack>

      <Paper sx={{ mt: 1, p: 1.25, borderRadius: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} flexWrap="wrap">
          <TextField
            type="date"
            size="small"
            label="Batch date"
            InputLabelProps={{ shrink: true }}
            value={batchDate}
            onChange={(e) => setBatchDate(e.target.value)}
            sx={{ width: { xs: "100%", sm: 170 } }}
          />
          {canRunPortalScrape && (
            <>
              <TextField
                type="number"
                size="small"
                label="Rinse page start"
                placeholder="optional"
                inputProps={{ min: 1, max: 500 }}
                value={rinseImportPageStart}
                onChange={(e) => setRinseImportPageStart(e.target.value)}
                sx={{ width: { xs: "100%", sm: 130 } }}
                title="First Rinse list page for this job only. Blank = from env default (usually 1)."
              />
              <TextField
                type="number"
                size="small"
                label="Max pages"
                placeholder="optional"
                inputProps={{ min: 1, max: 500 }}
                value={rinseImportMaxPages}
                onChange={(e) => setRinseImportMaxPages(e.target.value)}
                sx={{ width: { xs: "100%", sm: 120 } }}
                disabled={rinseImportSequential}
                title={
                  rinseImportSequential
                    ? "Not used in sequential mode (use pages/chunk and max chunks instead)."
                    : "How many list pages in one browser run. Blank = Azure/env default."
                }
              />
              <FormControlLabel
                sx={{ ml: 0, mr: 0 }}
                control={
                  <Checkbox
                    size="small"
                    checked={rinseImportSequential}
                    onChange={(e) => setRinseImportSequential(e.target.checked)}
                  />
                }
                label="Sequential pages"
                title="Run list pages one chunk after another (same job), merge, then one draft save. ~25 orders per list page; easier on small Azure SKUs than one huge scrape."
              />
              <TextField
                type="number"
                size="small"
                label="Pages/chunk"
                inputProps={{ min: 1, max: 50 }}
                value={rinseImportSeqChunkPages}
                onChange={(e) => setRinseImportSeqChunkPages(e.target.value)}
                sx={{ width: { xs: "100%", sm: 100 } }}
                disabled={!rinseImportSequential}
                title="List pages per browser run. Use 1 to match one Rinse page (~25 orders) per subprocess."
              />
              <TextField
                type="number"
                size="small"
                label="Max chunks"
                placeholder="opt"
                inputProps={{ min: 1, max: 500 }}
                value={rinseImportMaxSeqChunks}
                onChange={(e) => setRinseImportMaxSeqChunks(e.target.value)}
                sx={{ width: { xs: "100%", sm: 110 } }}
                disabled={!rinseImportSequential}
                title="Cap subprocess count (default 500). Omit to walk until an empty page."
              />
              <Button
                variant="contained"
                onClick={runRinseImportToBatch}
                disabled={rinseExportLoading || loading}
                title={rinseExportHint || undefined}
              >
                {rinseExportLoading && rinseImportJobId ? "Running…" : "Scrape Rinse → draft"}
              </Button>
              <Button
                type="button"
                variant="outlined"
                size="small"
                color="warning"
                onClick={(e) => {
                  e.preventDefault();
                  stopRinsePortalImport();
                }}
                disabled={
                  !rinseImportJobId || !rinseExportLoading || rinseImportStopBusy
                }
              >
                {rinseImportStopBusy ? "…" : "Stop"}
              </Button>
              {rinseExportLoading && rinseImportJobId ? (
                <Chip
                  size="small"
                  color="primary"
                  variant="outlined"
                  label={rinseImportTicketNo != null ? `Ticket ${rinseImportTicketNo}` : "…"}
                />
              ) : null}
            </>
          )}
        </Stack>
      </Paper>

      {batch && (
        <Stack direction="row" spacing={1} sx={{ mt: 0.8, flexWrap: "wrap" }}>
          <Chip
            label={formatBatchLabel(batch)}
            color="primary"
            variant="outlined"
          />
          <Chip
            label={(batch.state || "DRAFT").toUpperCase()}
            color={isConfirmed ? "success" : "warning"}
          />
        </Stack>
      )}

      {(message.text || (isDraft && !rinseExportLoading)) && (
        <Alert
          severity={message.type === "error" ? "error" : message.type === "warning" ? "warning" : "success"}
          sx={{ mt: 1, borderRadius: 2, py: 0.5 }}
        >
          {message.text ||
            (isDraft && !rinseExportLoading ? "Draft — confirm batch when ready." : "Ready.")}
        </Alert>
      )}

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 1 }}>Excel</Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 500, fontSize: 14 }}>Workbook</Typography>
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </Stack>

          <Button variant="contained" onClick={uploadFile} disabled={loading}>
            {loading ? "Uploading..." : "Upload draft"}
          </Button>

          <Button variant="outlined" onClick={() => loadCurrentBatch(rowStatusFilter)} disabled={loading || loadingRows}>
            Refresh staging
          </Button>
        </Stack>
      </Paper>

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 1 }}>Rinse / CSV</Typography>
        {canRunPortalScrape && rinseExportLoading && rinseImportJobId ? (
          <Button
            size="small"
            variant="text"
            onClick={() => setShowFullPortalScrapeLog((v) => !v)}
            sx={{ mb: 1, textTransform: "none" }}
          >
            {showFullPortalScrapeLog ? "Hide log" : "Log"}
          </Button>
        ) : null}
        {showFullPortalScrapeLog && (
          <Box
            ref={portalLogRef}
            sx={{
              maxHeight: 280,
              overflow: "auto",
              p: 1,
              borderRadius: 1,
              bgcolor: "grey.900",
              color: "grey.100",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: 11,
              lineHeight: 1.4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              mb: 1.5,
            }}
          >
            {portalScrapeLog || (rinseExportLoading ? "…" : "")}
          </Box>
        )}

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 500, fontSize: 13 }}>CSV file</Typography>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setPortalCsvFile(e.target.files?.[0] || null)}
            />
          </Stack>
          <Button variant="contained" color="secondary" onClick={uploadPortalCsv} disabled={loading}>
            {loading ? "…" : "Upload CSV"}
          </Button>
        </Stack>
      </Paper>

      {isRinseExportAdmin && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontWeight: 600, fontSize: 14, mb: 1 }}>Rinse export (admin)</Typography>
          <Button variant="outlined" size="small" onClick={runRinseBagExport} disabled={rinseExportLoading || loading}>
            {rinseExportLoading ? "…" : "Download CSV"}
          </Button>
        </Paper>
      )}

      <Paper sx={{ mt: 1.2, borderRadius: 2, overflow: "hidden" }}>
        <Tabs
          value={viewTab}
          onChange={(_, next) => setViewTab(next)}
          variant="fullWidth"
        >
          <Tab value="REVIEW" label="Draft Review" />
          <Tab value="BATCHES" label="Uploaded Batches" />
        </Tabs>
      </Paper>

      {batch && viewTab === "REVIEW" && (
        <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} justifyContent="space-between" alignItems={{ md: "center" }}>
            <Box>
              <Typography sx={{ fontSize: 20, fontWeight: 500 }}>{formatBatchLabel(batch)}</Typography>
              <Typography color="text.secondary">
                Date {formatCalendarDateLabel(batch.batch_date)} • State {batch.state || "DRAFT"}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1}>
              <Button variant="outlined" onClick={() => setAddOpen(true)} disabled={isConfirmed || loading}>
                Add Row
              </Button>
              <Button variant="contained" onClick={handleConfirm} disabled={isConfirmed || loading}>
                {isConfirmed ? "Confirmed" : "Confirm Batch"}
              </Button>
            </Stack>
          </Stack>

          <Stack direction="row" spacing={1} sx={{ mt: 1.2, flexWrap: "wrap" }}>
            <Chip label={`Accepted ${rowSummary.ACCEPTED + rowSummary.OVERRIDDEN}`} color="success" />
            <Chip label={`Needs Attention ${rowSummary.NEEDS_ATTENTION}`} color="warning" />
            <Chip label={`Rejected ${rowSummary.REJECTED_DUPLICATE}`} color="error" />
            <Chip label={`Deleted ${rowSummary.DELETED}`} variant="outlined" />
          </Stack>

          <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
            {["ALL", "ACCEPTED", "OVERRIDDEN", "NEEDS_ATTENTION", "REJECTED_DUPLICATE", "DELETED"].map((x) => (
              <Chip
                key={x}
                label={x}
                clickable
                color={rowStatusFilter === x ? "primary" : "default"}
                onClick={() => onFilterChange(x)}
              />
            ))}
          </Stack>

          {loadingRows ? (
            <Stack alignItems="center" sx={{ py: 2 }}>
              <CircularProgress size={24} />
            </Stack>
          ) : (
            <Table size="small" sx={{ mt: 1 }}>
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Date</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Weight/Count</TableCell>
                  <TableCell>Bag ID</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell>Rush</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Reason</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredRows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{row.id}</TableCell>
                    <TableCell>{formatCalendarDateLabel(row.date_clean)}</TableCell>
                    <TableCell>{row.name_clean}</TableCell>
                    <TableCell>
                      {String(row.service_type || "").toUpperCase() === "HD"
                        ? `${Math.round(Number(row.weight_num || 0))} pcs`
                        : row.weight_num == null
                          ? "-"
                          : `${Number(row.weight_num).toFixed(2)} lb`}
                    </TableCell>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: 13 }}>
                      {row.ticket_id ? String(row.ticket_id) : "—"}
                    </TableCell>
                    <TableCell>{row.service_type}</TableCell>
                    <TableCell>{row.rush_type}</TableCell>
                    <TableCell>{row.row_status}</TableCell>
                    <TableCell>{row.reason || "-"}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.6}>
                        <Button size="small" variant="outlined" onClick={() => openEdit(row)} disabled={isConfirmed}>
                          Edit
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          onClick={() => handleDelete(row.id)}
                          disabled={isConfirmed}
                        >
                          Delete
                        </Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {isConfirmed && batch?.batch_date && (
            <StagingOrderManagementTable
              batchDate={batch.batch_date}
              user={user}
              onOrdersChanged={() => window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"))}
            />
          )}
        </Paper>
      )}

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Edit Batch Row</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.6 }}>
            <TextField
              label="Date"
              type="date"
              value={editForm.date_clean}
              onChange={(e) => setEditForm((p) => ({ ...p, date_clean: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Name"
              value={editForm.name_clean}
              onChange={(e) => setEditForm((p) => ({ ...p, name_clean: e.target.value }))}
            />
            <TextField
              label="Weight / Count"
              type="number"
              value={editForm.weight_num}
              onChange={(e) => setEditForm((p) => ({ ...p, weight_num: e.target.value }))}
            />
            <TextField
              select
              label="Service"
              value={editForm.service_type}
              onChange={(e) => setEditForm((p) => ({ ...p, service_type: e.target.value }))}
            >
              <MenuItem value="WF">WF</MenuItem>
              <MenuItem value="HD">HD</MenuItem>
            </TextField>
            <TextField
              select
              label="Rush"
              value={editForm.rush_type}
              onChange={(e) => setEditForm((p) => ({ ...p, rush_type: e.target.value }))}
            >
              <MenuItem value="RUSH">RUSH</MenuItem>
              <MenuItem value="NON-RUSH">NON-RUSH</MenuItem>
            </TextField>
            <TextField
              select
              label="Row Status"
              value={editForm.row_status}
              onChange={(e) => setEditForm((p) => ({ ...p, row_status: e.target.value }))}
            >
              <MenuItem value="ACCEPTED">ACCEPTED</MenuItem>
              <MenuItem value="OVERRIDDEN">OVERRIDDEN</MenuItem>
              <MenuItem value="NEEDS_ATTENTION">NEEDS_ATTENTION</MenuItem>
              <MenuItem value="REJECTED_DUPLICATE">REJECTED_DUPLICATE</MenuItem>
              <MenuItem value="DELETED">DELETED</MenuItem>
            </TextField>
            <TextField
              label="Reason"
              value={editForm.reason}
              onChange={(e) => setEditForm((p) => ({ ...p, reason: e.target.value }))}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveEdit} disabled={loading}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add New Batch Row</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.6 }}>
            <TextField
              label="Date"
              type="date"
              value={addForm.date_clean}
              onChange={(e) => setAddForm((p) => ({ ...p, date_clean: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Name"
              value={addForm.name_clean}
              onChange={(e) => setAddForm((p) => ({ ...p, name_clean: e.target.value }))}
            />
            <TextField
              label="Weight / Count"
              type="number"
              value={addForm.weight_num}
              onChange={(e) => setAddForm((p) => ({ ...p, weight_num: e.target.value }))}
            />
            <TextField
              select
              label="Service"
              value={addForm.service_type}
              onChange={(e) => setAddForm((p) => ({ ...p, service_type: e.target.value }))}
            >
              <MenuItem value="WF">WF</MenuItem>
              <MenuItem value="HD">HD</MenuItem>
            </TextField>
            <TextField
              select
              label="Rush"
              value={addForm.rush_type}
              onChange={(e) => setAddForm((p) => ({ ...p, rush_type: e.target.value }))}
            >
              <MenuItem value="RUSH">RUSH</MenuItem>
              <MenuItem value="NON-RUSH">NON-RUSH</MenuItem>
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleAdd} disabled={loading}>Add</Button>
        </DialogActions>
      </Dialog>

      {viewTab === "BATCHES" && (
      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Typography sx={{ fontSize: 18, fontWeight: 500, mb: 1 }}>Uploaded Batches</Typography>
        <Stack spacing={0.8}>
          {batches.length === 0 ? (
            <Typography color="text.secondary">No batches yet.</Typography>
          ) : (
            batches.map((b) => (
              <Stack
                key={b.id}
                direction="row"
                spacing={1}
                alignItems="center"
                justifyContent="space-between"
                sx={{ border: "1px solid #e5e7eb", borderRadius: 1.5, p: 1 }}
              >
                <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap" }}>
                  <Typography sx={{ fontWeight: 500 }}>{formatBatchLabel(b)}</Typography>
                  <Chip
                    size="small"
                    label={(b.state || "DRAFT").toUpperCase()}
                    color={String(b.state || "").toUpperCase() === "CONFIRMED" ? "success" : "warning"}
                  />
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography color="text.secondary">
                    Loaded {b.orders_loaded || 0}
                  </Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={async () => {
                      setBatch(b);
                      await loadRows(b.id, "ALL");
                      setRowStatusFilter("ALL");
                      setViewTab("REVIEW");
                    }}
                  >
                    View
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    onClick={() => handleDeleteBatch(b.id)}
                    disabled={loading}
                  >
                    Delete
                  </Button>
                </Stack>
              </Stack>
            ))
          )}
        </Stack>
      </Paper>
      )}
    </Box>
  );
}

export default UploadPage;
