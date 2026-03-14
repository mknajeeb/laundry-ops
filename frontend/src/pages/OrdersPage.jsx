import { useEffect, useMemo, useState, useDeferredValue } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Bolt, CheckCircle, DeleteOutline, ExpandLess, ExpandMore, Image, Refresh, Search, Visibility } from "@mui/icons-material";
import {
  deleteOrderTicket,
  deleteOrder,
  getOrderTicket,
  getOrderTickets,
  getOrders,
  submitProcessedOrder,
  updateOrder,
  uploadOrderTicket,
} from "../api";

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const WF_BG = "#141922";
const HD_BG = "#0a869d";

function parseAsLocalDate(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const [y, m, d] = raw.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return null;
  return new Date(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate());
}

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const out = String(reader.result || "");
      resolve(out.includes(",") ? out.split(",")[1] : out);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function inferMimeType(fileName) {
  const name = String(fileName || "").toLowerCase();
  if (name.endsWith(".png")) return "image/png";
  if (name.endsWith(".webp")) return "image/webp";
  if (name.endsWith(".gif")) return "image/gif";
  return "image/jpeg";
}

function normalizeName(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

function parseTicketText(rawText) {
  const text = String(rawText || "");
  const lower = text.toLowerCase();
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  const ticketMatch = text.match(/ticket\s*#?\s*([a-z0-9-]{5,})/i);
  const lbsMatch = text.match(/(\d+(?:\.\d+)?)\s*(?:lb|lbs)\b/i);
  const pcsMatch = text.match(/(\d+)\s*(?:pcs|pc|pieces)\b/i);

  let service = "";
  if (lower.includes("wash and fold")) service = "WF";
  if (lower.includes("hang dry")) service = "HD";
  if (!service && pcsMatch) service = "HD";
  if (!service && lbsMatch) service = "WF";

  const rush = /\brush\b/.test(lower) ? "RUSH" : "NON-RUSH";

  const badLine = /(ticket|due|rush|order|nyc|created|wash|fold|hang|dry|fabric|softener|rinse|new customer)/i;
  let name = "";
  const ncIdx = lines.findIndex((l) => /new customer/i.test(l));
  if (ncIdx >= 0) {
    for (let i = ncIdx + 1; i < lines.length; i += 1) {
      if (!badLine.test(lines[i]) && /[a-z]/i.test(lines[i])) {
        name = lines[i];
        break;
      }
    }
  }
  if (!name) {
    for (const l of lines) {
      if (badLine.test(l)) continue;
      if (/[a-z]/i.test(l) && l.length >= 4) {
        name = l;
        break;
      }
    }
  }

  return {
    ticket_id: ticketMatch ? ticketMatch[1].toUpperCase() : "",
    name_clean: name,
    service_type: service,
    rush_type: rush,
    weight_num: lbsMatch ? Number(lbsMatch[1]) : (pcsMatch ? Number(pcsMatch[1]) : null),
    raw_text: text,
  };
}

function OrdersPage({ user }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const [rushFilter, setRushFilter] = useState("ALL"); // ALL | RUSH | NON-RUSH
  const [showProcessed, setShowProcessed] = useState(false);
  const [openAlpha, setOpenAlpha] = useState("A");

  const [submitDialogRow, setSubmitDialogRow] = useState(null);
  const [submitMeasure, setSubmitMeasure] = useState("");
  const [submitTicketId, setSubmitTicketId] = useState("");
  const [submitFile, setSubmitFile] = useState(null);
  const [ticketDialogRow, setTicketDialogRow] = useState(null);
  const [ticketFile, setTicketFile] = useState(null);
  const [ticketView, setTicketView] = useState(null);
  const [ticketViewLoading, setTicketViewLoading] = useState(false);
  const [adminTicketsOpen, setAdminTicketsOpen] = useState(false);
  const [adminTicketsLoading, setAdminTicketsLoading] = useState(false);
  const [adminTickets, setAdminTickets] = useState([]);
  const [notice, setNotice] = useState("");
  const [scanOpen, setScanOpen] = useState(false);
  const [scanFile, setScanFile] = useState(null);
  const [scanBusy, setScanBusy] = useState(false);
  const [scanParsed, setScanParsed] = useState(null);
  const [scanCandidates, setScanCandidates] = useState([]);

  const [editRow, setEditRow] = useState(null);

  const roleCodes = (user?.roles || []).map((r) => String(r).toUpperCase());
  const isAdmin = roleCodes.includes("ADMIN");
  const userId = Number(user?.user_id || 0);

  const load = async () => {
    try {
      setLoading(true);
      const res = await getOrders({ include_all: true });
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      console.error(error);
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const normalizeLogistics = (r) => {
    const v = String(r?.logistics_status || "").toUpperCase();
    if (v) return v;
    const s = String(r?.status || "").toUpperCase();
    if (["CHECKED_OUT", "SENT_TO_RINSE"].includes(s)) return "SENT_TO_RINSE";
    if (["FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(s)) return "FORCE_CHECKOUT";
    return "AT_WASHPRO";
  };

  const normalizeProcessing = (r) => {
    const v = String(r?.processing_status || "").toUpperCase();
    if (v) return v;
    const s = String(r?.status || "").toUpperCase();
    return s === "PROCESSED" ? "PROCESSED" : "PENDING";
  };

  const rushOf = (r) => String(r?.rush_type || "").toUpperCase() === "RUSH" ? "RUSH" : "NON-RUSH";
  const serviceOf = (r) => String(r?.service_type || "").toUpperCase();
  const isHD = (r) => serviceOf(r) === "HD";

  const formatMeasure = (r) => {
    const n = Number(r?.weight_num ?? 0);
    return isHD(r) ? `${Math.round(n)} pcs` : `${n.toFixed(2)} lb`;
  };

  const formatDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const visibleRows = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();

    return rows.filter((r) => {
      if (normalizeLogistics(r) !== "AT_WASHPRO") return false;

      const proc = normalizeProcessing(r);
      if (showProcessed) {
        if (proc !== "PROCESSED") return false;
        if (userId && Number(r?.processed_by_user_id || 0) !== userId) return false;
      } else if (proc !== "PENDING") {
        return false;
      }

      if (rushFilter !== "ALL" && rushOf(r) !== rushFilter) return false;

      if (!q) return true;
      return (
        String(r?.name_clean || "").toLowerCase().includes(q) ||
        String(r?.id || "").includes(q) ||
        String(r?.service_type || "").toLowerCase().includes(q) ||
        String(r?.weight_num ?? "").toLowerCase().includes(q)
      );
    });
  }, [rows, deferredSearch, rushFilter, showProcessed, userId]);

  const grouped = useMemo(() => {
    const out = {};
    for (const a of ALPHAS) out[a] = [];
    for (const r of visibleRows) {
      const c = String(r?.name_clean || "").trim().charAt(0).toUpperCase();
      const k = /^[A-Z]$/.test(c) ? c : "A";
      out[k].push(r);
    }
    return out;
  }, [visibleRows]);

  const counts = useMemo(() => {
    const base = rows.filter((r) => normalizeLogistics(r) === "AT_WASHPRO");
    const pending = base.filter((r) => normalizeProcessing(r) === "PENDING");
    const mine = base.filter(
      (r) => normalizeProcessing(r) === "PROCESSED" && (!userId || Number(r?.processed_by_user_id || 0) === userId)
    );
    return {
      all: showProcessed ? mine.length : pending.length,
      rush: (showProcessed ? mine : pending).filter((r) => rushOf(r) === "RUSH").length,
      nonRush: (showProcessed ? mine : pending).filter((r) => rushOf(r) === "NON-RUSH").length,
    };
  }, [rows, showProcessed, userId]);

  const toggleAlpha = (alpha) => setOpenAlpha((prev) => (prev === alpha ? null : alpha));

  useEffect(() => {
    const q = deferredSearch.trim();
    if (!q || visibleRows.length === 0) return;
    const first = visibleRows[0];
    const c = String(first?.name_clean || "").trim().charAt(0).toUpperCase();
    const alpha = /^[A-Z]$/.test(c) ? c : "A";
    setOpenAlpha(alpha);
  }, [deferredSearch, visibleRows]);

  const onSubmitOrder = async () => {
    if (!submitDialogRow) return;
    try {
      setSaving(true);
      const measureNum = Number(submitMeasure);
      if (!Number.isFinite(measureNum) || measureNum < 0) {
        setNotice("Enter valid weight/count.");
        return;
      }
      await updateOrder(submitDialogRow.id, { weight_num: measureNum });
      const payload = {};
      payload.weight_num = measureNum;
      if (submitTicketId) payload.ticket_id = submitTicketId;
      if (submitFile) {
        payload.ticket_image_base64 = await fileToBase64(submitFile);
        payload.ticket_file_name = submitFile.name;
      }
      await submitProcessedOrder(submitDialogRow.id, payload);
      setSubmitDialogRow(null);
      setSubmitMeasure("");
      setSubmitTicketId("");
      setSubmitFile(null);
      await load();
    } catch (error) {
      console.error(error);
      setNotice("Failed to submit.");
    } finally {
      setSaving(false);
    }
  };

  const onRunScan = async () => {
    if (!scanFile) return;
    try {
      setScanBusy(true);
      const { createWorker } = await import("tesseract.js");
      const worker = await createWorker("eng");
      const out = await worker.recognize(scanFile);
      await worker.terminate();
      const parsed = parseTicketText(out?.data?.text || "");
      setScanParsed(parsed);

      const base = rows.filter((r) => normalizeLogistics(r) === "AT_WASHPRO" && normalizeProcessing(r) === "PENDING");
      const pn = normalizeName(parsed.name_clean);
      const candidates = base
        .map((r) => {
          let score = 0;
          const rn = normalizeName(r.name_clean);
          if (parsed.ticket_id && String(r.ticket_id || "").toUpperCase() === parsed.ticket_id) score += 100;
          if (pn && rn) {
            if (rn === pn) score += 70;
            else if (rn.includes(pn) || pn.includes(rn)) score += 40;
          }
          if (parsed.service_type && String(r.service_type || "").toUpperCase() === parsed.service_type) score += 15;
          if (parsed.rush_type && String(r.rush_type || "").toUpperCase() === parsed.rush_type) score += 10;
          if (parsed.weight_num !== null && parsed.weight_num !== undefined) {
            const rw = Number(r.weight_num || 0);
            if (String(r.service_type || "").toUpperCase() === "HD") {
              if (Math.round(rw) === Math.round(Number(parsed.weight_num))) score += 25;
            } else {
              const diff = Math.abs(rw - Number(parsed.weight_num));
              if (diff <= 0.15) score += 25;
              else if (diff <= 0.5) score += 10;
            }
          }
          return { row: r, score };
        })
        .filter((x) => x.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 5);

      setScanCandidates(candidates);
    } catch (error) {
      console.error(error);
      setNotice("Scan failed.");
    } finally {
      setScanBusy(false);
    }
  };

  const pickScanCandidate = (candidate) => {
    const r = candidate.row;
    const c = String(r?.name_clean || "").trim().charAt(0).toUpperCase();
    const alpha = /^[A-Z]$/.test(c) ? c : "A";
    setSearch(r.name_clean || "");
    setOpenAlpha(alpha);
    setSubmitDialogRow(r);
    setSubmitMeasure(
      scanParsed?.weight_num !== null && scanParsed?.weight_num !== undefined
        ? String(scanParsed.weight_num)
        : String(r.weight_num ?? "")
    );
    setSubmitTicketId(scanParsed?.ticket_id || String(r.ticket_id || ""));
    setScanOpen(false);
    setScanFile(null);
  };

  const onAddTicket = async () => {
    if (!ticketDialogRow || !ticketFile) return;
    try {
      setSaving(true);
      await uploadOrderTicket(ticketDialogRow.id, {
        ticket_image_base64: await fileToBase64(ticketFile),
        ticket_file_name: ticketFile.name,
      });
      setTicketDialogRow(null);
      setTicketFile(null);
      await load();
    } catch (error) {
      console.error(error);
      setNotice("Ticket upload failed.");
    } finally {
      setSaving(false);
    }
  };

  const onViewTicket = async (row) => {
    if (!row?.id) return;
    try {
      setTicketViewLoading(true);
      const res = await getOrderTicket(row.id);
      const data = res?.data || {};
      if (!data?.ticket_image_base64 && !data?.ticket_image_url) {
        setNotice("No ticket image found.");
        return;
      }
      setTicketView({
        order_id: row.id,
        name_clean: row.name_clean,
        ticket_file_name: data.ticket_file_name,
        src: data.ticket_image_url || `data:${inferMimeType(data.ticket_file_name)};base64,${data.ticket_image_base64}`,
      });
    } catch (error) {
      console.error(error);
      setNotice("Failed to load ticket image.");
    } finally {
      setTicketViewLoading(false);
    }
  };

  const onDeleteTicket = async (row) => {
    if (!row?.id) return;
    if (!window.confirm(`Delete ticket image for ${row.name_clean}?`)) return;
    try {
      setSaving(true);
      await deleteOrderTicket(row.id);
      await load();
    } catch (error) {
      console.error(error);
      setNotice("Failed to delete ticket image.");
    } finally {
      setSaving(false);
    }
  };

  const openAdminTickets = async () => {
    try {
      setAdminTicketsOpen(true);
      setAdminTicketsLoading(true);
      const res = await getOrderTickets({ limit: 500 });
      setAdminTickets(Array.isArray(res?.data) ? res.data : []);
    } catch (error) {
      console.error(error);
      setNotice("Failed to load all ticket images.");
      setAdminTickets([]);
    } finally {
      setAdminTicketsLoading(false);
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#ffffff", px: { xs: 1, sm: 1.5 }, py: 1 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 30, fontWeight: 400 }}>Orders</Typography>
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant={showProcessed ? "contained" : "outlined"}
            onClick={() => setShowProcessed((prev) => !prev)}
            sx={{ textTransform: "none", fontWeight: 400 }}
          >
            Processed
          </Button>
          {!showProcessed && (
            <Button size="small" variant="text" startIcon={<Image />} onClick={() => setScanOpen(true)} sx={{ textTransform: "none", fontWeight: 400 }}>
              Scan
            </Button>
          )}
          <Button size="small" variant="text" onClick={load} sx={{ minWidth: 34 }}>
            <Refresh />
          </Button>
          {showProcessed && isAdmin && (
            <Button size="small" variant="text" startIcon={<Image />} onClick={openAdminTickets} sx={{ textTransform: "none", fontWeight: 400 }}>
              All Pictures
            </Button>
          )}
        </Stack>
      </Stack>

      <Stack direction="row" justifyContent="flex-end" sx={{ mt: 0.2 }}>
        <Box sx={{ textAlign: "right" }}>
          <Button size="small" variant="outlined" sx={{ textTransform: "none", fontWeight: 400, pointerEvents: "none" }}>
            Folded by
          </Button>
          <Typography sx={{ fontSize: 13, color: "#6b7280", mt: 0.2 }}>
            {user?.display_name || user?.username || "Unknown"}
          </Typography>
        </Box>
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mt: 1, overflowX: "auto", pb: 0.2 }}>
        <Button
          onClick={() => setRushFilter("ALL")}
          sx={{
            textTransform: "none",
            borderRadius: 2,
            px: 1.2,
            py: 0.6,
            fontWeight: 400,
            bgcolor: rushFilter === "ALL" ? "#0f172a" : "#eef2f7",
            color: rushFilter === "ALL" ? "#ffffff" : "#111827",
          }}
        >
          All {counts.all}
        </Button>
        <Button
          onClick={() => setRushFilter("RUSH")}
          sx={{
            textTransform: "none",
            borderRadius: 2,
            px: 1.2,
            py: 0.6,
            fontWeight: 400,
            bgcolor: rushFilter === "RUSH" ? "#b91c1c" : "#eef2f7",
            color: rushFilter === "RUSH" ? "#ffffff" : "#111827",
          }}
          startIcon={<Bolt sx={{ fontSize: 18 }} />}
        >
          Rush {counts.rush}
        </Button>
        <Button
          onClick={() => setRushFilter("NON-RUSH")}
          sx={{
            textTransform: "none",
            borderRadius: 2,
            px: 1.2,
            py: 0.6,
            fontWeight: 400,
            bgcolor: rushFilter === "NON-RUSH" ? "#0f766e" : "#eef2f7",
            color: rushFilter === "NON-RUSH" ? "#ffffff" : "#111827",
          }}
          startIcon={<CheckCircle sx={{ fontSize: 16 }} />}
        >
          Non-Rush {counts.nonRush}
        </Button>
      </Stack>

      <Paper sx={{ mt: 1.1, p: 1.1, borderRadius: 2, border: "1px solid #e5e7eb" }}>
        <TextField
          fullWidth
          size="small"
          placeholder="Search name, type, weight/count"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search fontSize="small" />
              </InputAdornment>
            ),
            endAdornment: (
              <InputAdornment position="end">
                <Button
                  size="small"
                  onClick={() => setSearch("")}
                  sx={{ textTransform: "none", minWidth: 48, fontWeight: 400 }}
                >
                  Clear
                </Button>
              </InputAdornment>
            ),
          }}
        />
      </Paper>

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.1}>
          <CircularProgress size={26} />
          <Typography color="text.secondary">Loading...</Typography>
        </Stack>
      ) : (
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {ALPHAS.map((alpha) => {
            const list = grouped[alpha] || [];
            const expanded = openAlpha === alpha;
            return (
              <Paper
                key={alpha}
                sx={{
                  borderRadius: 2,
                  border: "1px solid #e5e7eb",
                  overflow: "hidden",
                  opacity: list.length === 0 ? 0.36 : 1,
                }}
              >
                <Button
                  fullWidth
                  onClick={() => toggleAlpha(alpha)}
                  sx={{
                    px: 1.1,
                    py: 1,
                    justifyContent: "space-between",
                    textTransform: "none",
                    color: "#111827",
                    bgcolor: "#f8fafc",
                  }}
                >
                  <Stack direction="row" spacing={1.2} alignItems="center">
                    <Box
                      sx={{
                        width: 28,
                        height: 28,
                        borderRadius: "50%",
                        display: "grid",
                        placeItems: "center",
                        bgcolor: "#111827",
                        color: "#ffffff",
                        fontSize: 14,
                        fontWeight: 400,
                      }}
                    >
                      {alpha}
                    </Box>
                    <Typography sx={{ fontSize: 16, fontWeight: 400 }}>{list.length} bags</Typography>
                  </Stack>
                  {expanded ? <ExpandLess /> : <ExpandMore />}
                </Button>

                {expanded && (
                  <Box sx={{ p: 1 }}>
                    {list.length === 0 ? (
                      <Typography sx={{ color: "#6b7280", fontSize: 14 }}>No orders.</Typography>
                    ) : (
                      <Stack spacing={1}>
                        {list.map((r) => {
                          const rush = rushOf(r) === "RUSH";
                          const hd = isHD(r);
                          const pending = normalizeProcessing(r) === "PENDING";
                          return (
                            <Paper
                              key={r.id}
                              sx={{
                                p: 1.2,
                                borderRadius: 2,
                                bgcolor: hd ? HD_BG : WF_BG,
                                color: "#ffffff",
                                border: hd ? "1px solid #44c3d6" : "1px solid #2b3342",
                              }}
                            >
                              <Stack spacing={0.9}>
                                <Stack direction="row" justifyContent="space-between" alignItems="center">
                                  <Stack direction="row" spacing={0.7} alignItems="center">
                                    {rush ? <Bolt sx={{ fontSize: 20, color: "#ffcb5b" }} /> : <CheckCircle sx={{ fontSize: 17, color: "#d1fae5" }} />}
                                    <Typography sx={{ fontSize: 13, letterSpacing: 0.5, opacity: 0.9, fontWeight: 400 }}>
                                      {rush ? "RUSH" : "NON-RUSH"}
                                    </Typography>
                                  </Stack>
                                  <Typography sx={{ fontSize: 13, opacity: 0.85, fontWeight: 400 }}>
                                    {pending ? "Pending" : "Processed"}
                                  </Typography>
                                </Stack>

                                <Typography sx={{ fontSize: 38 > String(r?.name_clean || "").length ? 20 : 18, lineHeight: 1.15, fontWeight: 400 }}>
                                  {r.name_clean}
                                </Typography>

                                <Typography sx={{ fontSize: 16, opacity: 0.92, fontWeight: 400 }}>
                                  {formatDate(r.date_clean)} • {formatMeasure(r)}
                                </Typography>

                                <Box sx={{ pt: 0.45 }}>
                                  {showProcessed ? (
                                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                      {Number(r?.has_ticket_image || 0) > 0 && (
                                        <Button
                                          size="small"
                                          variant="outlined"
                                          startIcon={<Visibility />}
                                          onClick={() => onViewTicket(r)}
                                          sx={{ textTransform: "none", borderColor: "#ffffff", color: "#ffffff", fontWeight: 400 }}
                                        >
                                          View picture
                                        </Button>
                                      )}
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        startIcon={<Image />}
                                        onClick={() => setTicketDialogRow(r)}
                                        sx={{ textTransform: "none", borderColor: "#ffffff", color: "#ffffff", fontWeight: 400 }}
                                      >
                                        {Number(r?.has_ticket_image || 0) > 0 ? "Replace picture" : "Add picture"}
                                      </Button>
                                      {Number(r?.has_ticket_image || 0) > 0 && (
                                        <Button
                                          size="small"
                                          variant="outlined"
                                          color="error"
                                          startIcon={<DeleteOutline />}
                                          onClick={() => onDeleteTicket(r)}
                                          sx={{ textTransform: "none", fontWeight: 400 }}
                                        >
                                          Delete picture
                                        </Button>
                                      )}
                                    </Stack>
                                  ) : (
                                    <Button
                                      size="small"
                                      variant="contained"
                                      onClick={() => {
                                        setSubmitDialogRow(r);
                                        setSubmitMeasure(String(r.weight_num ?? ""));
                                        setSubmitTicketId(String(r.ticket_id || ""));
                                      }}
                                      sx={{ textTransform: "none", bgcolor: "#ffffff", color: "#111827", fontWeight: 400 }}
                                    >
                                      Submit
                                    </Button>
                                  )}
                                </Box>

                                {isAdmin && (
                                  <>
                                    <Divider sx={{ borderColor: "rgba(255,255,255,0.2)" }} />
                                    <Stack direction="row" spacing={1}>
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        onClick={() =>
                                          setEditRow({
                                            id: r.id,
                                            date_clean: String(r.date_clean || "").slice(0, 10),
                                            name_clean: r.name_clean || "",
                                            weight_num: r.weight_num ?? "",
                                            service_type: r.service_type || "WF",
                                          })
                                        }
                                        sx={{ textTransform: "none", borderColor: "#ffffff", color: "#ffffff", fontWeight: 400 }}
                                      >
                                        Edit
                                      </Button>
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        color="error"
                                        onClick={async () => {
                                          if (!window.confirm(`Delete #${r.id}?`)) return;
                                          await deleteOrder(r.id);
                                          await load();
                                        }}
                                        sx={{ textTransform: "none", fontWeight: 400 }}
                                      >
                                        Delete
                                      </Button>
                                    </Stack>
                                  </>
                                )}
                              </Stack>
                            </Paper>
                          );
                        })}
                      </Stack>
                    )}
                  </Box>
                )}
              </Paper>
            );
          })}
        </Stack>
      )}

      <Dialog open={Boolean(submitDialogRow)} onClose={() => setSubmitDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 400 }}>Submit</DialogTitle>
        <DialogContent dividers>
          {submitDialogRow && (
            <Stack spacing={1.1}>
              <TextField
                label={String(submitDialogRow.service_type || "").toUpperCase() === "HD" ? "Count" : "Weight"}
                type="number"
                value={submitMeasure}
                onChange={(e) => setSubmitMeasure(e.target.value)}
              />
              <Button variant="outlined" component="label" sx={{ textTransform: "none", fontWeight: 400 }}>
                {submitFile ? submitFile.name : "Upload Ticket"}
                <input
                  hidden
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={(e) => setSubmitFile(e.target.files?.[0] || null)}
                />
              </Button>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSubmitDialogRow(null)} sx={{ fontWeight: 400 }}>Cancel</Button>
          <Button variant="contained" onClick={onSubmitOrder} disabled={saving} sx={{ fontWeight: 400 }}>
            Submit
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(ticketDialogRow)} onClose={() => setTicketDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 400 }}>Add Ticket Picture</DialogTitle>
        <DialogContent dividers>
          {ticketDialogRow && (
            <Stack spacing={1.1}>
              <Typography sx={{ fontSize: 20, fontWeight: 400 }}>{ticketDialogRow.name_clean}</Typography>
              <Button variant="outlined" component="label" sx={{ textTransform: "none", fontWeight: 400 }}>
                {ticketFile ? ticketFile.name : "Select Ticket Photo"}
                <input
                  hidden
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={(e) => setTicketFile(e.target.files?.[0] || null)}
                />
              </Button>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTicketDialogRow(null)} sx={{ fontWeight: 400 }}>Cancel</Button>
          <Button variant="contained" onClick={onAddTicket} disabled={!ticketFile || saving} sx={{ fontWeight: 400 }}>
            Save Picture
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(ticketView)} onClose={() => setTicketView(null)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 400 }}>Ticket Picture</DialogTitle>
        <DialogContent dividers>
          {ticketViewLoading ? (
            <Stack alignItems="center" sx={{ py: 2 }}>
              <CircularProgress size={24} />
            </Stack>
          ) : (
            ticketView && (
              <Stack spacing={1.1}>
                <Typography sx={{ fontWeight: 400 }}>{ticketView.name_clean}</Typography>
                <Box
                  component="img"
                  alt="ticket"
                  src={ticketView.src}
                  sx={{ width: "100%", borderRadius: 1.5, border: "1px solid #e5e7eb" }}
                />
                <Typography sx={{ fontSize: 13, color: "#6b7280", fontWeight: 400 }}>
                  {ticketView.ticket_file_name || "ticket.jpg"}
                </Typography>
              </Stack>
            )
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTicketView(null)} sx={{ fontWeight: 400 }}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={adminTicketsOpen} onClose={() => setAdminTicketsOpen(false)} fullWidth maxWidth="md">
        <DialogTitle sx={{ fontWeight: 400 }}>All Ticket Pictures</DialogTitle>
        <DialogContent dividers>
          {adminTicketsLoading ? (
            <Stack alignItems="center" sx={{ py: 2 }}>
              <CircularProgress size={24} />
            </Stack>
          ) : adminTickets.length === 0 ? (
            <Typography sx={{ color: "#6b7280", fontWeight: 400 }}>No ticket records found.</Typography>
          ) : (
            <Stack spacing={1}>
              {adminTickets.map((t) => (
                <Paper key={`${t.id}-${t.order_id}`} sx={{ p: 1, borderRadius: 1.5, border: "1px solid #e5e7eb" }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 400 }}>{t.name_clean || `Order #${t.order_id}`}</Typography>
                      <Typography sx={{ fontSize: 13, color: "#6b7280", fontWeight: 400 }}>
                        {t.username || "unknown"} • {t.ticket_file_name || "no filename"}
                      </Typography>
                    </Box>
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={async () => {
                        await onViewTicket({ id: t.order_id, name_clean: t.name_clean || `Order #${t.order_id}` });
                      }}
                      sx={{ textTransform: "none", fontWeight: 400 }}
                    >
                      View
                    </Button>
                  </Stack>
                </Paper>
              ))}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAdminTicketsOpen(false)} sx={{ fontWeight: 400 }}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={scanOpen} onClose={() => setScanOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 400 }}>Scan Ticket</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.1}>
            <Button variant="outlined" component="label" sx={{ textTransform: "none", fontWeight: 400 }}>
              {scanFile ? scanFile.name : "Capture / Upload Ticket"}
              <input
                hidden
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(e) => setScanFile(e.target.files?.[0] || null)}
              />
            </Button>
            <Button variant="contained" onClick={onRunScan} disabled={!scanFile || scanBusy} sx={{ textTransform: "none", fontWeight: 400 }}>
              {scanBusy ? "Scanning..." : "Scan"}
            </Button>

            {scanParsed && (
              <Paper sx={{ p: 1, borderRadius: 1.2, border: "1px solid #e5e7eb", bgcolor: "#fafafa" }}>
                <Typography sx={{ fontSize: 13, color: "#4b5563" }}>
                  {scanParsed.ticket_id ? `Ticket ${scanParsed.ticket_id}` : "No ticket id"} • {scanParsed.name_clean || "No name"} •{" "}
                  {scanParsed.weight_num ?? "-"}
                </Typography>
              </Paper>
            )}

            {scanCandidates.length > 0 && (
              <Stack spacing={0.8}>
                <Typography sx={{ fontWeight: 400 }}>Matches</Typography>
                {scanCandidates.map((c) => (
                  <Button
                    key={c.row.id}
                    variant="outlined"
                    onClick={() => pickScanCandidate(c)}
                    sx={{ textTransform: "none", justifyContent: "space-between", fontWeight: 400 }}
                  >
                    <span>{c.row.name_clean} • {formatMeasure(c.row)} • {formatDate(c.row.date_clean)}</span>
                    <span style={{ marginLeft: 8 }}>Score {c.score}</span>
                  </Button>
                ))}
              </Stack>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setScanOpen(false)} sx={{ fontWeight: 400 }}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editRow)} onClose={() => setEditRow(null)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 400 }}>Edit Order</DialogTitle>
        <DialogContent dividers>
          {editRow && (
            <Stack spacing={1.1}>
              <TextField
                label="Date"
                type="date"
                value={editRow.date_clean}
                InputLabelProps={{ shrink: true }}
                onChange={(e) => setEditRow((p) => ({ ...p, date_clean: e.target.value }))}
              />
              <TextField
                label="Name"
                value={editRow.name_clean}
                onChange={(e) => setEditRow((p) => ({ ...p, name_clean: e.target.value }))}
              />
              <TextField
                label="Weight / Count"
                type="number"
                value={editRow.weight_num}
                onChange={(e) => setEditRow((p) => ({ ...p, weight_num: e.target.value }))}
              />
              <TextField
                label="Service"
                select
                value={editRow.service_type}
                onChange={(e) => setEditRow((p) => ({ ...p, service_type: e.target.value }))}
              >
                <MenuItem value="WF">WF</MenuItem>
                <MenuItem value="HD">HD</MenuItem>
              </TextField>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditRow(null)} sx={{ fontWeight: 400 }}>Cancel</Button>
          <Button
            variant="contained"
            onClick={async () => {
              if (!editRow) return;
              setSaving(true);
              try {
                await updateOrder(editRow.id, {
                  date_clean: editRow.date_clean,
                  name_clean: editRow.name_clean,
                  weight_num: Number(editRow.weight_num),
                  service_type: editRow.service_type,
                });
                setEditRow(null);
                await load();
              } finally {
                setSaving(false);
              }
            }}
            disabled={saving}
            sx={{ fontWeight: 400 }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(notice)} onClose={() => setNotice("")} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 400 }}>Confirmation</DialogTitle>
        <DialogContent dividers>
          <Typography sx={{ fontWeight: 400 }}>{notice}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNotice("")} sx={{ fontWeight: 400 }}>OK</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default OrdersPage;
