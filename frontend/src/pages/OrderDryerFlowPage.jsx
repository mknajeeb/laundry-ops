import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControlLabel,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { Add, CameraAlt, CheckCircle, Remove } from "@mui/icons-material";
import { Html5Qrcode, Html5QrcodeSupportedFormats } from "html5-qrcode";
import { useNavigate, useParams } from "react-router-dom";
import StandardScreenHeader from "../components/layout/StandardScreenHeader";
import { useI18n } from "../i18n/I18nContext";
import {
  cancelOrderGamingSession,
  completeOrderGamingTicket,
  getOrderGamingSession,
  scanOrderGamingDryer,
  startOrderGamingSession,
} from "../api";
import { displayCustomerName } from "../utils/displayCustomerName";

const READER_ID = "dryer-qr-reader";
const DRYER_MAINT_KEY = "washpro_dryer_scan_maintenance";

const DRYER_QR_READER_OUTER_SX = {
  borderRadius: 2,
  overflow: "hidden",
  bgcolor: "#0b1220",
  width: "100%",
  minWidth: 200,
  minHeight: "min(42vh, 400px)",
  maxHeight: { xs: "42vh", sm: 420 },
  position: "relative",
  border: "1px solid rgba(148,163,184,0.35)",
};

const DRYER_QR_READER_INNER_SX = {
  display: "block",
  width: "100%",
  minWidth: 200,
  minHeight: "min(42vh, 400px)",
  boxSizing: "border-box",
};

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

function normSvc(r) {
  return String(r?.service_type || "").trim().toUpperCase();
}

function isHdRow(r) {
  return normSvc(r) === "HD";
}

function formatOrderLine(r) {
  if (!r) return "";
  const n = Number(r.weight_num ?? 0);
  const m = isHdRow(r) ? `${Math.round(n)} pcs` : `${Number.isFinite(n) ? n.toFixed(2) : "0.00"} lb`;
  const ds = String(r.date_clean || "").slice(0, 10);
  return ds ? `${ds} · ${m}` : m;
}

