import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  List,
  ListItemButton,
  MenuItem,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { PhotoCamera, QrCodeScanner } from "@mui/icons-material";
import { Html5Qrcode } from "html5-qrcode";
import { createWorker, PSM } from "tesseract.js";
import { useI18n } from "../i18n/I18nContext";
import { lookupOrdersByScan } from "../api";
import { displayCustomerName } from "../utils/displayCustomerName";

function cropCanvasFraction(src, y0Frac, y1Frac) {
  const y0 = Math.max(0, Math.floor(src.height * y0Frac));
  const y1 = Math.min(src.height, Math.ceil(src.height * y1Frac));
  const ch = Math.max(1, y1 - y0);
  const c = document.createElement("canvas");
  c.width = src.width;
  c.height = ch;
  const x = c.getContext("2d");
  if (!x) return src;
  x.drawImage(src, 0, y0, src.width, ch, 0, 0, src.width, ch);
  return c;
}

/** Grayscale + contrast + light upscale so small tag text survives phone video. */
function enhanceForOcr(src) {
  const maxSide = 1400;
  const scale = Math.min(2.2, maxSide / Math.max(src.width, src.height));
  const tw = Math.max(1, Math.round(src.width * scale));
  const th = Math.max(1, Math.round(src.height * scale));
  const c = document.createElement("canvas");
  c.width = tw;
  c.height = th;
  const ctx = c.getContext("2d");
  if (!ctx) return src;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(src, 0, 0, tw, th);
  const img = ctx.getImageData(0, 0, tw, th);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    const v = y < 115 ? 0 : y > 195 ? 255 : ((y - 115) / 80) * 255;
    const q = v < 0 ? 0 : v > 255 ? 255 : v;
    d[i] = d[i + 1] = d[i + 2] = q;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

function extractLinesFromPage(data, source = "") {
  const out = [];
  const blocks = data?.blocks || [];
  for (const b of blocks) {
    for (const par of b.paragraphs || []) {
      for (const ln of par.lines || []) {
        const text = String(ln.text || "")
          .replace(/\|/g, "I")
          .replace(/[“”]/g, '"')
          .trim();
        if (text.length < 2) continue;
        out.push({
          text,
          confidence: typeof ln.confidence === "number" ? ln.confidence : 0,
          y: ln.bbox?.y0 ?? 0,
          source,
        });
      }
    }
  }
  return out;
}

function linesFromPlainText(raw) {
  return String(raw || "")
    .split(/\r?\n/)
    .map((l) => l.replace(/\|/g, "I").trim())
    .filter((l) => l.length > 1)
    .map((text, i) => ({ text, confidence: 45, y: i * 10, source: "" }));
}

function sourceRank(src) {
  if (src === "bottom") return 2;
  if (src === "full") return 1;
  if (src === "top") return 1;
  return 0;
}

function mergeLineLists(lists) {
  const map = new Map();
  for (const list of lists) {
    for (const ln of list) {
      const k = ln.text.toLowerCase().replace(/\s+/g, " ").slice(0, 80);
      const prev = map.get(k);
      const nc = ln.confidence || 0;
      const pc = prev?.confidence || 0;
      const better =
        !prev ||
        nc > pc ||
        (nc === pc && sourceRank(ln.source) > sourceRank(prev.source));
      if (better) {
        map.set(k, { ...ln });
      }
    }
  }
  return [...map.values()];
}

/** Rinse tags: QR + WASH & FOLD often top; address middle; customer name bottom (sometimes upside down). */
export function sniffServiceFromOcrBlob(blob) {
  const s = String(blob || "")
    .replace(/\s+/g, " ")
    .toUpperCase();
  if (/\bHANG\b.*\bDRY\b|\bHANG\s*[-&+]+\s*DRY\b|\bHD\b/i.test(s)) {
    return "Hang dry";
  }
  if (/\bWASH\b.*\bFOLD\b|\bW[A@4*]SH\b.*\bF[O0]LD\b|\bWASH\s*[&+]\s*FOLD\b|\bWASH\s+AND\s+FOLD\b|\bWF\b/i.test(s)) {
    return "Wash & fold";
  }
  if (s.includes("WASH") && s.includes("FOLD")) {
    return "Wash & fold";
  }
  if (s.includes("HANG") && s.includes("DRY")) {
    return "Hang dry";
  }
  return "";
}

function isProbablePersonName(text) {
  const t = String(text || "").trim();
  if (t.length < 5 || t.length > 56) return false;
  if (/[0-9#@]/.test(t)) return false;
  if (/[(){}\[\]\\/:;%]/.test(t)) return false;
  if (/^(wash|hang|fold|dry|rinse|bag)\b/i.test(t)) return false;
  if (/\b(ave|avenue|st\b|street|road|rd\b|blvd|blv|ln\b|ct\b|pl\b|suite|apt)\b/i.test(t)) {
    return false;
  }
  const parts = t.split(/\s+/).filter(Boolean);
  if (parts.length < 2 || parts.length > 4) return false;
  return parts.every((p) => /^[A-Za-z\u00C0-\u024F'-]+$/u.test(p) && p.length >= 2);
}

/** Prefer bottom-crop lines, then confidence; fall back to First Last anywhere in raw text. */
export function parseTagOcrStructured(lines, rawFallback) {
  const blob = lines.map((l) => l.text).join("\n");
  let service = sniffServiceFromOcrBlob(blob);
  if (!service && rawFallback) {
    service = sniffServiceFromOcrBlob(rawFallback);
  }

  const fromLines = mergeLineLists([lines]);
  const nameCands = fromLines
    .filter((l) => isProbablePersonName(l.text))
    .sort((a, b) => {
      const pref = sourceRank(b.source) - sourceRank(a.source);
      if (pref) return pref;
      return (b.confidence || 0) - (a.confidence || 0) || (b.y || 0) - (a.y || 0);
    });

  let name = nameCands[0]?.text?.trim() || "";
  if (!name && rawFallback) {
    const raw = String(rawFallback);
    const hits = raw.match(/\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})\b/g);
    if (hits) {
      const ok = hits.filter((h) => isProbablePersonName(h));
      ok.sort((a, b) => b.length - a.length);
      if (ok[0]) {
        name = ok[0].trim();
      }
    }
  }
  return { name, service };
}

/** @deprecated use parseTagOcrStructured; kept for tests */
export function parseTagOcrText(raw) {
  return parseTagOcrStructured(linesFromPlainText(raw), raw);
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

function buildLookupBodiesForQr(qrText, batchStr) {
  const qr = String(qrText || "").trim();
  if (!qr) return [];
  const bd = String(batchStr || "").trim().slice(0, 10);
  const batchOk = /^\d{4}-\d{2}-\d{2}$/.test(bd);
  const base = { qr_text: qr, name_hint: "", service_hint: "" };
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

const dialogTabKey = (storageKey) => `${storageKey}_dialog_tab`;

export default function OrderScanLookupBar({
  storageKey,
  onPickOrder,
  disabled,
  batchDate,
  variant = "dialog",
  /** Parent-controlled scan on/off (parent should persist). Omit to use `storageKey` in localStorage. */
  scanEnabled: scanEnabledProp,
  onScanEnabledChange,
  /** Embedded: strip paste / lookup / tag / idle line; parent supplies toolbar toggles. */
  compactEmbedded = false,
}) {
  const { t } = useI18n();
  const isEmbedded = variant === "embedded";
  const fullScreenDialog = useMediaQuery("(max-width:600px)");
  const readerId = `order-scan-qr-${storageKey.replace(/[^a-z0-9_-]/gi, "-")}`;
  const scanIsControlled = typeof scanEnabledProp === "boolean" && typeof onScanEnabledChange === "function";
  const [internalScanEnabled, setInternalScanEnabled] = useState(() => localStorage.getItem(storageKey) !== "0");
  const enabled = scanIsControlled ? scanEnabledProp : internalScanEnabled;
  const setEnabled = (v) => {
    if (scanIsControlled) onScanEnabledChange(v);
    else setInternalScanEnabled(v);
  };
  const [open, setOpen] = useState(false);
  const [ocrDialogOpen, setOcrDialogOpen] = useState(false);
  const [dialogTab, setDialogTab] = useState(() => localStorage.getItem(dialogTabKey(storageKey)) || "qr");
  const [nameHint, setNameHint] = useState("");
  const [serviceHint, setServiceHint] = useState("");
  const [qrPaste, setQrPaste] = useState("");
  const [busy, setBusy] = useState(false);
  const [pickList, setPickList] = useState(null);
  const [scanStatus, setScanStatus] = useState("");
  const [qrRemount, setQrRemount] = useState(0);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const workerRef = useRef(null);
  const scannerRef = useRef(null);
  const qrDecodeLockRef = useRef(false);
  const lastQrPayloadRef = useRef({ text: "", at: 0 });
  const hadPickListRef = useRef(false);

  useEffect(() => {
    if (scanIsControlled) return;
    localStorage.setItem(storageKey, enabled ? "1" : "0");
  }, [enabled, storageKey, scanIsControlled]);

  useEffect(() => {
    if (open || ocrDialogOpen) {
      localStorage.setItem(dialogTabKey(storageKey), dialogTab);
    }
  }, [dialogTab, open, ocrDialogOpen, storageKey]);

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

  const stopQrScanner = useCallback(async () => {
    const h = scannerRef.current;
    scannerRef.current = null;
    if (!h) return;
    try {
      await h.stop();
    } catch {
      /* */
    }
    try {
      await h.clear();
    } catch {
      /* */
    }
  }, []);

  const runBodies = useCallback(
    async (bodies) => {
      if (!bodies.length) {
        window.alert(t("ops.scanAlertNeedInput"));
        return "resume";
      }
      let lastErr = null;
      for (const body of bodies) {
        try {
          const res = await lookupOrdersByScan(body);
          const matches = Array.isArray(res.data?.matches) ? res.data.matches : [];
          if (matches.length === 1) {
            if (!isEmbedded) {
              setOpen(false);
            }
            setOcrDialogOpen(false);
            onPickOrder(matches[0]);
            return "single";
          }
          if (matches.length > 1) {
            setPickList(matches);
            return "pick";
          }
        } catch (e) {
          lastErr = e;
        }
      }
      if (lastErr) {
        window.alert(lastErr?.response?.data?.error || t("ops.scanAlertLookupFailed"));
        return "resume";
      }
      const usedQr = bodies.some((b) => String(b.qr_text || "").trim());
      window.alert(usedQr ? t("ops.scanAlertNoMatchQr") : t("ops.scanAlertNoMatch"));
      return "resume";
    },
    [isEmbedded, onPickOrder, t]
  );

  const runOrderLookup = useCallback(
    async (nh, sh) => {
      const bodies = buildLookupBodies(nh, sh, batchDate);
      return runBodies(bodies);
    },
    [batchDate, runBodies]
  );

  const onPasteQrLookup = useCallback(async () => {
    setBusy(true);
    setScanStatus(t("ops.scanStatusLooking"));
    try {
      await runBodies(buildLookupBodiesForQr(qrPaste, batchDate));
    } finally {
      setBusy(false);
      setScanStatus("");
    }
  }, [batchDate, qrPaste, runBodies, t]);

  const ocrCameraActive =
    (ocrDialogOpen && dialogTab === "ocr") || (!isEmbedded && open && dialogTab === "ocr");

  useEffect(() => {
    if (!ocrCameraActive) {
      stopCamera();
      void terminateWorker();
      if (!ocrDialogOpen && !open) {
        setNameHint("");
        setServiceHint("");
        setQrPaste("");
      }
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
  }, [ocrCameraActive, ocrDialogOpen, open, stopCamera]);

  const qrActiveEmbedded = isEmbedded && enabled && !disabled && dialogTab === "qr" && !ocrDialogOpen;
  const qrActiveDialog = !isEmbedded && open && dialogTab === "qr";

  useEffect(() => {
    if (!qrActiveEmbedded && !qrActiveDialog) {
      void stopQrScanner();
      return undefined;
    }
    let cancelled = false;
    qrDecodeLockRef.current = false;

    const onDecoded = async (decodedText) => {
      if (disabled || qrDecodeLockRef.current) return;
      const raw = String(decodedText || "").trim();
      if (!raw) return;
      const now = Date.now();
      if (lastQrPayloadRef.current.text === raw && now - lastQrPayloadRef.current.at < 4000) {
        return;
      }
      lastQrPayloadRef.current = { text: raw, at: now };

      const html5 = scannerRef.current;
      qrDecodeLockRef.current = true;
      try {
        if (html5) {
          try {
            html5.pause(true);
          } catch {
            /* */
          }
        }
        setScanStatus(t("ops.scanStatusLooking"));
        const outcome = await runBodies(buildLookupBodiesForQr(raw, batchDate));
        setScanStatus("");
        if (outcome === "resume") {
          const h = scannerRef.current;
          if (h) {
            try {
              h.resume();
            } catch {
              setQrRemount((n) => n + 1);
            }
          }
        } else if (outcome === "single") {
          await stopQrScanner();
        }
      } finally {
        qrDecodeLockRef.current = false;
      }
    };

    const run = async () => {
      await stopQrScanner();
      if (cancelled) return;
      // First paint often has 0×0 reader bounds; html5-qrcode then mis-draws the viewfinder until a remount.
      for (let attempt = 0; attempt < 24; attempt += 1) {
        if (cancelled) return;
        const probe = document.getElementById(readerId);
        if (probe) {
          const rect = probe.getBoundingClientRect();
          if (rect.width >= 120 && rect.height >= 120) break;
        }
        await new Promise((r) => window.setTimeout(r, 50));
      }
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      if (cancelled) return;
      const el = document.getElementById(readerId);
      if (!el) return;
      const html5 = new Html5Qrcode(readerId);
      scannerRef.current = html5;
      try {
        await html5.start(
          { facingMode: { ideal: "environment" } },
          {
            fps: 6,
            qrbox: (vw, vh) => {
              const w = Number(vw) || 300;
              const h = Number(vh) || 300;
              const side = Math.max(160, Math.min(280, Math.floor(Math.min(w, h) * 0.72)));
              return { width: side, height: side };
            },
          },
          onDecoded,
          () => {}
        );
      } catch {
        /* camera blocked */
      }
    };
    run();
    return () => {
      cancelled = true;
      void stopQrScanner();
    };
  }, [
    qrActiveEmbedded,
    qrActiveDialog,
    readerId,
    batchDate,
    runBodies,
    stopQrScanner,
    disabled,
    t,
    qrRemount,
  ]);

  useEffect(() => {
    if (pickList?.length) {
      hadPickListRef.current = true;
      return;
    }
    if (!hadPickListRef.current) return;
    hadPickListRef.current = false;
    const h = scannerRef.current;
    if (!h) return;
    if (!(qrActiveEmbedded || qrActiveDialog)) return;
    try {
      h.resume();
    } catch {
      setQrRemount((n) => n + 1);
    }
  }, [pickList, qrActiveEmbedded, qrActiveDialog]);

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
    const worker = workerRef.current;
    await worker.setParameters({
      tessedit_pageseg_mode: PSM.SINGLE_BLOCK,
      user_defined_dpi: "240",
    });

    const full = enhanceForOcr(canvas);
    const top = enhanceForOcr(cropCanvasFraction(canvas, 0, 0.42));
    const bottom = enhanceForOcr(cropCanvasFraction(canvas, 0.44, 1));

    const texts = [];
    const allLines = [];

    for (const [img, src] of [
      [full, "full"],
      [top, "top"],
      [bottom, "bottom"],
    ]) {
      const { data } = await worker.recognize(img, { rotateAuto: true }, { blocks: true, text: true });
      texts.push(data.text || "");
      let lines = extractLinesFromPage(data, src);
      if (!lines.length && data.text) {
        lines = linesFromPlainText(data.text).map((l) => ({ ...l, source: src }));
      }
      allLines.push(...lines);
    }

    const rawFallback = texts.join("\n");
    const merged = mergeLineLists([allLines]);
    return { ...parseTagOcrStructured(merged, rawFallback), noVideo: false };
  }, []);

  const onPrimaryOcr = useCallback(async () => {
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
      void stopQrScanner();
    };
  }, [stopCamera, stopQrScanner, terminateWorker]);

  const primaryOcrLabel =
    nameHint.trim() && serviceHint.trim() ? t("ops.tagFindOrder") : t("ops.tagReadButton");

  const closeMainDialog = async () => {
    if (busy) return;
    await stopQrScanner();
    setOpen(false);
  };

  const closeOcrDialog = async () => {
    if (busy) return;
    stopCamera();
    await terminateWorker();
    setOcrDialogOpen(false);
  };

  const openTagReader = () => {
    setDialogTab("ocr");
    if (isEmbedded) {
      setOcrDialogOpen(true);
    }
  };

  const scanSurface = compactEmbedded ? (
    <Stack spacing={0.5} sx={{ width: "100%" }}>
      <Box
        sx={{
          borderRadius: 2,
          overflow: "hidden",
          bgcolor: "#0f172a",
          minHeight: { xs: "36vh", sm: 260 },
          maxHeight: { xs: "46vh", sm: 360 },
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Box
          key={`${readerId}-${qrRemount}`}
          id={readerId}
          sx={{ width: "100%", height: "100%", minHeight: { xs: "36vh", sm: 260 } }}
        />
      </Box>
      {scanStatus ? (
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: "center", minHeight: 18 }}>
          {scanStatus}
        </Typography>
      ) : null}
    </Stack>
  ) : (
    <Stack spacing={1} sx={{ width: "100%" }}>
      <Box
        sx={{
          borderRadius: 2,
          overflow: "hidden",
          bgcolor: "#0f172a",
          minHeight: { xs: "38vh", sm: 260 },
          maxHeight: { xs: "48vh", sm: 360 },
          position: "relative",
        }}
      >
        <Box key={`${readerId}-${qrRemount}`} id={readerId} sx={{ width: "100%", height: "100%", minHeight: { xs: "38vh", sm: 260 } }} />
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ minHeight: 22 }}>
        {scanStatus || (isEmbedded ? t("ops.scanStatusIdle") : "")}
      </Typography>
      <TextField
        label={t("ops.scanPasteBagCode")}
        value={qrPaste}
        onChange={(e) => setQrPaste(e.target.value)}
        size="small"
        fullWidth
        autoComplete="off"
      />
      <Button
        variant="contained"
        size="large"
        onClick={onPasteQrLookup}
        disabled={busy || disabled || !qrPaste.trim()}
        sx={{ py: 1.25, fontWeight: 700 }}
      >
        {busy ? <CircularProgress size={22} color="inherit" /> : t("ops.scanLookUp")}
      </Button>
      <Link component="button" type="button" variant="body2" onClick={openTagReader} sx={{ alignSelf: "flex-start", cursor: "pointer" }}>
        {t("ops.scanOpenTagOcr")}
      </Link>
    </Stack>
  );

  if (isEmbedded) {
    return (
      <Box sx={{ mt: compactEmbedded ? 0.75 : 0.5 }}>
        {!compactEmbedded ? (
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
            <Switch checked={enabled} onChange={(_, v) => setEnabled(v)} disabled={disabled} color="primary" size="medium" />
            <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#334155" }}>{t("ops.scanToggleLabel")}</Typography>
          </Stack>
        ) : null}
        {enabled && !disabled ? scanSurface : null}

        <Dialog open={ocrDialogOpen} onClose={closeOcrDialog} fullWidth maxWidth="sm" fullScreen={fullScreenDialog}>
          <DialogTitle sx={{ fontWeight: 700, py: 1 }}>{t("ops.tagDialogTitle")}</DialogTitle>
          <DialogContent sx={{ px: 2, pt: 0, pb: 2 }}>
            <Stack spacing={1.25}>
              <Box
                sx={{
                  borderRadius: 2,
                  overflow: "hidden",
                  bgcolor: "#0f172a",
                  minHeight: 220,
                  maxHeight: "40vh",
                }}
              >
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  style={{ width: "100%", height: "100%", minHeight: 220, objectFit: "cover", display: "block" }}
                />
              </Box>
              <TextField label={t("ops.scanNameLabel")} value={nameHint} onChange={(e) => setNameHint(e.target.value)} size="small" fullWidth autoComplete="off" />
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
              <Button variant="contained" size="large" startIcon={<PhotoCamera />} onClick={onPrimaryOcr} disabled={busy || disabled} sx={{ py: 1.25, fontWeight: 700 }}>
                {busy ? <CircularProgress size={22} color="inherit" /> : primaryOcrLabel}
              </Button>
            </Stack>
          </DialogContent>
          <DialogActions sx={{ px: 2, pb: 2 }}>
            <Button onClick={closeOcrDialog} disabled={busy}>
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
                    setOcrDialogOpen(false);
                    onPickOrder(m);
                  }}
                >
                  <Stack>
                    <Typography fontWeight={700}>{displayCustomerName(m.name_clean)}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {m.ticket_id ? `${t("ops.bagIdShort")} ${m.ticket_id} • ` : ""}#{m.id} • {String(m.date_clean || "").slice(0, 10)} • {m.service_type} • {m.weight_num}
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
            startIcon={<QrCodeScanner />}
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

      <Dialog
        open={open}
        onClose={closeMainDialog}
        fullWidth
        maxWidth="sm"
        fullScreen={fullScreenDialog}
        aria-labelledby="order-scan-title"
      >
        <DialogTitle id="order-scan-title" sx={{ fontWeight: 700, py: 1, px: 2 }}>
          {t("ops.scanBagButton")}
        </DialogTitle>
        <DialogContent sx={{ px: 2, pt: 0, pb: 1, display: "flex", flexDirection: "column", gap: 1 }}>
          <ToggleButtonGroup exclusive fullWidth size="small" value={dialogTab} onChange={(_, v) => v && setDialogTab(v)}>
            <ToggleButton value="qr">{t("ops.scanModeBagQr")}</ToggleButton>
            <ToggleButton value="ocr">{t("ops.scanModeTagOcr")}</ToggleButton>
          </ToggleButtonGroup>

          {dialogTab === "qr" ? (
            <Stack spacing={1} sx={{ flex: 1, minHeight: 0 }}>
              {scanSurface}
            </Stack>
          ) : (
            <Stack spacing={1.25}>
              <Box sx={{ borderRadius: 2, overflow: "hidden", bgcolor: "#0f172a", minHeight: "36vh", maxHeight: "44vh" }}>
                <video ref={videoRef} autoPlay playsInline muted style={{ width: "100%", height: "100%", minHeight: 200, objectFit: "cover", display: "block" }} />
              </Box>
              <TextField label={t("ops.scanNameLabel")} value={nameHint} onChange={(e) => setNameHint(e.target.value)} size="small" fullWidth autoComplete="off" />
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
              <Button variant="contained" size="large" startIcon={<PhotoCamera />} onClick={onPrimaryOcr} disabled={busy || disabled} sx={{ py: 1.25, fontWeight: 700 }}>
                {busy ? <CircularProgress size={22} color="inherit" /> : primaryOcrLabel}
              </Button>
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={closeMainDialog} disabled={busy}>
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
                  <Typography fontWeight={700}>{displayCustomerName(m.name_clean)}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {m.ticket_id ? `${t("ops.bagIdShort")} ${m.ticket_id} • ` : ""}#{m.id} • {String(m.date_clean || "").slice(0, 10)} • {m.service_type} • {m.weight_num}
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
