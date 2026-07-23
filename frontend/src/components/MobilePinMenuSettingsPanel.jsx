import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { getClockPayrollUiSettings, getOrganization, putClockPayrollUiSettings } from "../api";

export const DEFAULT_PIN_MENU = {
  enabled: true,
  features: {
    switch_role: true,
    checklist: true,
    inventory: true,
  },
};

/** Known buttons — keep in sync with backend PIN_HUB_FEATURE_DEFS. */
export const PIN_MENU_FEATURE_OPTIONS = [
  {
    id: "switch_role",
    label: "Switch Role",
    help: "Change category & role while clocked in (needs Categories & Roles tracking on).",
  },
  {
    id: "checklist",
    label: "End-of-day checklist",
    help: "Maintenance task list for anyone with an attendance PIN.",
  },
  {
    id: "inventory",
    label: "Inventory",
    help: "Open inventory after PIN unlock (inventory module must be on).",
  },
];

/**
 * Org settings: which buttons appear on the mobile /pin menu.
 * Route for employees: /pin/{orgSlug}
 */
export default function MobilePinMenuSettingsPanel() {
  const [pinMenu, setPinMenu] = useState(DEFAULT_PIN_MENU);
  const [clock, setClock] = useState(null);
  const [payroll, setPayroll] = useState(null);
  const [slug, setSlug] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });
  const [copied, setCopied] = useState(false);

  const pinUrl = useMemo(() => {
    if (!slug || typeof window === "undefined") return "";
    return `${window.location.origin}/pin/${encodeURIComponent(slug)}`;
  }, [slug]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [uiRes, orgRes] = await Promise.all([
          getClockPayrollUiSettings(),
          getOrganization().catch(() => null),
        ]);
        if (cancelled) return;
        const d = uiRes.data || {};
        setClock(d.clock || null);
        setPayroll(d.payroll || null);
        const pm = d.pin_menu && typeof d.pin_menu === "object" ? d.pin_menu : {};
        setPinMenu({
          enabled: pm.enabled !== false,
          features: {
            ...DEFAULT_PIN_MENU.features,
            ...(pm.features && typeof pm.features === "object" ? pm.features : {}),
          },
        });
        const orgSlug = orgRes?.data?.slug || "";
        setSlug(String(orgSlug || "").toLowerCase());
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setFeature = (id, checked) => {
    setPinMenu((p) => ({
      ...p,
      features: { ...p.features, [id]: checked },
    }));
  };

  const save = async () => {
    try {
      setSaving(true);
      setMessage({ type: "", text: "" });
      const body = {
        pin_menu: {
          enabled: !!pinMenu.enabled,
          features: { ...pinMenu.features },
        },
      };
      // Preserve clock/payroll when present so we don't rely on server merge alone.
      if (clock) body.clock = clock;
      if (payroll) body.payroll = payroll;
      const res = await putClockPayrollUiSettings(body);
      const d = res.data || {};
      if (d.pin_menu) {
        setPinMenu({
          enabled: d.pin_menu.enabled !== false,
          features: {
            ...DEFAULT_PIN_MENU.features,
            ...(d.pin_menu.features || {}),
          },
        });
      }
      setMessage({ type: "success", text: "Mobile PIN menu saved." });
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Save failed (need settings permission).",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="h6" fontWeight={700}>
          Mobile PIN menu
        </Typography>
        <Typography variant="body2" color="text.secondary">
          One home-screen link for phones. Employees enter their attendance PIN, then see only the
          buttons you assign here (and that their role/permissions allow). You can add more buttons
          later.
        </Typography>

        {pinUrl ? (
          <Box
            sx={{
              p: 1.25,
              borderRadius: 1,
              bgcolor: "action.hover",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              fontSize: "0.85rem",
              wordBreak: "break-all",
            }}
          >
            {pinUrl}
            <Button
              size="small"
              sx={{ ml: 1, textTransform: "none" }}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(pinUrl);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1500);
                } catch {
                  /* ignore */
                }
              }}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </Box>
        ) : null}

        <FormControlLabel
          control={
            <Checkbox
              checked={!!pinMenu.enabled}
              onChange={(e) => setPinMenu((p) => ({ ...p, enabled: e.target.checked }))}
            />
          }
          label="Enable mobile PIN menu (/pin)"
        />

        <Typography variant="subtitle2" sx={{ pt: 0.5 }}>
          Buttons on the menu
        </Typography>
        {PIN_MENU_FEATURE_OPTIONS.map((opt) => (
          <Box key={opt.id}>
            <FormControlLabel
              disabled={!pinMenu.enabled}
              control={
                <Checkbox
                  checked={!!pinMenu.features?.[opt.id]}
                  onChange={(e) => setFeature(opt.id, e.target.checked)}
                />
              }
              label={opt.label}
            />
            <Typography variant="caption" color="text.secondary" display="block" sx={{ pl: 4, mt: -0.5 }}>
              {opt.help}
            </Typography>
          </Box>
        ))}

        {message.text ? (
          <Alert severity={message.type === "error" ? "error" : "success"} onClose={() => setMessage({ type: "", text: "" })}>
            {message.text}
          </Alert>
        ) : null}

        <Box>
          <Button variant="contained" disabled={saving} onClick={save} sx={{ textTransform: "none" }}>
            {saving ? "Saving…" : "Save mobile PIN menu"}
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}
