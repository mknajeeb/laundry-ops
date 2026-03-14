import { useEffect, useMemo, useState, useDeferredValue } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  InputAdornment,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Bolt, CheckCircle, Close, DeleteOutline, ExpandLess, ExpandMore, Image, Refresh, Search, Visibility } from "@mui/icons-material";
import {
  deleteOrderTicket,
  deleteOrder,
  getCurrentUploadBatch,
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

function normalizeCode(value) {
  return String(value || "").trim().toUpperCase();
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
  const [submitPreview, setSubmitPreview] = useState("");
  const [ticketDialogRow, setTicketDialogRow] = useState(null);
  const [ticketFile, setTicketFile] = useState(null);
  const [ticketView, setTicketView] = useState(null);
  const [ticketViewLoading, setTicketViewLoading] = useState(false);
  const [adminTicketsOpen, setAdminTicketsOpen] = useState(false);
  const [adminTicketsLoading, setAdminTicketsLoading] = useState(false);
  const [adminTickets, setAdminTickets] = useState([]);
  const [notice, setNotice] = useState("");
  const [batchInfo, setBatchInfo] = useState(null);

  const [editRow, setEditRow] = useState(null);

  const roleCodes = (user?.roles || []).map((r) => String(r).toUpperCase());
  const isAdmin = roleCodes.includes("ADMIN");
  const userId = Number(user?.user_id || 0);

  const load = async () => {
    try {
      setLoading(true);
      const [ordersRes, batchRes] = await Promise.all([
        getOrders({ include_all: true }),
        getCurrentUploadBatch().catch(() => ({ data: null })),
      ]);
      setRows(Array.isArray(ordersRes?.data) ? ordersRes.data : []);
      setBatchInfo(batchRes?.data || null);
    } catch (error) {
      console.error(error);
      setRows([]);
      setBatchInfo(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const normalizeLogistics = (r) => {
    const v = normalizeCode(r?.logistics_status);
    if (v) return v;
    const s = normalizeCode(r?.status);
    if (["CHECKED_OUT", "SENT_TO_RINSE"].includes(s)) return "SENT_TO_RINSE";
    if (["FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(s)) return "FORCE_CHECKOUT";
    return "AT_WASHPRO";
  };

  const normalizeProcessing = (r) => {
    const v = normalizeCode(r?.processing_status);
    if (v) return v;
    const s = normalizeCode(r?.status);
    return s === "PROCESSED" ? "PROCESSED" : "PENDING";
  };

  const rushOf = (r) => normalizeCode(r?.rush_type) === "RUSH" ? "RUSH" : "NON-RUSH";
  const serviceOf = (r) => normalizeCode(r?.service_type);
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

  const formatBatchDayDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  };

  useEffect(() => {
    if (!submitFile) {
      setSubmitPreview("");
      return;
    }
    const url = URL.createObjectURL(submitFile);
    setSubmitPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [submitFile]);

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
      if (isHD(submitDialogRow) && !Number.isInteger(measureNum)) {
        setNotice("HD count must be a whole number.");
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

  const activeBatchDate = batchInfo?.batch_date || rows[0]?.batch_date || null;
  const searchActive = deferredSearch.trim().length > 0;

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#ffffff", px: { xs: 1, sm: 1.5 }, py: 1 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Stack spacing={0.2}>
          <Typography sx={{ fontSize: 30, fontWeight: 400 }}>Rinse orders</Typography>
          <Typography sx={{ fontSize: 15, color: "#6b7280", fontWeight: 400 }}>
            {formatBatchDayDate(activeBatchDate)}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant={showProcessed ? "contained" : "outlined"}
            onClick={() => setShowProcessed((prev) => !prev)}
            sx={{ textTransform: "none", fontWeight: 400 }}
          >
            Processed
          </Button>
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
            if (searchActive && list.length === 0) return null;
            const expanded = searchActive ? true : openAlpha === alpha;
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
                                        setSubmitMeasure("");
                                        setSubmitTicketId(String(r.ticket_id || ""));
                                        setSubmitFile(null);
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
                Upload ticket
                <input
                  hidden
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={(e) => setSubmitFile(e.target.files?.[0] || null)}
                />
              </Button>
              {submitPreview && (
                <Box sx={{ position: "relative", borderRadius: 1.5, overflow: "hidden", border: "1px solid #e5e7eb" }}>
                  <Box
                    component="img"
                    src={submitPreview}
                    alt="ticket preview"
                    sx={{ width: "100%", display: "block", maxHeight: 260, objectFit: "contain", bgcolor: "#111827" }}
                  />
                  <IconButton
                    size="small"
                    onClick={() => setSubmitFile(null)}
                    sx={{
                      position: "absolute",
                      top: 8,
                      right: 8,
                      bgcolor: "rgba(255,255,255,0.9)",
                      "&:hover": { bgcolor: "#ffffff" },
                    }}
                  >
                    <Close fontSize="small" />
                  </IconButton>
                </Box>
              )}
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