export default function OrderDryerFlowPage({ user }) {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const oid = Number(orderId);
  const uid = Number(user?.user_id || 0);

  const [loading, setLoading] = useState(true);
  const [blocked, setBlocked] = useState("");
  const [alreadyDone, setAlreadyDone] = useState(false);
  const [step, setStep] = useState(1);
  const [dryerCount, setDryerCount] = useState(1);
  const [lockToken, setLockToken] = useState("");
  const [dryers, setDryers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [manualCode, setManualCode] = useState("");
  const [sessionOrder, setSessionOrder] = useState(null);
  const [dryerMaintenanceOn, setDryerMaintenanceOn] = useState(() => localStorage.getItem(DRYER_MAINT_KEY) !== "0");
  const [isSimpleSession, setIsSimpleSession] = useState(false);
  const [pendingTicketB64, setPendingTicketB64] = useState("");
  const [pendingTicketFname, setPendingTicketFname] = useState("ticket.jpg");
  const [weightInput, setWeightInput] = useState(0);
  const [completedFlash, setCompletedFlash] = useState(false);
  const scannerRef = useRef(null);
  const startedRef = useRef(false);

  useEffect(() => {
    localStorage.setItem(DRYER_MAINT_KEY, dryerMaintenanceOn ? "1" : "0");
  }, [dryerMaintenanceOn]);

  const stopScanner = useCallback(async () => {
    const h = scannerRef.current;
    scannerRef.current = null;
    if (!h) return;
    try {
      await h.stop();
    } catch {
      /* ignore */
    }
    try {
      await h.clear();
    } catch {
      /* ignore */
    }
  }, []);

  const finishSuccess = useCallback(() => {
    setCompletedFlash(true);
    window.setTimeout(() => navigate("/orders", { replace: true }), 2200);
  }, [navigate]);

  const onScanDryer = useCallback(
    async (code) => {
      if (!lockToken) return;
      setBusy(true);
      try {
        const res = await scanOrderGamingDryer(oid, { lock_token: lockToken, dryer_code: code });
        const list = res.data?.dryers || [];
        setDryers(list);
        if (res.data?.complete) {
          await stopScanner();
          setStep(3);
        }
      } catch (e) {
        window.alert(e?.response?.data?.error || "Scan failed");
      } finally {
        setBusy(false);
      }
    },
    [lockToken, oid, stopScanner]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!Number.isFinite(oid) || oid < 1) {
        setBlocked("Invalid order.");
        setLoading(false);
        return;
      }
      try {
        const res = await getOrderGamingSession(oid);
        if (cancelled) return;
        const d = res.data || {};
        setSessionOrder({
          name_clean: d.name_clean,
          date_clean: d.date_clean,
          weight_num: d.weight_num,
          service_type: d.service_type,
          ticket_id: d.ticket_id,
          rush_type: d.rush_type,
        });
        const st = String(d.gaming_flow_status || "").toUpperCase();
        if (st === "COMPLETED") {
          setAlreadyDone(true);
          setLoading(false);
          return;
        }
        if (st === "ACTIVE") {
          const owner = Number(d.gaming_locked_by_user_id || 0);
          if (owner && owner !== uid) {
            setBlocked("Another team member is handling this order right now.");
            setLoading(false);
            return;
          }
          if (d.lock_token) {
            setLockToken(String(d.lock_token));
            const n = Number(d.gaming_dryer_count) || 0;
            setIsSimpleSession(n === 0);
            setDryerCount(n < 1 ? 1 : n);
            const list = Array.isArray(d.gaming_dryers) ? d.gaming_dryers : [];
            setDryers(list);
            if (n === 0) {
              setStep(3);
            } else if (list.length >= n) {
              setStep(3);
            } else {
              setStep(2);
            }
            setLoading(false);
            return;
          }
        }
        setStep(1);
        setIsSimpleSession(false);
      } catch (e) {
        if (!cancelled) setBlocked(e?.response?.data?.error || "Could not load session.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [oid, uid]);

  useEffect(() => {
    if (step === 5 && sessionOrder) {
      const w = Number(sessionOrder.weight_num);
      setWeightInput(Number.isFinite(w) ? w : 0);
    }
  }, [step, sessionOrder]);

  useEffect(() => {
    if (step !== 2 || !lockToken) return undefined;
    let cancelled = false;
    startedRef.current = false;

    const run = async () => {
      await stopScanner();
      if (cancelled) return;
      for (let attempt = 0; attempt < 24; attempt += 1) {
        if (cancelled) return;
        const probe = document.getElementById(READER_ID);
        if (probe) {
          const rect = probe.getBoundingClientRect();
          if (rect.width >= 120 && rect.height >= 120) break;
        }
        await new Promise((r) => window.setTimeout(r, 50));
      }
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      if (cancelled) return;
      const el = document.getElementById(READER_ID);
      if (!el) return;
      const html5 = new Html5Qrcode(READER_ID, {
        verbose: false,
        formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE],
        useBarCodeDetectorIfSupported: false,
      });
      scannerRef.current = html5;
      try {
        await html5.start(
          { facingMode: { ideal: "environment" } },
          {
            fps: 10,
            aspectRatio: 1,
            qrbox: (vw, vh) => {
              const w = Number(vw) || 320;
              const h = Number(vh) || 320;
              const side = Math.floor(Math.min(w, h) * 0.88);
              return { width: Math.max(200, side), height: Math.max(200, side) };
            },
          },
          async (text) => {
            if (startedRef.current) return;
            const tx = String(text || "").trim();
            if (!tx) return;
            startedRef.current = true;
            try {
              await onScanDryer(tx);
            } finally {
              startedRef.current = false;
            }
          },
          () => {}
        );
      } catch {
        /* camera blocked — manual entry still works */
      }
    };
    run();
    return () => {
      cancelled = true;
      stopScanner();
    };
  }, [step, lockToken, stopScanner, onScanDryer]);

  const onNextFromCount = async () => {
    setBusy(true);
    try {
      const res = await startOrderGamingSession(oid, { dryer_count: dryerCount });
      setLockToken(res.data?.lock_token || "");
      setDryers(res.data?.dryers || []);
      setIsSimpleSession(false);
      setStep(2);
    } catch (e) {
      window.alert(e?.response?.data?.error || "Could not start assignment");
    } finally {
      setBusy(false);
    }
  };

  const onStartSimplePath = async () => {
    setBusy(true);
    try {
      const res = await startOrderGamingSession(oid, { dryer_count: 0, simple_flow: true });
      setLockToken(res.data?.lock_token || "");
      setDryers([]);
      setDryerCount(0);
      setIsSimpleSession(true);
      setStep(3);
    } catch (e) {
      window.alert(e?.response?.data?.error || "Could not start assignment");
    } finally {
      setBusy(false);
    }
  };

  const completeTicketWithFile = async (file) => {
    if (!file || !lockToken) return;
    setBusy(true);
    try {
      const b64 = await fileToBase64(file);
      if (isSimpleSession) {
        setPendingTicketB64(b64);
        setPendingTicketFname(file.name || "ticket.jpg");
        setStep(4);
      } else {
        await completeOrderGamingTicket(oid, {
          lock_token: lockToken,
          ticket_image_base64: b64,
          ticket_file_name: file.name,
        });
        finishSuccess();
      }
    } catch (e) {
      window.alert(e?.response?.data?.error || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const submitSimpleComplete = async () => {
    if (!lockToken || !pendingTicketB64) return;
    setBusy(true);
    try {
      await completeOrderGamingTicket(oid, {
        lock_token: lockToken,
        ticket_image_base64: pendingTicketB64,
        ticket_file_name: pendingTicketFname,
        weight_num: weightInput,
      });
      finishSuccess();
    } catch (e) {
      window.alert(e?.response?.data?.error || "Could not complete order");
    } finally {
      setBusy(false);
    }
  };

  const bumpWeight = (dir) => {
    const stepAmt = isHdRow(sessionOrder) ? 1 : 0.25;
    setWeightInput((w) => {
      const cur = Number(w) || 0;
      const next = cur + dir * stepAmt;
      return isHdRow(sessionOrder) ? Math.max(0, Math.round(next)) : Math.max(0, Math.round(next * 100) / 100);
    });
  };

  const onCancelFlow = async () => {
    if (!lockToken) {
      navigate(-1);
      return;
    }
    if (!window.confirm("Cancel dryer assignment and unlock this order?")) return;
    setBusy(true);
    try {
      await cancelOrderGamingSession(oid, { lock_token: lockToken });
      navigate("/orders", { replace: true });
    } catch {
      navigate("/orders", { replace: true });
    } finally {
      setBusy(false);
    }
  };

  const orderBanner = sessionOrder && (
    <Paper
      elevation={0}
      sx={{
        mb: 1.25,
        p: 1.25,
        borderRadius: 2,
        border: "1px solid #e9d5ff",
        bgcolor: "rgba(255,255,255,0.92)",
      }}
    >
      <Typography sx={{ fontWeight: 800, fontSize: "1.05rem", color: "#1e1b4b", lineHeight: 1.25 }}>
        {displayCustomerName(sessionOrder.name_clean) || `Order #${oid}`}
      </Typography>
      {sessionOrder.ticket_id ? (
        <Typography sx={{ fontSize: 14, fontWeight: 600, color: "#4c1d95", mt: 0.35 }}>
          {t("ops.bagIdShort")} {String(sessionOrder.ticket_id)}
        </Typography>
      ) : null}
      <Typography sx={{ fontSize: 13.5, color: "#64748b", mt: 0.35 }}>
        #{oid}
        {sessionOrder.service_type ? ` · ${String(sessionOrder.service_type)}` : ""}
        {formatOrderLine(sessionOrder) ? ` · ${formatOrderLine(sessionOrder)}` : ""}
      </Typography>
    </Paper>
  );

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "100vh" }}>
        <CircularProgress />
      </Stack>
    );
  }

  if (blocked) {
    return (
      <Box
        sx={{
          p: { xs: 1, sm: 2 },
          minHeight: "100vh",
          background: "linear-gradient(168deg, #faf5ff 0%, #f3e8ff 40%, #fafafa 100%)",
        }}
      >
        <StandardScreenHeader title={t("ops.dryerFlowTitle")} dense onBack={() => navigate(-1)} />
        <Alert severity="warning" sx={{ mt: 2 }}>
          {blocked}
        </Alert>
      </Box>
    );
  }

  if (alreadyDone) {
    return (
      <Box
        sx={{
          p: { xs: 1, sm: 2 },
          minHeight: "100vh",
          background: "linear-gradient(168deg, #faf5ff 0%, #f3e8ff 40%, #fafafa 100%)",
        }}
      >
        <StandardScreenHeader title={t("ops.dryerFlowTitle")} dense onBack={() => navigate("/orders")} />
        <Alert severity="info" sx={{ mt: 2 }}>
          Dryer assignment is already completed for this order. Add or replace the ticket photo from Upload → Live orders for this batch if needed.
        </Alert>
      </Box>
    );
  }

  const maintToggleDisabled = Boolean(lockToken);

  return (
    <Box
      sx={{
        minHeight: "100vh",
        background: "linear-gradient(168deg, #faf5ff 0%, #ede9fe 35%, #f5f3ff 70%, #fafafa 100%)",
        display: "flex",
        flexDirection: "column",
        pb: "env(safe-area-inset-bottom, 16px)",
        px: { xs: 1, sm: 1.5 },
        pt: 1,
        position: "relative",
      }}
    >
      <StandardScreenHeader
        title={`${t("ops.dryerFlowTitle")} #${oid}`}
        dense
        onBack={onCancelFlow}
        homePath="/orders"
      />

      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
        {orderBanner}

        {step === 1 && (
          <Stack spacing={2} sx={{ flex: 1, px: 1, py: 1, maxWidth: 420, mx: "auto", width: "100%" }}>
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: "#fafafa", borderColor: "#c4b5fd" }}>
              <Typography sx={{ fontWeight: 800, fontSize: "0.95rem", color: "#5b21b6", mb: 1.25 }}>
                Dryer maintenance
              </Typography>
              <FormControlLabel
                sx={{ alignItems: "center", mx: 0, display: "flex" }}
                control={
                  <Switch
                    checked={dryerMaintenanceOn}
                    disabled={maintToggleDisabled}
                    onChange={(_, v) => setDryerMaintenanceOn(v)}
                    color="primary"
                  />
                }
                label={
                  <Box>
                    <Typography sx={{ fontWeight: 700, fontSize: 15 }}>
                      Dryer QR scan {dryerMaintenanceOn ? "on" : "off"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.35 }}>
                      Off skips dryer count and scanning — ticket photo, then mark complete, then weight.
                    </Typography>
                  </Box>
                }
              />
            </Paper>
            {!dryerMaintenanceOn ? (
              <>
                <Typography color="text.secondary">
                  Continue to capture the ticket, confirm complete, then enter weight to finish.
                </Typography>
                <Button
                  variant="contained"
                  size="large"
                  disabled={busy}
                  onClick={onStartSimplePath}
                  sx={{ borderRadius: 999, py: 1.6, fontWeight: 700, fontSize: "1.05rem" }}
                >
                  Continue
                </Button>
              </>
            ) : (
              <>
                <Typography variant="h5" sx={{ fontWeight: 700 }}>
                  How many dryers?
                </Typography>
                <Stack direction="row" alignItems="center" justifyContent="center" spacing={3}>
                  <Button
                    variant="outlined"
                    size="large"
                    onClick={() => setDryerCount((c) => Math.max(1, c - 1))}
                    sx={{ minWidth: 56, minHeight: 56, borderRadius: 2 }}
                  >
                    <Remove fontSize="large" />
                  </Button>
                  <Typography sx={{ fontSize: 42, fontWeight: 800, minWidth: 64, textAlign: "center" }}>{dryerCount}</Typography>
                  <Button
                    variant="outlined"
                    size="large"
                    onClick={() => setDryerCount((c) => Math.min(20, c + 1))}
                    sx={{ minWidth: 56, minHeight: 56, borderRadius: 2 }}
                  >
                    <Add fontSize="large" />
                  </Button>
                </Stack>
                <Button
                  variant="contained"
                  size="large"
                  disabled={busy}
                  onClick={onNextFromCount}
                  sx={{ borderRadius: 999, py: 1.6, fontWeight: 700, fontSize: "1.05rem" }}
                >
                  Next
                </Button>
              </>
            )}
          </Stack>
        )}

        {step === 2 && (
          <Stack sx={{ flex: 1, px: 0.5, py: 0.5, overflow: "hidden" }}>
            <Typography sx={{ fontWeight: 700, mb: 1, px: 0.5 }}>Scan dryer QR codes</Typography>
            <Box
              sx={{
                display: "grid",
                gridTemplateRows: { xs: "1fr 1fr", sm: "1fr" },
                gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
                gap: 1,
                flex: 1,
                minHeight: 0,
              }}
            >
              <Box sx={{ ...DRYER_QR_READER_OUTER_SX, border: "2px solid #e2e8f0" }}>
                <Box id={READER_ID} sx={DRYER_QR_READER_INNER_SX} />
              </Box>
              <Stack spacing={1.2} sx={{ p: 1, bgcolor: "#fff", borderRadius: 2, border: "1px solid #e2e8f0" }}>
                <Typography sx={{ fontWeight: 600 }}>
                  Dryers ({dryers.length} / {dryerCount})
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={0.75}>
                  {dryers.map((d) => (
                    <Box
                      key={d}
                      sx={{
                        px: 1.2,
                        py: 0.5,
                        bgcolor: "#e0e7ff",
                        color: "#312e81",
                        borderRadius: 999,
                        fontWeight: 700,
                      }}
                    >
                      {d}
                    </Box>
                  ))}
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  Point the camera at each dryer QR. No duplicates. Need {dryerCount - dryers.length} more.
                </Typography>
                <TextField
                  size="small"
                  label="Or type dryer code"
                  value={manualCode}
                  onChange={(e) => setManualCode(e.target.value)}
                />
                <Button
                  variant="outlined"
                  disabled={busy || !manualCode.trim()}
                  onClick={() => onScanDryer(manualCode).then(() => setManualCode(""))}
                >
                  Add code
                </Button>
              </Stack>
            </Box>
          </Stack>
        )}

        {step === 3 && (
          <Stack spacing={2} sx={{ flex: 1, px: 1, py: 2, maxWidth: 480, mx: "auto", width: "100%" }}>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Ticket photo
            </Typography>
            <Typography color="text.secondary">
              {isSimpleSession
                ? "Take or upload one clear ticket photo. Next you will mark the order complete and enter weight."
                : "Take or upload one clear photo of the ticket — the flow finishes as soon as it is saved."}
            </Typography>
            <Button variant="contained" component="label" startIcon={<CameraAlt />} disabled={busy} sx={{ py: 2, borderRadius: 2 }}>
              {busy ? "Saving…" : "Choose / capture photo"}
              <input
                hidden
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(e) => {
                  const file = e.target.files?.[0] || null;
                  e.target.value = "";
                  if (file) completeTicketWithFile(file);
                }}
              />
            </Button>
          </Stack>
        )}

        {step === 4 && isSimpleSession && (
          <Stack spacing={2.5} sx={{ flex: 1, px: 1, py: 2, maxWidth: 440, mx: "auto", width: "100%" }}>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Mark complete
            </Typography>
            <Typography color="text.secondary">
              Ticket photo is saved on this device for this session. Continue to enter ticket weight and send to the
              server.
            </Typography>
            <Button
              variant="contained"
              size="large"
              startIcon={<CheckCircle />}
              disabled={!pendingTicketB64}
              onClick={() => setStep(5)}
              sx={{ borderRadius: 999, py: 1.6, fontWeight: 700 }}
            >
              Mark complete
            </Button>
          </Stack>
        )}

        {step === 5 && isSimpleSession && (
          <Stack spacing={2.5} sx={{ flex: 1, px: 1, py: 2, maxWidth: 440, mx: "auto", width: "100%" }}>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Ticket weight
            </Typography>
            <Typography color="text.secondary">
              Adjust if needed, then finish. Units: {isHdRow(sessionOrder) ? "pieces" : "lb"}.
            </Typography>
            <Paper
              elevation={0}
              sx={{
                p: 2,
                borderRadius: 3,
                border: "1px solid #e2e8f0",
                bgcolor: "#fff",
              }}
            >
              <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
                <Button variant="outlined" size="large" onClick={() => bumpWeight(-1)} sx={{ minWidth: 56, minHeight: 56 }}>
                  <Remove />
                </Button>
                <Typography sx={{ fontSize: 36, fontWeight: 800, textAlign: "center", flex: 1 }}>
                  {isHdRow(sessionOrder) ? Math.round(Number(weightInput) || 0) : Number(weightInput || 0).toFixed(2)}
                </Typography>
                <Button variant="outlined" size="large" onClick={() => bumpWeight(1)} sx={{ minWidth: 56, minHeight: 56 }}>
                  <Add />
                </Button>
              </Stack>
            </Paper>
            <Button
              variant="contained"
              size="large"
              disabled={busy || !pendingTicketB64}
              onClick={submitSimpleComplete}
              sx={{ borderRadius: 999, py: 1.6, fontWeight: 700 }}
            >
              Finish order
            </Button>
          </Stack>
        )}
      </Box>

      {completedFlash ? (
        <Box
          sx={{
            position: "fixed",
            inset: 0,
            zIndex: 2000,
            bgcolor: "rgba(15, 23, 42, 0.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            px: 2,
          }}
        >
          <Typography sx={{ color: "#f8fafc", fontWeight: 800, fontSize: "1.35rem", letterSpacing: 0.04 }}>
            Completed
          </Typography>
        </Box>
      ) : null}
    </Box>
  );
}
