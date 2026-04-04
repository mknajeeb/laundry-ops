import { useCallback, useEffect, useMemo, useState } from "react";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  FormControlLabel,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  deleteNotificationEvent,
  deleteNotificationGroup,
  getNotificationEventAudiences,
  getNotificationEvents,
  getNotificationGroupMembers,
  getNotificationGroups,
  getNotificationPreferences,
  getUsers,
  postNotificationDispatch,
  postNotificationEvent,
  postNotificationGroup,
  putNotificationEventAudiences,
  putNotificationGroupMembers,
  putNotificationPreferences,
} from "../api";
import { useI18n } from "../i18n/I18nContext";

const NOTIF_OUTLINE_ACCORDION_SX = {
  border: 1,
  borderColor: "divider",
  borderRadius: 1,
  "&:before": { display: "none" },
  boxShadow: "none",
};

function PrefsSection() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [prefs, setPrefs] = useState({
    push_out: true,
    email_out: true,
    sms_out: true,
    whatsapp_out: false,
  });

  const load = useCallback(async () => {
    setErr("");
    setLoading(true);
    try {
      const res = await getNotificationPreferences();
      const d = res.data || {};
      setPrefs({
        push_out: d.push_out !== false,
        email_out: d.email_out !== false,
        sms_out: d.sms_out !== false,
        whatsapp_out: !!d.whatsapp_out,
      });
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setErr("");
    try {
      await putNotificationPreferences({
        email_out: prefs.email_out,
        push_out: prefs.push_out,
        sms_out: prefs.sms_out,
        whatsapp_out: prefs.whatsapp_out,
      });
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Typography>{t("notifications.loading")}</Typography>;

  return (
    <Stack spacing={2} sx={{ maxWidth: 520 }}>
      {err && <Alert severity="error">{err}</Alert>}
      <Typography variant="body2" color="text.secondary">
        {t("notifications.prefsBlurb")}
      </Typography>
      <FormControlLabel
        control={
          <Checkbox
            checked={prefs.push_out}
            onChange={(_, v) => setPrefs((p) => ({ ...p, push_out: v }))}
          />
        }
        label={t("notifications.channelPush")}
      />
      <FormControlLabel
        control={
          <Checkbox
            checked={prefs.email_out}
            onChange={(_, v) => setPrefs((p) => ({ ...p, email_out: v }))}
          />
        }
        label={t("notifications.channelEmail")}
      />
      <FormControlLabel
        control={
          <Checkbox
            checked={prefs.sms_out}
            onChange={(_, v) => setPrefs((p) => ({ ...p, sms_out: v }))}
          />
        }
        label={t("notifications.channelSms")}
      />
      <FormControlLabel
        control={
          <Checkbox
            checked={prefs.whatsapp_out}
            onChange={(_, v) => setPrefs((p) => ({ ...p, whatsapp_out: v }))}
          />
        }
        label={t("notifications.channelWhatsapp")}
      />
      <Button variant="contained" onClick={save} disabled={saving}>
        {saving ? t("common.saving") : t("common.save")}
      </Button>
    </Stack>
  );
}

function GroupsSection() {
  const { t } = useI18n();
  const [groups, setGroups] = useState([]);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const [name, setName] = useState("");
  const [sel, setSel] = useState(null);
  const [members, setMembers] = useState([]);
  const [memberIds, setMemberIds] = useState({});

  const loadGroups = useCallback(async () => {
    setErr("");
    try {
      const res = await getNotificationGroups();
      setGroups(res.data?.groups || []);
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Load failed");
    }
  }, []);

  const loadUsers = useCallback(async () => {
    try {
      const res = await getUsers();
      setUsers(Array.isArray(res.data) ? res.data : []);
    } catch (e) {
      setUsers([]);
      setErr(
        e?.response?.data?.error ||
          e?.message ||
          t("notifications.usersLoadError")
      );
    }
  }, [t]);

  useEffect(() => {
    loadGroups();
    loadUsers();
  }, [loadGroups, loadUsers]);

  useEffect(() => {
    if (!sel) {
      setMembers([]);
      setMemberIds({});
      return;
    }
    (async () => {
      try {
        const res = await getNotificationGroupMembers(sel.id);
        const list = res.data?.members || [];
        setMembers(list);
        const m = {};
        list.forEach((u) => {
          m[u.id] = true;
        });
        setMemberIds(m);
      } catch (e) {
        setErr(e?.response?.data?.error || e?.message || "Load failed");
      }
    })();
  }, [sel]);

  const saveMembers = async () => {
    if (!sel) return;
    setErr("");
    try {
      const ids = Object.keys(memberIds)
        .filter((k) => memberIds[k])
        .map((k) => Number(k));
      await putNotificationGroupMembers(sel.id, ids);
      await loadGroups();
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Save failed");
    }
  };

  const createGroup = async () => {
    if (!name.trim()) return;
    setErr("");
    try {
      await postNotificationGroup({ name: name.trim() });
      setName("");
      await loadGroups();
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Create failed");
    }
  };

  const removeGroup = async (g) => {
    if (!window.confirm(t("notifications.confirmDeleteGroup"))) return;
    setErr("");
    try {
      await deleteNotificationGroup(g.id);
      if (sel?.id === g.id) setSel(null);
      await loadGroups();
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Delete failed");
    }
  };

  return (
    <Stack spacing={2}>
      {err && <Alert severity="error">{err}</Alert>}
      <Accordion
        defaultExpanded
        disableGutters
        elevation={0}
        sx={NOTIF_OUTLINE_ACCORDION_SX}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Stack direction="row" alignItems="baseline" spacing={1} flexWrap="wrap">
            <Typography fontWeight={600}>
              {t("notifications.panelGroupsListTitle")}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              ({groups.length})
            </Typography>
          </Stack>
        </AccordionSummary>
        <AccordionDetails>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              size="small"
              label={t("notifications.groupName")}
              value={name}
              onChange={(e) => setName(e.target.value)}
              sx={{ flex: 1 }}
            />
            <Button variant="contained" onClick={createGroup}>
              {t("notifications.createGroup")}
            </Button>
          </Stack>
          <Table size="small" sx={{ mt: 1 }}>
            <TableHead>
              <TableRow>
                <TableCell>{t("notifications.groupName")}</TableCell>
                <TableCell align="right">{t("common.actions")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {groups.map((g) => (
                <TableRow
                  key={g.id}
                  hover
                  selected={sel?.id === g.id}
                  sx={{ cursor: "pointer" }}
                  onClick={() => setSel(g)}
                >
                  <TableCell>{g.name}</TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      color="error"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeGroup(g);
                      }}
                    >
                      {t("common.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </AccordionDetails>
      </Accordion>
      <Accordion
        key={sel ? `g-members-${sel.id}` : "g-members-none"}
        defaultExpanded={Boolean(sel)}
        disableGutters
        elevation={0}
        sx={NOTIF_OUTLINE_ACCORDION_SX}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600} color={sel ? "text.primary" : "text.secondary"}>
            {t("notifications.panelGroupMembersTitle")}
            {sel ? ` — ${sel.name}` : ""}
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          {sel ? (
            <>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                {t("notifications.membersFor")} {sel.name}
              </Typography>
              <Stack spacing={0.5} sx={{ maxHeight: 280, overflow: "auto" }}>
                {users.map((u) => (
                  <FormControlLabel
                    key={u.id}
                    control={
                      <Checkbox
                        size="small"
                        checked={!!memberIds[u.id]}
                        onChange={(_, v) =>
                          setMemberIds((prev) => ({ ...prev, [u.id]: v }))
                        }
                      />
                    }
                    label={`${u.display_name || u.username} (#${u.id})`}
                  />
                ))}
              </Stack>
              <Button sx={{ mt: 1 }} variant="outlined" onClick={saveMembers}>
                {t("notifications.saveMembers")}
              </Button>
            </>
          ) : (
            <Typography variant="body2" color="text.secondary">
              {t("notifications.selectGroupForMembers")}
            </Typography>
          )}
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}

const ALL_USERS_SENTINEL = -1;

function EventsSection() {
  const { t } = useI18n();
  const [events, setEvents] = useState([]);
  const [err, setErr] = useState("");
  const [ek, setEk] = useState("");
  const [dn, setDn] = useState("");
  const [sel, setSel] = useState(null);
  const [aud, setAud] = useState([]);
  const [audLoading, setAudLoading] = useState(false);
  const [tenantUsers, setTenantUsers] = useState([]);
  const [tenantGroups, setTenantGroups] = useState([]);
  const [listsLoading, setListsLoading] = useState(true);
  const [userFilter, setUserFilter] = useState("");
  const [routingSaving, setRoutingSaving] = useState(false);
  const [draft, setDraft] = useState({
    incAllUsers: false,
    incUsers: /** @type {Set<number>} */ (new Set()),
    incGroups: /** @type {Set<number>} */ (new Set()),
    excUsers: /** @type {Set<number>} */ (new Set()),
    excGroups: /** @type {Set<number>} */ (new Set()),
  });
  const [dispatchKey, setDispatchKey] = useState("");
  const [dispatchTitle, setDispatchTitle] = useState("Test");
  const [dispatchBody, setDispatchBody] = useState("Hello from Laundry Ops");
  const [dispatching, setDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState(null);

  const load = useCallback(async () => {
    setErr("");
    try {
      const ev = await getNotificationEvents();
      setEvents(ev.data?.events || []);
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Load failed");
    }
  }, []);

  const loadLists = useCallback(async () => {
    setListsLoading(true);
    setErr("");
    try {
      const [u, g] = await Promise.all([getUsers(), getNotificationGroups()]);
      setTenantUsers(Array.isArray(u.data) ? u.data : []);
      setTenantGroups(g.data?.groups || []);
    } catch (e) {
      setErr(
        e?.response?.data?.error ||
          e?.message ||
          t("notifications.usersLoadError")
      );
      setTenantUsers([]);
      setTenantGroups([]);
    } finally {
      setListsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadLists();
  }, [loadLists]);

  useEffect(() => {
    if (sel?.event_key) setDispatchKey(sel.event_key);
  }, [sel]);

  useEffect(() => {
    if (!sel) {
      setAud([]);
      return;
    }
    let cancelled = false;
    setAud([]);
    (async () => {
      setAudLoading(true);
      try {
        const res = await getNotificationEventAudiences(sel.id);
        if (!cancelled) setAud(res.data?.audiences || []);
      } catch (e) {
        if (!cancelled) {
          setErr(e?.response?.data?.error || e?.message || "Load failed");
        }
      } finally {
        if (!cancelled) setAudLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sel]);

  useEffect(() => {
    if (!sel) return;
    const inc = aud.filter((a) => a.rule_kind === "include");
    const exc = aud.filter((a) => a.rule_kind === "exclude");
    setDraft({
      incAllUsers: inc.some(
        (a) =>
          a.target_type === "user" &&
          Number(a.target_id) === ALL_USERS_SENTINEL
      ),
      incUsers: new Set(
        inc
          .filter(
            (a) =>
              a.target_type === "user" &&
              Number(a.target_id) !== ALL_USERS_SENTINEL
          )
          .map((a) => Number(a.target_id))
      ),
      incGroups: new Set(
        inc
          .filter((a) => a.target_type === "group")
          .map((a) => Number(a.target_id))
      ),
      excUsers: new Set(
        exc
          .filter((a) => a.target_type === "user")
          .map((a) => Number(a.target_id))
      ),
      excGroups: new Set(
        exc
          .filter((a) => a.target_type === "group")
          .map((a) => Number(a.target_id))
      ),
    });
  }, [sel, aud]);

  const filteredUsers = useMemo(() => {
    const q = userFilter.trim().toLowerCase();
    if (!q) return tenantUsers;
    return tenantUsers.filter((u) => {
      const a = `${u.display_name || ""} ${u.username || ""}`.toLowerCase();
      return a.includes(q) || String(u.id).includes(q);
    });
  }, [tenantUsers, userFilter]);

  const buildPayload = () => {
    const includes = [];
    if (draft.incAllUsers) {
      includes.push({ type: "user", id: ALL_USERS_SENTINEL });
    }
    draft.incUsers.forEach((id) => includes.push({ type: "user", id }));
    draft.incGroups.forEach((id) => includes.push({ type: "group", id }));
    const excludes = [];
    draft.excUsers.forEach((id) => excludes.push({ type: "user", id }));
    draft.excGroups.forEach((id) => excludes.push({ type: "group", id }));
    return { includes, excludes };
  };

  const saveRouting = async () => {
    if (!sel) return;
    setRoutingSaving(true);
    setErr("");
    try {
      const { includes, excludes } = buildPayload();
      await putNotificationEventAudiences(sel.id, { includes, excludes });
      const res = await getNotificationEventAudiences(sel.id);
      setAud(res.data?.audiences || []);
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Update failed");
    } finally {
      setRoutingSaving(false);
    }
  };

  const toggleSet = (key, id, on) => {
    setDraft((d) => {
      const next = new Set(d[key]);
      if (on) next.add(id);
      else next.delete(id);
      return { ...d, [key]: next };
    });
  };

  const createEvent = async () => {
    if (!ek.trim() || !dn.trim()) return;
    setErr("");
    try {
      await postNotificationEvent({
        event_key: ek.trim(),
        display_name: dn.trim(),
      });
      setEk("");
      setDn("");
      await load();
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Create failed");
    }
  };

  const removeEvent = async (ev) => {
    if (!window.confirm(t("notifications.confirmDeleteEvent"))) return;
    setErr("");
    try {
      await deleteNotificationEvent(ev.id);
      if (sel?.id === ev.id) setSel(null);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Delete failed");
    }
  };

  const runDispatch = async () => {
    setErr("");
    setDispatchResult(null);
    setDispatching(true);
    try {
      const res = await postNotificationDispatch({
        event_key: dispatchKey.trim(),
        title: dispatchTitle,
        body: dispatchBody,
      });
      setDispatchResult(res.data);
    } catch (e) {
      const data = e?.response?.data;
      setDispatchResult(
        data && typeof data === "object"
          ? data
          : { ok: false, error: e?.message || "Dispatch failed" }
      );
      if (data?.error && typeof data.error === "string") {
        setErr(data.error);
      }
    } finally {
      setDispatching(false);
    }
  };

  return (
    <Stack spacing={2}>
      {err && <Alert severity="error">{err}</Alert>}
      <Accordion
        defaultExpanded
        disableGutters
        elevation={0}
        sx={NOTIF_OUTLINE_ACCORDION_SX}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Stack direction="row" alignItems="baseline" spacing={1} flexWrap="wrap">
            <Typography fontWeight={600}>
              {t("notifications.panelEventsTitle")}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              ({events.length})
            </Typography>
          </Stack>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {t("notifications.createEvent")}
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              size="small"
              label={t("notifications.eventKey")}
              value={ek}
              onChange={(e) => setEk(e.target.value)}
              placeholder="task.reminder"
            />
            <TextField
              size="small"
              label={t("notifications.eventDisplayName")}
              value={dn}
              onChange={(e) => setDn(e.target.value)}
              sx={{ flex: 1 }}
            />
            <Button variant="contained" onClick={createEvent}>
              {t("common.add")}
            </Button>
          </Stack>
          <Table size="small" sx={{ mt: 1 }}>
            <TableHead>
              <TableRow>
                <TableCell>{t("notifications.eventKey")}</TableCell>
                <TableCell>{t("notifications.eventDisplayName")}</TableCell>
                <TableCell align="right">{t("common.actions")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {events.map((ev) => (
                <TableRow
                  key={ev.id}
                  hover
                  selected={sel?.id === ev.id}
                  sx={{ cursor: "pointer" }}
                  onClick={() => setSel(ev)}
                >
                  <TableCell>{ev.event_key}</TableCell>
                  <TableCell>{ev.display_name}</TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      color="error"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeEvent(ev);
                      }}
                    >
                      {t("common.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </AccordionDetails>
      </Accordion>
      <Accordion
        key={sel ? `evt-route-${sel.id}` : "evt-route-none"}
        defaultExpanded={Boolean(sel)}
        disableGutters
        elevation={0}
        sx={NOTIF_OUTLINE_ACCORDION_SX}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600} color={sel ? "text.primary" : "text.secondary"}>
            {t("notifications.panelRoutingTitle")}
            {sel ? ` — ${sel.event_key}` : ""}
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          {!sel ? (
            <Typography variant="body2" color="text.secondary">
              {t("notifications.selectEventForRouting")}
            </Typography>
          ) : (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography fontWeight={600} gutterBottom>
            {t("notifications.routingFor")} {sel.event_key}
          </Typography>
          <Typography
            variant="caption"
            color="text.secondary"
            display="block"
            gutterBottom
          >
            {t("notifications.routingHelp")}
          </Typography>
          {audLoading || listsLoading ? (
            <Stack alignItems="center" py={2}>
              <CircularProgress size={28} />
            </Stack>
          ) : (
            <>
              <FormControlLabel
                sx={{ mb: 1, display: "block" }}
                control={
                  <Checkbox
                    size="small"
                    checked={draft.incAllUsers}
                    onChange={(_, v) =>
                      setDraft((d) => ({
                        ...d,
                        incAllUsers: v,
                        incUsers: v ? new Set() : d.incUsers,
                      }))
                    }
                  />
                }
                label={t("notifications.includeAllUsers")}
              />
              <Accordion defaultExpanded>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography fontWeight={600}>
                    {t("notifications.routingIncludeUsers")}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <TextField
                    size="small"
                    fullWidth
                    sx={{ mb: 1 }}
                    label={t("notifications.filterUsers")}
                    value={userFilter}
                    onChange={(e) => setUserFilter(e.target.value)}
                    disabled={draft.incAllUsers}
                  />
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    display="block"
                    sx={{ mb: 0.5 }}
                  >
                    {t("notifications.tenantUsers")}
                  </Typography>
                  {!tenantUsers.length ? (
                    <Typography variant="body2" color="text.secondary">
                      {t("notifications.noUsersInTenant")}
                    </Typography>
                  ) : (
                    <Stack
                      spacing={0.25}
                      sx={{ maxHeight: 240, overflow: "auto" }}
                    >
                      {filteredUsers.map((u) => (
                        <FormControlLabel
                          key={u.id}
                          control={
                            <Checkbox
                              size="small"
                              checked={draft.incUsers.has(u.id)}
                              disabled={draft.incAllUsers}
                              onChange={(_, v) =>
                                toggleSet("incUsers", u.id, v)
                              }
                            />
                          }
                          label={`${u.display_name || u.username} (#${u.id})`}
                        />
                      ))}
                    </Stack>
                  )}
                </AccordionDetails>
              </Accordion>
              <Accordion defaultExpanded>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography fontWeight={600}>
                    {t("notifications.routingIncludeGroups")}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  {!tenantGroups.length ? (
                    <Typography variant="body2" color="text.secondary">
                      {t("notifications.noGroupsForRouting")}
                    </Typography>
                  ) : (
                    <Stack spacing={0.25}>
                      {tenantGroups.map((g) => (
                        <FormControlLabel
                          key={g.id}
                          control={
                            <Checkbox
                              size="small"
                              checked={draft.incGroups.has(g.id)}
                              onChange={(_, v) =>
                                toggleSet("incGroups", g.id, v)
                              }
                            />
                          }
                          label={`${g.name} (#${g.id})`}
                        />
                      ))}
                    </Stack>
                  )}
                </AccordionDetails>
              </Accordion>
              <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography fontWeight={600}>
                    {t("notifications.routingExcludeUsers")}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    display="block"
                    sx={{ mb: 1 }}
                  >
                    {t("notifications.excludeUsersHelp")}
                  </Typography>
                  <Stack
                    spacing={0.25}
                    sx={{ maxHeight: 200, overflow: "auto" }}
                  >
                    {tenantUsers.map((u) => (
                      <FormControlLabel
                        key={`exc-${u.id}`}
                        control={
                          <Checkbox
                            size="small"
                            checked={draft.excUsers.has(u.id)}
                            onChange={(_, v) =>
                              toggleSet("excUsers", u.id, v)
                            }
                          />
                        }
                        label={`${u.display_name || u.username} (#${u.id})`}
                      />
                    ))}
                  </Stack>
                </AccordionDetails>
              </Accordion>
              <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography fontWeight={600}>
                    {t("notifications.routingExcludeGroups")}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Stack spacing={0.25}>
                    {tenantGroups.map((g) => (
                      <FormControlLabel
                        key={`excg-${g.id}`}
                        control={
                          <Checkbox
                            size="small"
                            checked={draft.excGroups.has(g.id)}
                            onChange={(_, v) =>
                              toggleSet("excGroups", g.id, v)
                            }
                          />
                        }
                        label={`${g.name} (#${g.id})`}
                      />
                    ))}
                  </Stack>
                </AccordionDetails>
              </Accordion>
              <Button
                variant="contained"
                onClick={saveRouting}
                disabled={routingSaving}
              >
                {routingSaving ? t("common.saving") : t("notifications.saveRouting")}
              </Button>
            </>
          )}
        </Paper>
          )}
        </AccordionDetails>
      </Accordion>
      <Accordion
        defaultExpanded={false}
        disableGutters
        elevation={0}
        sx={NOTIF_OUTLINE_ACCORDION_SX}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>
            {t("notifications.panelTestTitle")}
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
      <Paper variant="outlined" sx={{ p: 2, width: "100%" }}>
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          gutterBottom
        >
          {t("notifications.dispatchHelp")}
        </Typography>
        <Typography
          variant="caption"
          color="primary.main"
          display="block"
          sx={{ mb: 0.5 }}
        >
          {t("notifications.dispatchSyncedHint")}
        </Typography>
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          sx={{ mb: 1 }}
        >
          {t("notifications.emailNotConfiguredHint")}
        </Typography>
        <Stack spacing={1} sx={{ maxWidth: 480 }}>
          <TextField
            size="small"
            label={t("notifications.eventKey")}
            value={dispatchKey}
            onChange={(e) => setDispatchKey(e.target.value)}
          />
          <TextField
            size="small"
            label={t("notifications.dispatchTitle")}
            value={dispatchTitle}
            onChange={(e) => setDispatchTitle(e.target.value)}
          />
          <TextField
            size="small"
            label={t("notifications.dispatchBody")}
            value={dispatchBody}
            onChange={(e) => setDispatchBody(e.target.value)}
            multiline
            minRows={2}
          />
          <Button
            variant="contained"
            onClick={runDispatch}
            disabled={dispatching || !dispatchKey.trim()}
          >
            {dispatching ? "…" : t("notifications.sendTest")}
          </Button>
          {dispatchResult && (
            <>
              <Alert
                severity={dispatchResult.ok ? "success" : "warning"}
                sx={{ mt: 1 }}
              >
                <Typography variant="subtitle2" gutterBottom>
                  {t("notifications.dispatchResult")}
                </Typography>
                <Box
                  component="pre"
                  sx={{ m: 0, fontSize: 12, whiteSpace: "pre-wrap" }}
                >
                  {JSON.stringify(dispatchResult, null, 2)}
                </Box>
              </Alert>
              {dispatchResult.ok &&
                Number(dispatchResult.recipients) === 0 && (
                  <Alert severity="warning" sx={{ mt: 1 }}>
                    {t("notifications.dispatchZeroRecipients")}
                  </Alert>
                )}
            </>
          )}
        </Stack>
      </Paper>
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}

export default function NotificationsPage({ user }) {
  const { t } = useI18n();
  const [tab, setTab] = useState(0);
  const isAdmin = useMemo(
    () => (user?.roles || []).map((r) => String(r).toUpperCase()).includes("ADMIN"),
    [user]
  );

  return (
    <Box sx={{ p: { xs: 1, md: 2 }, maxWidth: 1100 }}>
      <Typography variant="h5" gutterBottom>
        {t("notifications.title")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t("notifications.intro")}
      </Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label={t("notifications.tabPrefs")} />
        {isAdmin && <Tab label={t("notifications.tabGroups")} />}
        {isAdmin && <Tab label={t("notifications.tabEvents")} />}
      </Tabs>
      {tab === 0 && <PrefsSection />}
      {tab === 1 && isAdmin && <GroupsSection />}
      {tab === 2 && isAdmin && <EventsSection />}
    </Box>
  );
}
