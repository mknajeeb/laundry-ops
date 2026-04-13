import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItemButton,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { PhotoCamera } from "@mui/icons-material";
import { createWorker } from "tesseract.js";
import { useI18n } from "../i18n/I18nContext";
import { lookupOrdersByScan } from "../api";

/** Parse Rinse-style tag: name (+ address), then QR block, then WASH & FOLD / HANG DRY at bottom. */
export function parseTagOcrText(raw) {
  const lines = String(raw || "")
    .split(/\r?\n/)
    .map((l) => l.replace(/\|/g, "I").trim())
    .filter((l) => l.length > 1);

  const blob = lines.join("\n");
  let service = "";
  if (/\bhang\s*[-&]?\s*dry\b|\bhang\s+dry\b|\bHD\b/i.test(blob)) {
    service = "Hang dry";
  } else if (/\bwash\s*&\s*fold\b|\bwash\s+and\s+fold\b|\bwash\s*[- ]?\s*fold\b|\bWF\b/i.test(blob)) {
    service = "Wash & fold";
  }

  const nameLines = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^(wash|hang)\b/i.test(l) && l.length < 40) {
      break;
    }
    if (/^\d{2,5}\s+[\w\s#.',-]+(ave|avenue|st\b|street|road|rd\b|blvd|dr\b|way|ln\b|ct\b)/i.test(l)) {
      break;
    }
    if (/^[A-Z0-9]{24,}$/.test(l.replace(/\s/g, ""))) {
      break;
    }
    if (/^[a-zA-Z]/.test(l) && !/^(wash|hang)\s/i.test(l)) {
      nameLines.push(l);
    } else if (nameLines.length && /^[\d#]/.test(l)) {
      break;
    }
  }

  let name = nameLines.slice(0, 2).join(" ").replace(/\s+/g, " ").trim();
  if (!name && lines[0] && !/^(wash|hang)\b/i.test(lines[0])) {
    name = lines[0].replace(/\s+/g, " ").trim();
  }

  return { name, service };
}

