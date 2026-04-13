import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  List,
  ListItemButton,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { QrCodeScanner } from "@mui/icons-material";
import { Html5Qrcode } from "html5-qrcode";
import { useI18n } from "../i18n/I18nContext";
import { lookupOrdersByScan } from "../api";

const SCAN_READER_ID = "order-scan-reader";

function deriveNameHintsFromQr(qrText) {
  const raw = String(qrText || "").trim();
  if (!raw) return [];
  const out = [];
  const seen = new Set();
  const push = (s) => {
    const x = String(s || "")
      .trim()
      .replace(/\s+/g, " ");
    if (x.length < 3) return;
    const k = x.toLowerCase();
    if (seen.has(k)) return;
    seen.add(k);
    out.push(x);
  };
  try {
    const u = new URL(raw);
    for (let seg of u.pathname.split("/")) {
      if (!seg || seg.length < 3) continue;
      try {
        seg = decodeURIComponent(seg);
      } catch {
        /* keep seg */
      }
      const spaced = seg.replace(/[-_.+]+/g, " ").trim();
      if (spaced.length >= 3) push(spaced);
    }
    const sp = new URLSearchParams(u.search);
    for (const v of sp.values()) {
      const s = String(v || "").trim();
      if (s.length > 2 && /[a-zA-Z]/.test(s)) {
        try {
          push(decodeURIComponent(s).replace(/\+/g, " "));
        } catch {
          push(s.replace(/\+/g, " "));
        }
      }
    }
  } catch {
    /* not a valid absolute URL */
  }
  const brutal = raw.replace(/[^a-zA-Z0-9]+/g, " ").trim();
  const parts = brutal.split(/\s+/).filter((w) => w.length >= 4);
  for (const p of parts.slice(0, 8)) push(p);
  return out.slice(0, 6);
}

