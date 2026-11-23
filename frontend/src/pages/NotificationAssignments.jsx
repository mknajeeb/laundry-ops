import { useCallback, useEffect, useMemo, useState } from "react";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import {
  getNotificationManagement,
  getNotificationManagementUsers,
  putNotificationManagementCategory,
} from "../api";

function personLabel(person) {
  const name = person.display_name || "Unnamed user";
  const account = person.username || `user ${person.id}`;
  return `${name} · ${account}`;
}

function CategoryEditor({ category, onSaved }) {
  const [enabled, setEnabled] = useState(category.enabled !== false);
  const [selected, setSelected] = useState(category.recipients || []);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const signature = `${category.event_key}|${category.enabled}|${(category.recipients || []).map((person) => person.id).join(",")}`;
  useEffect(() => {
    setEnabled(category.enabled !== false);
    setSelected(category.recipients || []);
    setQuery("");
    setError("");
  }, [signature]);

  useEffect(() => {
    let cancel = false;
    const handle = window.setTimeout(() => {
      getNotificationManagementUsers(query)
        .then((res) => {
          if (!cancel) setMatches(res.data?.users || []);
        })
        .catch(() => {
          if (!cancel) setMatches([]);
        });
    }, 200);
    return () => {
      cancel = true;
      window.clearTimeout(handle);
    };
  }, [query]);

  const selectedIds = useMemo(() => new Set(selected.map((person) => person.id)), [selected]);

  const cancel = () => {
    setEnabled(category.enabled !== false);
    setSelected(category.recipients || []);
    setQuery("");
    setError("");
  };

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await putNotificationManagementCategory(category.event_key, {
        enabled,
        user_ids: selected.map((person) => person.id),
      });
      await onSaved();
    } catch (err) {
      const code = err?.response?.data?.error;
      setError(
        code === "inactive_user"
          ? "Inactive users cannot be assigned."
          : code === "outside_organization"
            ? "That account is not in this organization."
            : code || err?.message || "Could not save recipients.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack spacing={1.5} sx={{ py: 1 }}>
      <Typography variant="body2" color="text.secondary">
        {category.description}
      </Typography>
      <FormControlLabel
        control={<Switch checked={enabled} onChange={(_, value) => setEnabled(value)} />}
        label={enabled ? "Category enabled" : "Category disabled"}
      />
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        {selected.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No recipients. Saving this sends the alert to nobody.
          </Typography>
        ) : (
          selected.map((person) => (
            <Chip
              key={person.id}
              label={personLabel(person)}
              color={person.active === false ? "warning" : "default"}
              onDelete={() => setSelected((rows) => rows.filter((row) => row.id !== person.id))}
            />
          ))
        )}
      </Stack>
      <TextField
        size="small"
        label="Search active users"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Name or username"
      />
      <Stack spacing={0.5}>
        {matches
          .filter((person) => !selectedIds.has(person.id))
          .map((person) => (
            <Button
              key={person.id}
              variant="text"
              sx={{ justifyContent: "flex-start" }}
              onClick={() => setSelected((rows) => [...rows, { ...person, active: true }])}
            >
              {personLabel(person)}
            </Button>
          ))}
      </Stack>
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Stack direction="row" spacing={1}>
        <Button variant="contained" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button variant="outlined" onClick={cancel} disabled={saving}>
          Cancel
        </Button>
      </Stack>
    </Stack>
  );
}

export default function NotificationAssignments() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState("");

  const load = useCallback(async () => {
    const res = await getNotificationManagement();
    setData(res.data);
  }, []);

  useEffect(() => {
    let cancel = false;
    getNotificationManagement()
      .then((res) => {
        if (!cancel) setData(res.data);
      })
      .catch((err) => {
        if (!cancel) setError(err?.response?.data?.error || err?.message || "Could not load notifications.");
      });
    return () => {
      cancel = true;
    };
  }, []);

  const needle = filter.trim().toLowerCase();
  const modules = (data?.modules || [])
    .map((module) => ({
      ...module,
      categories: (module.categories || []).filter((category) => {
        if (!needle) return true;
        return (
          module.label.toLowerCase().includes(needle) ||
          category.label.toLowerCase().includes(needle) ||
          category.event_key.toLowerCase().includes(needle)
        );
      }),
    }))
    .filter((module) => module.categories.length > 0);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return <CircularProgress size={28} />;

  return (
    <Stack spacing={2}>
      <Alert severity={data.management_routing_active ? "success" : "info"}>
        {data.management_routing_active
          ? "Management routing is active. Alerts go only to the people assigned below."
          : "Management routing is not active. Assignments are saved, and current alerts still use the previous rules until activation is approved."}
      </Alert>
      <TextField
        size="small"
        label="Search modules or categories"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
      />
      {modules.map((module) => (
        <Accordion key={module.module_key} defaultExpanded disableGutters>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography sx={{ fontWeight: 700 }}>{module.label}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            {module.categories.map((category) => {
              const count = (category.recipients || []).filter((person) => person.active !== false).length;
              const expanded = open === category.event_key;
              return (
                <Box key={category.event_key} sx={{ borderTop: 1, borderColor: "divider", py: 0.5 }}>
                  <Button
                    fullWidth
                    sx={{ justifyContent: "space-between", textTransform: "none", color: "text.primary" }}
                    onClick={() => setOpen(expanded ? "" : category.event_key)}
                  >
                    <span>{category.label}</span>
                    <Typography variant="body2" color="text.secondary">
                      {category.enabled === false ? "Disabled" : `${count} recipient${count === 1 ? "" : "s"}`}
                    </Typography>
                  </Button>
                  {expanded ? <CategoryEditor category={category} onSaved={load} /> : null}
                </Box>
              );
            })}
          </AccordionDetails>
        </Accordion>
      ))}
      <Accordion disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography sx={{ fontWeight: 700 }}>Automatic notifications</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            These go to the employee the event is about. They are not assigned on this page.
          </Typography>
          {(data.automatic || []).map((item) => (
            <Box key={item.event_key} sx={{ py: 1, borderTop: 1, borderColor: "divider" }}>
              <Typography sx={{ fontWeight: 600 }}>
                {item.module_label} — {item.label}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {item.kind === "system" ? "System" : "Personal"}: {item.targeting}
              </Typography>
            </Box>
          ))}
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            {(data.unsupported_modules || []).join(", ")} do not send notifications yet.
          </Typography>
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