function buildLookupBodies(nameHint, serviceHint, batchStr) {
  const nh0 = String(nameHint || "").trim();
  const sh0 = String(serviceHint || "").trim();
  const bd = String(batchStr || "").trim().slice(0, 10);
  const batchOk = /^\d{4}-\d{2}-\d{2}$/.test(bd);
  const base = { qr_text: "", name_hint: nh0, service_hint: sh0 };
  const bodies = [];
  if (batchOk) {
    bodies.push({ ...base, batch_date: bd });
  }
  bodies.push({ ...base });
  const seen = new Set();
  return bodies.filter((b) => {
    const k = JSON.stringify(b);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

export default function OrderScanLookupBar({ storageKey, onPickOrder, disabled, batchDate }) {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState(() => localStorage.getItem(storageKey) === "1");
  const [open, setOpen] = useState(false);
  const [nameHint, setNameHint] = useState("");
  const [serviceHint, setServiceHint] = useState("");
  const [busy, setBusy] = useState(false);
  const [pickList, setPickList] = useState(null);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const workerRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(storageKey, enabled ? "1" : "0");
  }, [enabled, storageKey]);

  const terminateWorker = useCallback(async () => {
    const w = workerRef.current;
    workerRef.current = null;
    if (w) {
      try {
        await w.terminate();
      } catch {
        /* */
      }
    }
  }, []);

  const stopCamera = useCallback(() => {
    const s = streamRef.current;
    streamRef.current = null;
    if (s) {
      try {
        s.getTracks().forEach((tr) => tr.stop());
      } catch {
        /* */
      }
    }
    const v = videoRef.current;
    if (v) {
      v.srcObject = null;
    }
  }, []);

  useEffect(() => {
    if (!open) {
      stopCamera();
      void terminateWorker();
      setNameHint("");
      setServiceHint("");
      return undefined;
    }
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((tr) => tr.stop());
          return;
        }
        streamRef.current = stream;
        const v = videoRef.current;
        if (v) {
          v.srcObject = stream;
          await v.play().catch(() => {});
        }
      } catch {
        /* no camera */
      }
    })();
    return () => {
      cancelled = true;
      stopCamera();
    };
  }, [open, stopCamera]);

  const runOrderLookup = useCallback(
    async (nh, sh) => {
      const bd = String(batchDate || "").trim().slice(0, 10);
      const bodies = buildLookupBodies(nh, sh, bd);
      let lastErr = null;
      for (const body of bodies) {
        try {
          const res = await lookupOrdersByScan(body);
          const matches = Array.isArray(res.data?.matches) ? res.data.matches : [];
          if (matches.length === 1) {
            setOpen(false);
            onPickOrder(matches[0]);
            return true;
          }
          if (matches.length > 1) {
            setPickList(matches);
            return true;
          }
        } catch (e) {
          lastErr = e;
        }
      }
      if (lastErr) {
        window.alert(lastErr?.response?.data?.error || t("ops.scanAlertLookupFailed"));
        return false;
      }
      window.alert(t("ops.scanAlertNoMatch"));
      return false;
    },
    [batchDate, onPickOrder, t]
  );

  const captureAndOcr = useCallback(async () => {
    const video = videoRef.current;
    if (!video || video.readyState < 2 || !video.videoWidth) {
      return { name: "", service: "", noVideo: true };
    }
    const w = video.videoWidth;
    const h = video.videoHeight;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return { name: "", service: "", noVideo: true };
    }
    ctx.drawImage(video, 0, 0, w, h);
    if (!workerRef.current) {
      workerRef.current = await createWorker("eng");
    }
    const {
      data: { text },
    } = await workerRef.current.recognize(canvas);
    return { ...parseTagOcrText(text), noVideo: false };
  }, []);

  const onPrimary = useCallback(async () => {
    setBusy(true);
    try {
      const hasBoth = nameHint.trim() && serviceHint.trim();
      if (!hasBoth) {
        const parsed = await captureAndOcr();
        if (parsed.noVideo) {
          window.alert(t("ops.tagNoVideo"));
          return;
        }
        const nNext = (parsed.name || nameHint).trim();
        const sNext = (parsed.service || serviceHint).trim();
        if (parsed.name) {
          setNameHint(parsed.name);
        }
        if (parsed.service) {
          setServiceHint(parsed.service);
        }
        if (nNext && sNext) {
          await runOrderLookup(nNext, sNext);
          return;
        }
        if (!nNext) {
          window.alert(t("ops.tagOcrNoName"));
          return;
        }
        window.alert(t("ops.tagOcrNoService"));
        return;
      }
      await runOrderLookup(nameHint.trim(), serviceHint.trim());
    } finally {
      setBusy(false);
    }
  }, [captureAndOcr, nameHint, serviceHint, runOrderLookup, t]);

  useEffect(() => {
    return () => {
      void terminateWorker();
      stopCamera();
    };
  }, [stopCamera, terminateWorker]);

  const primaryLabel =
    nameHint.trim() && serviceHint.trim() ? t("ops.tagFindOrder") : t("ops.tagReadButton");

  return (
    <Box sx={{ mt: 0.75 }}>
      <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
        <Stack direction="row" alignItems="center" spacing={0.5}>
          <Switch checked={enabled} onChange={(_, v) => setEnabled(v)} disabled={disabled} color="primary" size="medium" />
          <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#334155" }}>{t("ops.scanToggleLabel")}</Typography>
        </Stack>
        {enabled && (
          <Button
            variant="contained"
            color="primary"
            startIcon={<PhotoCamera />}
            onClick={() => setOpen(true)}
            disabled={disabled}
            sx={{
              borderRadius: 2,
              textTransform: "none",
              fontWeight: 700,
              minHeight: 48,
              px: 2,
              boxShadow: "0 4px 14px rgba(37, 99, 235, 0.28)",
            }}
          >
            {t("ops.scanBagButton")}
          </Button>
        )}
      </Stack>

      <Dialog open={open} onClose={() => !busy && setOpen(false)} fullWidth maxWidth="sm" aria-labelledby="tag-read-title">
        <DialogTitle id="tag-read-title" sx={{ fontWeight: 700, py: 1.5, px: 2 }}>
          {t("ops.tagDialogTitle")}
        </DialogTitle>
        <DialogContent sx={{ px: 2, pt: 0, pb: 2 }}>
          <Stack spacing={1.5}>
            <Box
              sx={{
                borderRadius: 2,
                overflow: "hidden",
                bgcolor: "#0f172a",
                minHeight: 280,
                position: "relative",
              }}
            >
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                style={{ width: "100%", height: 280, objectFit: "cover", display: "block" }}
              />
            </Box>
            <TextField
              label={t("ops.scanNameLabel")}
              value={nameHint}
              onChange={(e) => setNameHint(e.target.value)}
              size="small"
              fullWidth
              autoComplete="off"
            />
            <TextField
              select
              label={t("ops.scanServiceLabel")}
              value={serviceHint}
              onChange={(e) => setServiceHint(e.target.value)}
              InputLabelProps={{ shrink: true }}
              SelectProps={{
                displayEmpty: true,
                renderValue: (selected) => {
                  if (!selected) return "—";
                  const labels = {
                    "Wash & fold": t("ops.svcWashFold"),
                    "Wash and fold": t("ops.svcWashAndFold"),
                    "Hang dry": t("ops.svcHangDry"),
                    WF: "WF",
                    HD: "HD",
                  };
                  return labels[selected] || selected;
                },
              }}
              size="small"
              fullWidth
            >
              <MenuItem value="">—</MenuItem>
              <MenuItem value="Wash & fold">{t("ops.svcWashFold")}</MenuItem>
              <MenuItem value="Wash and fold">{t("ops.svcWashAndFold")}</MenuItem>
              <MenuItem value="Hang dry">{t("ops.svcHangDry")}</MenuItem>
              <MenuItem value="WF">WF</MenuItem>
              <MenuItem value="HD">HD</MenuItem>
            </TextField>
            <Button
              variant="contained"
              size="large"
              onClick={onPrimary}
              disabled={busy || disabled}
              sx={{ py: 1.5, fontWeight: 700 }}
            >
              {busy ? <CircularProgress size={22} color="inherit" /> : primaryLabel}
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={() => setOpen(false)} disabled={busy}>
            {t("ops.scanClose")}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(pickList?.length)} onClose={() => setPickList(null)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 700 }}>{t("ops.scanPickOrder")}</DialogTitle>
        <DialogContent dividers>
          <List dense>
            {pickList?.map((m) => (
              <ListItemButton
                key={m.id}
                onClick={() => {
                  setPickList(null);
                  setOpen(false);
                  onPickOrder(m);
                }}
              >
                <Stack>
                  <Typography fontWeight={700}>{m.name_clean}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    #{m.id} • {String(m.date_clean || "").slice(0, 10)} • {m.service_type} • {m.weight_num}
                  </Typography>
                </Stack>
              </ListItemButton>
            ))}
          </List>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPickList(null)}>{t("common.cancel")}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
