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
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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
  putNotificationManagementRouting,
} from "../api";

function compactName(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function personLabel(person) {
  const account = person.username || `user ${person.id}`;
  const display = compactName(person.display_name);
  const employee = compactName(person.employee_name);
  const primary = employee || display || "Unnamed user";
  const same = display.localeCompare(primary, undefined, { sensitivity: "accent" }) === 0;
  return same || !display ? `${primary} · ${account}` : `${primary} · ${display} · ${account}`;
}

export function addRecipient(selected, person) {
  if (selected.some((row) => row.id === person.id)) return selected;
  return [...selected, { ...person, active: true }];
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
        placeholder="Name, payroll name, or username"
      />
      <Stack
        spacing={0.5}
        data-testid="assignment-user-results"
        sx={{ maxHeight: { xs: "40vh", sm: 320 }, overflowY: "auto" }}
      >
        {matches
          .filter((person) => !selectedIds.has(person.id))
          .map((person) => (
            <Button
              key={person.id}
              variant="text"
              sx={{ justifyContent: "flex-start", textAlign: "left" }}
              onClick={() => setSelected((rows) => addRecipient(rows, person))}
            >
              {personLabel(person)}
            </Button>
          ))}
        {query.trim() && matches.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No matching users
          </Typography>
        ) : null}
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

function categoryTitle(module, category) {
  return `${module.label} — ${category.label}`;
}

function activeRecipientCount(category) {
  return (category.recipients || []).filter((person) => person.active !== false).length;
}

export default function NotificationAssignments() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState("");
  const [routingIntent, setRoutingIntent] = useState("");
  const [routingError, setRoutingError] = useState("");
  const [routingBusy, setRoutingBusy] = useState(false);

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

  const categories = (data.modules || []).flatMap((module) =>
    (module.categories || []).map((category) => ({ module, category }))
  );
  const emptyCategories = data.empty_categories || [];
  const routingActive = Boolean(data.management_routing_active);

  const confirmRouting = async () => {
    setRoutingBusy(true);
    setRoutingError("");
    try {
      await putNotificationManagementRouting({
        active: routingIntent === "activate",
        confirm_incomplete: routingIntent === "activate" && emptyCategories.length > 0,
      });
      setRoutingIntent("");
      await load();
    } catch (err) {
      const names = (err?.response?.data?.empty_categories || []).map((row) => row.label).filter(Boolean);
      setRoutingError(
        names.length
          ? `These categories have no recipients: ${names.join(", ")}.`
          : err?.response?.data?.error || err?.message || "Could not change routing.",
      );
    } finally {
      setRoutingBusy(false);
    }
  };

  return (
    <Stack spacing={2}>
      <Box
        sx={{
          border: 1,
          borderColor: "divider",
          borderRadius: 1,
          p: 2,
          display: "grid",
          gap: 1,
        }}
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignItems: { sm: "center" } }}>
          <Chip
            data-testid="routing-status"
            label={routingActive ? "Routing Active" : "Routing Inactive"}
            color={routingActive ? "success" : "default"}
          />
          <Typography variant="body2">
            {data.category_count || categories.length} notification categories
          </Typography>
        </Stack>
        {categories.map(({ module, category }) => (
          <Typography key={category.event_key} variant="body2" color="text.secondary">
            {categoryTitle(module, category)} —{" "}
            {category.enabled === false
              ? "Disabled"
              : activeRecipientCount(category) === 0
                ? "No recipients"
                : `${activeRecipientCount(category)} recipient${activeRecipientCount(category) === 1 ? "" : "s"}`}
          </Typography>
        ))}
        <Typography variant="body2">
          Categories with no recipients:{" "}
          {emptyCategories.length ? emptyCategories.map((row) => row.label).join(", ") : "None"}
        </Typography>
        <Alert severity="warning">
          Activating routing replaces legacy role-based notification distribution. A role such as
          Finance, Supervisor, or Admin does not receive a management alert unless that person is
          assigned below.
        </Alert>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <Button
            data-testid="activate-routing"
            variant="contained"
            disabled={routingActive}
            onClick={() => {
              setRoutingError("");
              setRoutingIntent("activate");
            }}
          >
            Activate Routing
          </Button>
          <Button
            data-testid="deactivate-routing"
            variant="outlined"
            disabled={!routingActive}
            onClick={() => {
              setRoutingError("");
              setRoutingIntent("deactivate");
            }}
          >
            Deactivate Routing
          </Button>
        </Stack>
      </Box>
      <Dialog open={Boolean(routingIntent)} onClose={() => (routingBusy ? null : setRoutingIntent(""))} fullWidth>
        <DialogTitle>{routingIntent === "activate" ? "Activate routing?" : "Deactivate routing?"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            {routingIntent === "activate" ? (
              <>
                <Typography variant="body2">
                  Management alerts will go only to the people assigned here. Role access will no longer add recipients.
                </Typography>
                {emptyCategories.length ? (
                  <Alert severity="warning">
                    These categories have no recipients and will send nothing:{" "}
                    {emptyCategories.map((row) => row.label).join(", ")}.
                  </Alert>
                ) : null}
              </>
            ) : (
              <Typography variant="body2">
                Management alerts return to the previous role and audience rules. Saved recipients stay in place.
              </Typography>
            )}
            {routingError ? <Alert severity="error">{routingError}</Alert> : null}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ flexDirection: { xs: "column", sm: "row" }, alignItems: "stretch" }}>
          <Button onClick={() => setRoutingIntent("")} disabled={routingBusy}>
            Cancel
          </Button>
          <Button data-testid="confirm-routing" variant="contained" onClick={confirmRouting} disabled={routingBusy}>
            {routingBusy ? "Saving…" : routingIntent === "activate" ? "Activate Routing" : "Deactivate Routing"}
          </Button>
        </DialogActions>
      </Dialog>
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
              const count = activeRecipientCount(category);
              const expanded = open === category.event_key;
              return (
                <Box key={category.event_key} sx={{ borderTop: 1, borderColor: "divider", py: 0.5 }}>
                  <Button
                    fullWidth
                    data-testid={`category-${category.event_key}`}
                    sx={{
                      justifyContent: "space-between",
                      textTransform: "none",
                      color: "text.primary",
                      flexWrap: "wrap",
                      gap: 0.5,
                    }}
                    onClick={() => setOpen(expanded ? "" : category.event_key)}
                  >
                    <span>{categoryTitle(module, category)}</span>
                    <Typography variant="body2" color="text.secondary">
                      {category.enabled === false
                        ? "Disabled"
                        : count === 0
                          ? "No recipients"
                          : `${count} recipient${count === 1 ? "" : "s"}`}
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
