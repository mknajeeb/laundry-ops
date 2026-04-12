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
import { lookupOrdersByScan } from "../api";

const SCAN_READER_ID = "order-scan-reader";

export default function OrderScanLookupBar({ storageKey, onPickOrder, disabled }) {
  const [enabled, setEnabled] = useState(() => localStorage.getItem(storageKey) === "1");
  const [open, setOpen] = useState(false);
  const [nameHint, setNameHint] = useState("");
  const [serviceHint, setServiceHint] = useState("");
  const [manualQr, setManualQr] = useState("");
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
      if (!q && !nameHint.trim() && !serviceHint.trim()) {
        window.alert("Scan a QR code or enter name / service hints.");
        return;
      }
      setBusy(true);
      try {
        const res = await lookupOrdersByScan({
          qr_text: q,
          name_hint: nameHint.trim(),
          service_hint: serviceHint.trim(),
        });
        const matches = Array.isArray(res.data?.matches) ? res.data.matches : [];
        if (matches.length === 0) {
          window.alert("No matching order found. Check name and service on the tag (Wash & fold vs Hang dry).");
          return;
        }
        if (matches.length === 1) {
          await stopScanner();
          setOpen(false);
          onPickOrder(matches[0]);
          return;
        }
        await stopScanner();
        setPickList(matches);
      } catch (e) {
        window.alert(e?.response?.data?.error || "Lookup failed");
      } finally {
        setBusy(false);
      }
    },
    [nameHint, serviceHint, onPickOrder, stopScanner]
  );

  useEffect(() => {
    if (!open || !enabled) return undefined;
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
          { fps: 8, qrbox: { width: 240, height: 240 } },
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
        /* camera unavailable — manual QR still works */
      }
    };
    start();
    return () => {
      cancelled = true;
      stopScanner();
    };
  }, [open, enabled, runLookup, stopScanner]);

  const onManualLookup = () => runLookup(manualQr);

  return (
    <Box sx={{ mt: 1 }}>
      <FormControlLabel
        control={
          <Switch
            checked={enabled}
            onChange={(_, v) => setEnabled(v)}
            disabled={disabled}
            color="primary"
          />
        }
        label={
          <Typography component="span" sx={{ fontWeight: 600 }}>
            Scan lookup (QR + optional name / service from tag)
          </Typography>
        }
      />
      {enabled && (
        <Button
          variant="outlined"
          startIcon={<QrCodeScanner />}
          onClick={() => setOpen(true)}
          disabled={disabled}
          sx={{ ml: 1, borderRadius: 999, textTransform: "none" }}
        >
          Scan bag
        </Button>
      )}

      <Dialog open={open} onClose={() => !busy && setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Scan bag tag</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.5}>
            <Typography variant="body2" color="text.secondary">
              Point the camera at the QR on the Rinse tag. If several orders share the same name, type the name and
              choose the service printed on the tag (Wash &amp; fold vs Hang dry).
            </Typography>
            <Box
              id={SCAN_READER_ID}
              sx={{ minHeight: 220, bgcolor: "#000", borderRadius: 1, overflow: "hidden" }}
            />
            <TextField
              label="Name on tag (optional)"
              value={nameHint}
              onChange={(e) => setNameHint(e.target.value)}
              placeholder="e.g. Paris Rivera"
            />
            <TextField
              select
              label="Service on tag (optional)"
              value={serviceHint}
              onChange={(e) => setServiceHint(e.target.value)}
              SelectProps={{ displayEmpty: true }}
            >
              <MenuItem value="">Any / not sure</MenuItem>
              <MenuItem value="Wash & fold">Wash &amp; fold</MenuItem>
              <MenuItem value="Wash and fold">Wash and fold</MenuItem>
              <MenuItem value="Hang dry">Hang dry</MenuItem>
              <MenuItem value="WF">WF (code)</MenuItem>
              <MenuItem value="HD">HD (code)</MenuItem>
            </TextField>
            <TextField
              label="Or paste QR text"
              value={manualQr}
              onChange={(e) => setManualQr(e.target.value)}
              multiline
              minRows={2}
            />
            <Button variant="contained" onClick={onManualLookup} disabled={busy}>
              Look up with pasted text
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} disabled={busy}>
            Close
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(pickList?.length)} onClose={() => setPickList(null)} fullWidth maxWidth="sm">
        <DialogTitle>Multiple matches — pick one</DialogTitle>
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
                  <Typography fontWeight={600}>{m.name_clean}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    #{m.id} • {String(m.date_clean || "").slice(0, 10)} • {m.service_type} • weight {m.weight_num}
                  </Typography>
                </Stack>
              </ListItemButton>
            ))}
          </List>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPickList(null)}>Cancel</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