function dedupeScanBodies(list) {
  const seen = new Set();
  return list.filter((b) => {
    const k = JSON.stringify(b);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function buildScanLookupBodies(qrText, nameHint, serviceHint, batchStr) {
  const q = String(qrText || "").trim();
  const nh0 = String(nameHint || "").trim();
  const sh0 = String(serviceHint || "").trim();
  const bd = String(batchStr || "").trim().slice(0, 10);
  const batchOk = /^\d{4}-\d{2}-\d{2}$/.test(bd);

  const derived = deriveNameHintsFromQr(q);
  const hints = nh0 ? [nh0] : derived.length > 0 ? derived : [""];

  const services = sh0 ? [sh0] : [""];

  const bodies = [];
  for (const nh of hints) {
    for (const sh of services) {
      const base = { qr_text: q, name_hint: nh, service_hint: sh };
      if (batchOk) {
        bodies.push({ ...base, batch_date: bd });
      }
      bodies.push({ ...base });
    }
  }
  return dedupeScanBodies(bodies);
}

export default function OrderScanLookupBar({ storageKey, onPickOrder, disabled, batchDate }) {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState(() => localStorage.getItem(storageKey) === "1");
  const [open, setOpen] = useState(false);
  const [nameHint, setNameHint] = useState("");
  const [serviceHint, setServiceHint] = useState("");
  const [manualQr, setManualQr] = useState("");
  const [useCamera, setUseCamera] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pickList, setPickList] = useState(null);
  const scannerRef = useRef(null);
  const scanBusyRef = useRef(false);

  useEffect(() => {
    localStorage.setItem(storageKey, enabled ? "1" : "0");
  }, [enabled, storageKey]);

  const stopScanner = useCallback(async () => {
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

  const runLookup = useCallback(
    async (qrText) => {
      const q = String(qrText || "").trim();
      if (!q && (!nameHint.trim() || !serviceHint.trim())) {
        window.alert(t("ops.scanAlertNeedQrOrTagFields"));
        return;
      }
      setBusy(true);
      try {
        const bd = String(batchDate || "").trim().slice(0, 10);
        const bodies = buildScanLookupBodies(q, nameHint, serviceHint, bd);
        let lastErr = null;
        for (const body of bodies) {
          try {
            const res = await lookupOrdersByScan(body);
            const matches = Array.isArray(res.data?.matches) ? res.data.matches : [];
            if (matches.length === 1) {
              await stopScanner();
              setOpen(false);
              onPickOrder(matches[0]);
              return;
            }
            if (matches.length > 1) {
              await stopScanner();
              setPickList(matches);
              return;
            }
          } catch (e) {
            lastErr = e;
          }
        }
        if (lastErr) {
          window.alert(lastErr?.response?.data?.error || t("ops.scanAlertLookupFailed"));
          return;
        }
        window.alert(t("ops.scanAlertNoMatch"));
      } catch (e) {
        window.alert(e?.response?.data?.error || t("ops.scanAlertLookupFailed"));
      } finally {
        setBusy(false);
      }
    },
    [nameHint, serviceHint, batchDate, onPickOrder, stopScanner, t]
  );

  useEffect(() => {
    if (!open) {
      void stopScanner();
    }
  }, [open, stopScanner]);

  useEffect(() => {
    if (open) setUseCamera(true);
  }, [open]);

  useEffect(() => {
    if (!open || !enabled || !useCamera) {
      void stopScanner();
      return undefined;
    }
    let cancelled = false;
    scanBusyRef.current = false;

    const start = async () => {
      await stopScanner();
      if (cancelled) return;
      const el = document.getElementById(SCAN_READER_ID);
      if (!el) return;
      const html5 = new Html5Qrcode(SCAN_READER_ID);
      scannerRef.current = html5;
      try {
        await html5.start(
          { facingMode: "environment" },
          { fps: 15, qrbox: { width: 280, height: 280 } },
          async (text) => {
            if (scanBusyRef.current) return;
            scanBusyRef.current = true;
            try {
              await runLookup(text);
            } finally {
              scanBusyRef.current = false;
            }
          },
          () => {}
        );
      } catch {
        /* camera unavailable */
      }
    };
    start();
    return () => {
      cancelled = true;
      stopScanner();
    };
  }, [open, enabled, useCamera, runLookup, stopScanner]);

  const onManualLookup = () => runLookup(manualQr);

  const canLookUp =
    !busy &&
    (Boolean(manualQr.trim()) || (Boolean(nameHint.trim()) && Boolean(serviceHint.trim())));

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

      <Dialog open={open} onClose={() => !busy && setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 700 }}>{t("ops.scanDialogTitle")}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.25}>
            <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.45 }}>
              {t("ops.scanDialogHint")}
            </Typography>
            <FormControlLabel
              control={
                <Switch
                  checked={useCamera}
                  onChange={(_, v) => setUseCamera(v)}
                  disabled={busy}
                  color="primary"
                  size="small"
                />
              }
              label={t("ops.scanCameraToggle")}
              sx={{ m: 0, alignItems: "center" }}
            />
            {useCamera && (
              <Box
                id={SCAN_READER_ID}
                sx={{ minHeight: 260, bgcolor: "#0f172a", borderRadius: 2, overflow: "hidden" }}
              />
            )}
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              {t("ops.scanOptionalSection")}
            </Typography>
            <TextField
              label={t("ops.scanNameLabel")}
              value={nameHint}
              onChange={(e) => setNameHint(e.target.value)}
              placeholder={t("ops.scanNamePlaceholder")}
              size="small"
              fullWidth
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
                  if (!selected) return t("ops.scanServiceAny");
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
              <MenuItem value="">{t("ops.scanServiceAny")}</MenuItem>
              <MenuItem value="Wash & fold">{t("ops.svcWashFold")}</MenuItem>
              <MenuItem value="Wash and fold">{t("ops.svcWashAndFold")}</MenuItem>
              <MenuItem value="Hang dry">{t("ops.svcHangDry")}</MenuItem>
              <MenuItem value="WF">WF</MenuItem>
              <MenuItem value="HD">HD</MenuItem>
            </TextField>
            <TextField
              label={t("ops.scanPasteQrLabel")}
              value={manualQr}
              onChange={(e) => setManualQr(e.target.value)}
              multiline
              minRows={2}
              size="small"
              placeholder={t("ops.scanPasteQrPlaceholder")}
            />
            <Button
              variant="contained"
              onClick={onManualLookup}
              disabled={!canLookUp}
              sx={{ py: 1.2, fontWeight: 700 }}
            >
              {t("ops.scanLookUp")}
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions>
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
