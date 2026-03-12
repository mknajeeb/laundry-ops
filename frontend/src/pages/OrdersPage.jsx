import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Chip,
  CircularProgress,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { FlashOn, Refresh, Search } from "@mui/icons-material";
import { deleteOrder, getCurrentUploadBatch, getEmployees, getOrders, processOrder, updateOrder } from "../api";
import { useSearchParams } from "react-router-dom";

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

function OrdersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [orders, setOrders] = useState([]);
  const [activeBatch, setActiveBatch] = useState(null);
  const [loading, setLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [service, setService] = useState((searchParams.get("service") || "ALL").toUpperCase());
  const [rush, setRush] = useState((searchParams.get("rush") || "ALL").toUpperCase());
  const [logistics, setLogistics] = useState((searchParams.get("logistics") || "ALL").toUpperCase());
  const [processing, setProcessing] = useState((searchParams.get("processing") || searchParams.get("status") || "ALL").toUpperCase());
  const [alpha, setAlpha] = useState("ALL");
  const [editRow, setEditRow] = useState(null);
  const [saving, setSaving] = useState(false);
  const [employees, setEmployees] = useState([]);
  const [processRow, setProcessRow] = useState(null);

  useEffect(() => {
    const nextService = (searchParams.get("service") || "ALL").toUpperCase();
    const nextRush = (searchParams.get("rush") || "ALL").toUpperCase();
    const nextLogistics = (searchParams.get("logistics") || "ALL").toUpperCase();
    const nextProcessing = (searchParams.get("processing") || searchParams.get("status") || "ALL").toUpperCase();
    setService(nextService);
    setRush(nextRush);
    setLogistics(nextLogistics);
    setProcessing(nextProcessing);
  }, [searchParams]);

  const loadOrders = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getOrders();
      const rows = Array.isArray(res.data) ? res.data : [];
      setOrders(rows);
    } catch (error) {
      console.error(error);
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOrders();
  }, [loadOrders]);

  useEffect(() => {
    async function loadEmployees() {
      try {
        const res = await getEmployees();
        setEmployees(Array.isArray(res.data) ? res.data : []);
      } catch (error) {
        console.error(error);
        setEmployees([]);
      }
    }
    loadEmployees();
  }, []);

  useEffect(() => {
    async function loadBatch() {
      try {
        const res = await getCurrentUploadBatch();
        setActiveBatch(res?.data || null);
      } catch (error) {
        console.error(error);
        setActiveBatch(null);
      }
    }
    loadBatch();
  }, []);

  const handleFullRefresh = async () => {
    setSearch("");
    setService("ALL");
    setRush("ALL");
    setLogistics("ALL");
    setProcessing("ALL");
    setAlpha("ALL");
    setSearchParams({});
    await loadOrders();
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();

    return orders.filter((row) => {
      const rowService = String(row?.service_type || "").toUpperCase();
      const rowRush = String(row?.rush_type || "").toUpperCase();
      const rowLogistics = String(
        row?.logistics_status || (String(row?.status || "").toUpperCase() === "CHECKED_OUT" ? "SENT_TO_RINSE" : "AT_WASHPRO")
      ).toUpperCase();
      const rowProcessing = String(
        row?.processing_status || (String(row?.status || "").toUpperCase() === "PROCESSED" ? "PROCESSED" : "PENDING")
      ).toUpperCase();

      const matchSearch =
        !q ||
        String(row?.name_clean || "").toLowerCase().includes(q) ||
        String(row?.id || "").includes(q);

      const matchService = service === "ALL" || rowService === service;
      const matchRush = rush === "ALL" || rowRush === rush;
      const matchLogistics = logistics === "ALL" || rowLogistics === logistics;
      const matchProcessing = processing === "ALL" || rowProcessing === processing;
      const name = String(row?.name_clean || "").trim().toUpperCase();
      const first = name.charAt(0);
      const matchAlpha = alpha === "ALL" || first === alpha;

      return matchSearch && matchService && matchRush && matchLogistics && matchProcessing && matchAlpha;
    });
  }, [orders, search, service, rush, logistics, processing, alpha]);

  const stats = useMemo(() => {
    const total = filtered.length;
    const wf = filtered.filter((row) => String(row?.service_type || "").toUpperCase() === "WF").length;
    const hd = filtered.filter((row) => String(row?.service_type || "").toUpperCase() === "HD").length;
    const rushCount = filtered.filter((row) => String(row?.rush_type || "").toUpperCase() === "RUSH").length;

    return { total, wf, hd, rushCount };
  }, [filtered]);

  const formatMeasure = (row) => {
    const serviceType = String(row?.service_type || "").toUpperCase();
    const raw = Number(row?.weight_num ?? 0);

    if (serviceType === "WF") return `${raw.toFixed(2)} lb`;
    if (serviceType === "HD") return `${Math.round(raw)} pcs`;
    return "-";
  };

  const formatDateOnly = (value) => {
    if (!value) return "-";
    const d = parseAsLocalDate(value);
    if (!d || Number.isNaN(d.getTime())) return String(value).split(" ")[0];
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const applyParamFilters = (nextService, nextRush, nextLogistics, nextProcessing) => {
    const next = {};
    if (nextService !== "ALL") next.service = nextService;
    if (nextRush !== "ALL") next.rush = nextRush;
    if (nextLogistics !== "ALL") next.logistics = nextLogistics;
    if (nextProcessing !== "ALL") next.processing = nextProcessing;
    setSearchParams(next);
  };

  return (
    <Box sx={{ minHeight: "100vh", background: "#f3f4f6", px: { xs: 1.2, md: 2.4 }, py: 1.5 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 30, fontWeight: 500, lineHeight: 1 }}>Orders</Typography>
        <Button size="small" variant="text" startIcon={<Refresh />} onClick={loadOrders} disabled={loading}>
          Refresh
        </Button>
      </Stack>
      <Typography sx={{ color: "#6b7280", mt: 0.4 }}>Live staging queue</Typography>
      {activeBatch && (
        <Chip
          size="small"
          sx={{ mt: 0.8 }}
          color={String(activeBatch.state || "").toUpperCase() === "CONFIRMED" ? "success" : "warning"}
          label={`${(parseAsLocalDate(activeBatch.batch_date) || new Date(activeBatch.batch_date)).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" })} • ${String(activeBatch.state || "DRAFT").toUpperCase()}`}
        />
      )}

      <Stack direction="row" spacing={1} sx={{ mt: 1.2, overflowX: "auto", pb: 0.4 }}>
        <Chip label={`${stats.total} visible`} color="primary" />
        <Chip label={`WF ${stats.wf}`} />
        <Chip label={`HD ${stats.hd}`} />
        <Chip icon={<FlashOn />} label={`RUSH ${stats.rushCount}`} color="error" variant="outlined" />
        <Button size="small" variant="outlined" onClick={() => window.print()}>
          Print
        </Button>
        <Button size="small" variant="outlined" onClick={handleFullRefresh} disabled={loading}>Reset Filters</Button>
      </Stack>

      <Paper sx={{ p: 1.2, borderRadius: 2, mt: 1.2 }}>
        <TextField
          fullWidth
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or id"
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search fontSize="small" />
              </InputAdornment>
            ),
          }}
        />

        <Stack direction="row" spacing={1} sx={{ mt: 1, overflowX: "auto", pb: 0.5 }}>
          {["ALL", "WF", "HD"].map((item) => (
            <Chip
              key={item}
              label={item}
              clickable
              color={service === item ? "warning" : "default"}
              onClick={() => {
                setService(item);
                applyParamFilters(item, rush, logistics, processing);
              }}
            />
          ))}
          {["ALL", "RUSH", "NON-RUSH"].map((item) => (
            <Chip
              key={item}
              label={item}
              clickable
              color={rush === item ? "error" : "default"}
              onClick={() => {
                setRush(item);
                applyParamFilters(service, item, logistics, processing);
              }}
            />
          ))}
          {["ALL", "AT_WASHPRO", "SENT_TO_RINSE", "FORCE_CHECKOUT"].map((item) => (
            <Chip
              key={item}
              label={item}
              clickable
              color={logistics === item ? "info" : "default"}
              onClick={() => {
                setLogistics(item);
                applyParamFilters(service, rush, item, processing);
              }}
            />
          ))}
          {["ALL", "PENDING", "PROCESSED"].map((item) => (
            <Chip
              key={item}
              label={item}
              clickable
              color={processing === item ? "success" : "default"}
              onClick={() => {
                setProcessing(item);
                applyParamFilters(service, rush, logistics, item);
              }}
            />
          ))}
        </Stack>

        <Stack direction="row" spacing={0.7} sx={{ mt: 0.5, overflowX: "auto", pb: 0.3 }}>
          {["ALL", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"].map((letter) => (
            <Chip
              key={letter}
              label={letter}
              clickable
              color={alpha === letter ? "primary" : "default"}
              onClick={() => setAlpha(letter)}
            />
          ))}
        </Stack>
      </Paper>

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.2}>
          <CircularProgress />
          <Typography color="text.secondary">Loading orders...</Typography>
        </Stack>
      ) : filtered.length === 0 ? (
        <Paper sx={{ p: 2, mt: 1.5, borderRadius: 2, color: "#6b7280" }}>No orders found for this filter.</Paper>
      ) : (
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {filtered.map((row) => {
            const isRush = String(row?.rush_type || "").toUpperCase() === "RUSH";
            const isHD = String(row?.service_type || "").toUpperCase() === "HD";
            const rowLogistics = String(
              row?.logistics_status || (String(row?.status || "").toUpperCase() === "CHECKED_OUT" ? "SENT_TO_RINSE" : "AT_WASHPRO")
            ).toUpperCase();
            const rowProcessing = String(
              row?.processing_status || (String(row?.status || "").toUpperCase() === "PROCESSED" ? "PROCESSED" : "PENDING")
            ).toUpperCase();

            return (
              <Paper
                key={row.id}
                sx={{
                  p: 1.2,
                  borderRadius: 2,
                  border: isHD ? "1px solid #0097b2" : "1px solid #ffbd59",
                  bgcolor: isHD ? "#0097b2" : "#111827",
                }}
              >
                <Stack spacing={0.7}>
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Typography sx={{ fontSize: 20, fontWeight: 500, color: "#fff" }}>{row.name_clean || "-"}</Typography>
                    <Chip size="small" label={`#${row.id}`} sx={{ bgcolor: "#fff", color: "#111827" }} />
                  </Stack>

                  <Typography sx={{ color: "#f8fafc", fontWeight: 500 }}>
                    {formatMeasure(row)} • {formatDateOnly(row.date_clean)}
                  </Typography>

                  <Stack direction="row" spacing={1}>
                    <Chip size="small" label={row.service_type || "-"} sx={{ bgcolor: "#fff", color: "#111827" }} />
                    <Chip size="small" label={isRush ? "RUSH" : "NON-RUSH"} sx={{ bgcolor: "#fff", color: "#111827" }} />
                    <Chip size="small" label={rowLogistics} sx={{ bgcolor: "#fff", color: "#111827" }} />
                    <Chip size="small" label={rowProcessing} sx={{ bgcolor: "#fff", color: "#111827" }} />
                  </Stack>

                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="outlined" onClick={() => setEditRow({
                      id: row.id,
                      date_clean: String(row.date_clean || "").slice(0, 10),
                      name_clean: row.name_clean || "",
                      weight_num: row.weight_num ?? "",
                      service_type: row.service_type || "WF",
                    })}>
                      Edit
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      sx={{ bgcolor: "#ffffff", color: "#111827", "&:hover": { bgcolor: "#f3f4f6" } }}
                      onClick={() =>
                        setProcessRow({
                          order_id: row.id,
                          washer_employee_id: "",
                          folder_employee_id: "",
                          processing_date: new Date().toISOString().slice(0, 10),
                          fold_end_time: "",
                        })
                      }
                    >
                      Process
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      color="error"
                      onClick={async () => {
                        if (!window.confirm(`Delete order #${row.id}?`)) return;
                        try {
                          await deleteOrder(row.id);
                          setOrders((prev) => prev.filter((r) => r.id !== row.id));
                        } catch (error) {
                          console.error(error);
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </Stack>
                </Stack>
              </Paper>
            );
          })}
        </Stack>
      )}

      <Dialog open={!!editRow} onClose={() => setEditRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>Edit Order</DialogTitle>
        <DialogContent>
          {editRow && (
            <Stack spacing={1.2} sx={{ mt: 0.6 }}>
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
          <Button onClick={() => setEditRow(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!editRow || saving}
            onClick={async () => {
              if (!editRow) return;
              try {
                setSaving(true);
                await updateOrder(editRow.id, {
                  date_clean: editRow.date_clean,
                  name_clean: editRow.name_clean,
                  weight_num: Number(editRow.weight_num),
                  service_type: editRow.service_type,
                });
                setOrders((prev) =>
                  prev.map((r) =>
                    r.id === editRow.id
                      ? {
                          ...r,
                          date_clean: editRow.date_clean,
                          name_clean: editRow.name_clean,
                          weight_num: Number(editRow.weight_num),
                          service_type: editRow.service_type,
                        }
                      : r
                  )
                );
                setEditRow(null);
              } catch (error) {
                console.error(error);
              } finally {
                setSaving(false);
              }
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!processRow} onClose={() => setProcessRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>Enter Processing Data</DialogTitle>
        <DialogContent>
          {processRow && (
            <Stack spacing={1.2} sx={{ mt: 0.6 }}>
              <TextField
                select
                label="Washed By"
                value={processRow.washer_employee_id}
                onChange={(e) => setProcessRow((p) => ({ ...p, washer_employee_id: e.target.value }))}
              >
                {employees.map((emp) => (
                  <MenuItem key={emp.id} value={emp.id}>{emp.name}</MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Folded By"
                value={processRow.folder_employee_id}
                onChange={(e) => setProcessRow((p) => ({ ...p, folder_employee_id: e.target.value }))}
              >
                {employees.map((emp) => (
                  <MenuItem key={emp.id} value={emp.id}>{emp.name}</MenuItem>
                ))}
              </TextField>
              <TextField
                type="date"
                label="Processing Date"
                value={processRow.processing_date}
                InputLabelProps={{ shrink: true }}
                onChange={(e) => setProcessRow((p) => ({ ...p, processing_date: e.target.value }))}
              />
              <TextField
                label="Folding End Time (e.g. 03:45 PM)"
                value={processRow.fold_end_time}
                onChange={(e) => setProcessRow((p) => ({ ...p, fold_end_time: e.target.value }))}
              />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setProcessRow(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!processRow || !processRow.washer_employee_id || !processRow.folder_employee_id}
            onClick={async () => {
              if (!processRow) return;
              try {
                setSaving(true);
                await processOrder({
                  ...processRow,
                  pieces: null,
                  issue_type: null,
                  rinse_case_id: null,
                });
                setOrders((prev) =>
                  prev.map((r) =>
                    r.id === processRow.order_id
                      ? { ...r, processing_status: "PROCESSED", status: "PROCESSED" }
                      : r
                  )
                );
                setProcessRow(null);
              } catch (error) {
                console.error(error);
              } finally {
                setSaving(false);
              }
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default OrdersPage;
