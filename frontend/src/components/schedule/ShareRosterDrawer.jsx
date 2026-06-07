import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  FormControlLabel,
  IconButton,
  InputAdornment,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import LinkIcon from "@mui/icons-material/Link";
import {
  deleteRosterShareLink,
  getRosterShareLinks,
  postRosterShareLink,
} from "../../api";

import ScheduleEmptyState from "./ScheduleEmptyState";
import PlanningDateRangePicker from "../datetime/PlanningDateRangePicker";
import { businessTodayYmd } from "../../utils/businessTime";

export default function ShareRosterDrawer({ open, onClose, defaultStart, defaultEnd, publishedCount = 0, settings }) {
  const [links, setLinks] = useState([]);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const [form, setForm] = useState({
    title: "Partner Roster",
    date_start: defaultStart || businessTodayYmd(),
    date_end: defaultEnd || businessTodayYmd(),
    published_only: true,
    show_phone: false,
    show_worker_category: false,
    show_internal_notes: false,
    show_performance: false,
    pin: "",
    expires_at: "",
    mode: "live",
  });

  const load = useCallback(async () => {
    try {
      const res = await getRosterShareLinks();
      setLinks(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || "Could not load links");
    }
  }, []);

  useEffect(() => {
    if (open) {
      setForm((f) => ({
        ...f,
        date_start: defaultStart || f.date_start,
        date_end: defaultEnd || f.date_end,
      }));
      load();
    }
  }, [open, defaultStart, defaultEnd, load]);

  const fullUrl = (path) => `${window.location.origin}${path}`;

  const copyLink = (path) => {
    navigator.clipboard?.writeText(fullUrl(path));
    setCopied(path);
    setTimeout(() => setCopied(""), 2000);
  };

  const create = async () => {
    setError("");
    try {
      const res = await postRosterShareLink({
        ...form,
        expires_at: form.expires_at || null,
        pin: form.pin || undefined,
      });
      await load();
      if (res.data?.public_path) copyLink(res.data.public_path);
    } catch (e) {
      setError(e.response?.data?.error || "Could not create share link.");
    }
  };

  const revoke = async (id) => {
    try {
      await deleteRosterShareLink(id);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Could not revoke link.");
    }
  };

  return (
    <Drawer anchor="bottom" open={open} onClose={onClose} PaperProps={{ sx: { borderRadius: "16px 16px 0 0", maxHeight: "92vh" } }}>
      <Box sx={{ p: 2, maxWidth: 560, mx: "auto", width: "100%" }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <LinkIcon color="primary" />
            <Typography variant="h6" fontWeight={800}>
              Share roster
            </Typography>
          </Stack>
          <IconButton onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Partners get a read-only link. Published schedules only by default — no rates, payroll, or private notes.
        </Typography>

        {error ? (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
            {error}
          </Alert>
        ) : null}

        {form.published_only && publishedCount === 0 ? (
          <Alert severity="warning">
            No published shifts in this week yet. Partners will see an empty roster until you publish.
          </Alert>
        ) : null}

        <Stack spacing={2} sx={{ mb: 3 }}>
          <TextField
            label="Title"
            size="small"
            fullWidth
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <PlanningDateRangePicker
            start={form.date_start}
            end={form.date_end}
            weekStartsOn={settings?.week_starts_on ?? 0}
            onChange={({ start, end }) =>
              setForm((prev) => ({
                ...prev,
                ...(start != null ? { date_start: start } : {}),
                ...(end != null ? { date_end: end } : {}),
              }))
            }
          />
          <TextField
            label="Optional PIN"
            type="password"
            size="small"
            fullWidth
            value={form.pin}
            onChange={(e) => setForm({ ...form, pin: e.target.value })}
            helperText="Leave blank for open link (still token-secured)"
          />
          <TextField
            label="Expires (optional)"
            type="datetime-local"
            size="small"
            fullWidth
            InputLabelProps={{ shrink: true }}
            value={form.expires_at}
            onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
          />
          <FormControlLabel
            control={
              <Switch
                checked={form.published_only}
                onChange={(e) => setForm({ ...form, published_only: e.target.checked })}
              />
            }
            label="Published schedule only (recommended)"
          />
          <FormControlLabel
            control={
              <Switch checked={form.show_phone} onChange={(e) => setForm({ ...form, show_phone: e.target.checked })} />
            }
            label="Show phone numbers"
          />
          <FormControlLabel
            control={
              <Switch
                checked={form.show_worker_category}
                onChange={(e) => setForm({ ...form, show_worker_category: e.target.checked })}
              />
            }
            label="Show worker category"
          />
          <Button variant="contained" size="large" onClick={create} startIcon={<LinkIcon />}>
            Generate & copy link
          </Button>
        </Stack>

        <Divider sx={{ my: 2 }} />
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
          Active links
        </Typography>
        <Stack spacing={1.5}>
          {links.map((ln) => (
            <Box
              key={ln.id}
              sx={{
                p: 1.5,
                borderRadius: 2,
                border: "1px solid",
                borderColor: "divider",
                bgcolor: "background.paper",
              }}
            >
              <Typography variant="subtitle2" fontWeight={700}>
                {ln.title}
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                {ln.date_start} – {ln.date_end} · {ln.mode} · {ln.published_only ? "published only" : "includes drafts"}
              </Typography>
              {ln.last_accessed_at ? (
                <Typography variant="caption" color="text.secondary">
                  Last accessed: {new Date(ln.last_accessed_at).toLocaleString()}
                </Typography>
              ) : null}
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                <Button
                  size="small"
                  startIcon={<ContentCopyIcon />}
                  onClick={() => copyLink(ln.public_path)}
                >
                  {copied === ln.public_path ? "Copied!" : "Copy"}
                </Button>
                <Button size="small" color="error" onClick={() => revoke(ln.id)}>
                  Revoke
                </Button>
              </Stack>
            </Box>
          ))}
          {!links.length ? (
            <ScheduleEmptyState
              title="No roster share links"
              description="Generate a link above to share the published schedule with partners."
            />
          ) : null}
        </Stack>
      </Box>
    </Drawer>
  );
}
