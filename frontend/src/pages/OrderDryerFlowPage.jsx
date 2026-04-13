import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Add, CameraAlt, Remove } from "@mui/icons-material";
import { Html5Qrcode } from "html5-qrcode";
import { useNavigate, useParams } from "react-router-dom";
import StandardScreenHeader from "../components/layout/StandardScreenHeader";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import {
  cancelOrderGamingSession,
  completeOrderGamingTicket,
  getOrderGamingSession,
  scanOrderGamingDryer,
  startOrderGamingSession,
} from "../api";

const READER_ID = "dryer-qr-reader";

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

export default function OrderDryerFlowPage({ user }) {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { logout } = useAuth();
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
  const scannerRef = useRef(null);
  const startedRef = useRef(false);

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
            const n = Number(d.gaming_dryer_count) || 1;
            setDryerCount(n);
            const list = Array.isArray(d.gaming_dryers) ? d.gaming_dryers : [];
            setDryers(list);
            if (list.length >= n) setStep(3);
            else setStep(2);
            setLoading(false);
            return;
          }
        }
        setStep(1);
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
    if (step !== 2 || !lockToken) return undefined;
    let cancelled = false;
    startedRef.current = false;

    const run = async () => {
      await stopScanner();
      if (cancelled) return;
      const el = document.getElementById(READER_ID);
      if (!el) return;
      const html5 = new Html5Qrcode(READER_ID);
      scannerRef.current = html5;
      try {
        await html5.start(
          { facingMode: "environment" },
          { fps: 8, qrbox: { width: 260, height: 260 } },
          async (text) => {
            if (startedRef.current) return;
            const t = String(text || "").trim();
            if (!t) return;
            startedRef.current = true;
            try {
              await onScanDryer(t);
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
      setStep(2);
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
      await completeOrderGamingTicket(oid, {
        lock_token: lockToken,
        ticket_image_base64: b64,
        ticket_file_name: file.name,
      });
      navigate("/orders", { replace: true });
    } catch (e) {
      window.alert(e?.response?.data?.error || "Upload failed");
    } finally {
      setBusy(false);
    }
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
        <StandardScreenHeader title={t("ops.dryerFlowTitle")} dense onBack={() => navigate(-1)} onLogout={logout} />
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
        <StandardScreenHeader title={t("ops.dryerFlowTitle")} dense onBack={() => navigate("/orders")} onLogout={logout} />
        <Alert severity="info" sx={{ mt: 2 }}>
          Dryer assignment is already completed for this order. Add or replace the ticket photo from Upload → Live orders for this batch if needed.
        </Alert>
      </Box>
    );
  }

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
      }}
    >
      <StandardScreenHeader
        title={`${t("ops.dryerFlowTitle")} #${oid}`}
        dense
        onBack={onCancelFlow}
        homePath="/orders"
        onLogout={logout}
      />

      {step === 1 && (
        <Stack spacing={2} sx={{ flex: 1, px: 2, py: 3, maxWidth: 420, mx: "auto", width: "100%" }}>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            How many Dryers?
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
        </Stack>
      )}

      {step === 2 && (
        <Stack sx={{ flex: 1, px: 1.5, py: 1, overflow: "hidden" }}>
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
            <Box
              id={READER_ID}
              sx={{
                borderRadius: 2,
                overflow: "hidden",
                bgcolor: "#000",
                minHeight: { xs: 220, sm: 320 },
                border: "2px solid #e2e8f0",
              }}
            />
            <Stack spacing={1.2} sx={{ p: 1, bgcolor: "#fff", borderRadius: 2, border: "1px solid #e2e8f0" }}>
              <Typography sx={{ fontWeight: 600 }}>Dryers ({dryers.length} / {dryerCount})</Typography>
              <Stack direction="row" flexWrap="wrap" gap={0.75}>
                {dryers.map((d) => (
                  <Box key={d} sx={{ px: 1.2, py: 0.5, bgcolor: "#dcfce7", borderRadius: 999, fontWeight: 700 }}>
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
              <Button variant="outlined" disabled={busy || !manualCode.trim()} onClick={() => onScanDryer(manualCode).then(() => setManualCode(""))}>
                Add code
              </Button>
            </Stack>
          </Box>
        </Stack>
      )}

      {step === 3 && (
        <Stack spacing={2} sx={{ flex: 1, px: 2, py: 3, maxWidth: 480, mx: "auto", width: "100%" }}>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Ticket photo
          </Typography>
          <Typography color="text.secondary">Take or upload one clear photo of the ticket — the flow finishes as soon as it is saved.</Typography>
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
    </Box>
  );
}
