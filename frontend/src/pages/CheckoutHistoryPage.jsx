import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import {
  getCheckoutHistoryCheckouts,
  getCheckoutHistoryOrders,
  listCheckoutHistorySnapshots,
} from "../api";
import { useI18n } from "../i18n/I18nContext";

export default function CheckoutHistoryPage() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [snapshots, setSnapshots] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [orders, setOrders] = useState([]);
  const [checkouts, setCheckouts] = useState([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadSnapshots = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listCheckoutHistorySnapshots();
      const rows = Array.isArray(res.data) ? res.data : [];
      setSnapshots(rows);
      setSelectedId((prev) => {
        if (prev != null && rows.some((r) => r.id === prev)) return prev;
        return rows[0]?.id ?? null;
      });
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || e?.message || "Could not load history.");
      setSnapshots([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshots();
  }, [loadSnapshots]);

  useEffect(() => {
    if (!selectedId) {
      setOrders([]);
      setCheckouts([]);
      return;
    }
    let cancelled = false;
    (async () => {
      setDetailLoading(true);
      try {
        const [or, co] = await Promise.all([
          getCheckoutHistoryOrders(selectedId),
          getCheckoutHistoryCheckouts(selectedId),
        ]);
        if (!cancelled) {
          setOrders(Array.isArray(or.data) ? or.data : []);
          setCheckouts(Array.isArray(co.data) ? co.data : []);
        }
      } catch (e) {
        if (!cancelled) {
          console.error(e);
          setOrders([]);
          setCheckouts([]);
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  return (
    <Box sx={{ minHeight: "100%", p: { xs: 1.2, md: 2 } }}>
      <Typography sx={{ fontSize: 28, fontWeight: 700, mb: 0.5 }}>{t("checkoutHistory.title")}</Typography>
      <Typography sx={{ color: "#64748b", mb: 2, maxWidth: 720 }}>
        {t("checkoutHistory.blurb")}
      </Typography>

      {loading ? (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress size={32} />
        </Stack>
      ) : error ? (
        <Alert severity="error">{error}</Alert>
      ) : (
        <Stack spacing={2}>
          <Paper sx={{ p: 1.5, borderRadius: 2 }}>
            <Typography sx={{ fontWeight: 600, mb: 1 }}>{t("checkoutHistory.snapshots")}</Typography>
            {snapshots.length === 0 ? (
              <Typography color="text.secondary">{t("checkoutHistory.empty")}</Typography>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t("checkoutHistory.colDay")}</TableCell>
                    <TableCell>{t("checkoutHistory.colArchived")}</TableCell>
                    <TableCell align="right">{t("checkoutHistory.colStaging")}</TableCell>
                    <TableCell align="right">{t("checkoutHistory.colCheckouts")}</TableCell>
                    <TableCell align="right">{t("checkoutHistory.colBatches")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {snapshots.map((s) => (
                    <TableRow
                      key={s.id}
                      hover
                      selected={selectedId === s.id}
                      onClick={() => setSelectedId(s.id)}
                      sx={{ cursor: "pointer" }}
                    >
                      <TableCell>{String(s.business_date || "").slice(0, 10)}</TableCell>
                      <TableCell>{String(s.archived_at || "").replace("T", " ").slice(0, 19)}</TableCell>
                      <TableCell align="right">{s.staging_count ?? 0}</TableCell>
                      <TableCell align="right">{s.checkout_log_count ?? 0}</TableCell>
                      <TableCell align="right">{s.upload_batch_count ?? 0}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Paper>

          {selectedId ? (
            <Paper sx={{ p: 1.5, borderRadius: 2 }}>
              <Typography sx={{ fontWeight: 600, mb: 1 }}>{t("checkoutHistory.ordersTitle")}</Typography>
              {detailLoading ? (
                <CircularProgress size={24} />
              ) : orders.length === 0 ? (
                <Typography color="text.secondary" variant="body2">
                  {t("checkoutHistory.noOrders")}
                </Typography>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t("checkoutHistory.colName")}</TableCell>
                      <TableCell>{t("checkoutHistory.colDate")}</TableCell>
                      <TableCell>{t("checkoutHistory.colSvc")}</TableCell>
                      <TableCell>{t("checkoutHistory.colLogistics")}</TableCell>
                      <TableCell>{t("checkoutHistory.colChecked")}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {orders.map((o) => (
                      <TableRow key={o.id}>
                        <TableCell>{o.name_clean}</TableCell>
                        <TableCell>{String(o.date_clean || "").slice(0, 10)}</TableCell>
                        <TableCell>{o.service_type}</TableCell>
                        <TableCell>{o.logistics_status || "—"}</TableCell>
                        <TableCell>
                          {o.checked_out ? (
                            <Chip size="small" label={t("checkoutHistory.yes")} color="success" />
                          ) : (
                            <Chip size="small" label={t("checkoutHistory.no")} variant="outlined" />
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Paper>
          ) : null}

          {selectedId ? (
            <Paper sx={{ p: 1.5, borderRadius: 2 }}>
              <Typography sx={{ fontWeight: 600, mb: 1 }}>{t("checkoutHistory.checkoutEventsTitle")}</Typography>
              {detailLoading ? (
                <CircularProgress size={24} />
              ) : checkouts.length === 0 ? (
                <Typography color="text.secondary" variant="body2">
                  {t("checkoutHistory.noCheckouts")}
                </Typography>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t("checkoutHistory.colTime")}</TableCell>
                      <TableCell>{t("checkoutHistory.colName")}</TableCell>
                      <TableCell>{t("checkoutHistory.colSvc")}</TableCell>
                      <TableCell>{t("checkoutHistory.colEmployee")}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {checkouts.map((c) => (
                      <TableRow key={c.id}>
                        <TableCell>{String(c.checkout_time || "").replace("T", " ").slice(0, 19)}</TableCell>
                        <TableCell>{c.name}</TableCell>
                        <TableCell>{c.service}</TableCell>
                        <TableCell>{c.employee || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Paper>
          ) : null}
        </Stack>
      )}
    </Box>
  );
}
