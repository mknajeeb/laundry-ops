import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
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
      setUsers(res.data || []);
    } catch {
      setUsers([]);
    }
  }, []);

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
      <Table size="small">
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
                <Button size="small" color="error" onClick={(e) => { e.stopPropagation(); removeGroup(g); }}>
                  {t("common.delete")}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {sel && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography fontWeight={600} gutterBottom>
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
        </Paper>
      )}
    </Stack>
  );
}

function EventsSection() {
  const { t } = useI18n();
  const [events, setEvents] = useState([]);
  const [err, setErr] = useState("");
  const [ek, setEk] = useState("");
  const [dn, setDn] = useState("");
  const [sel, setSel] = useState(null);
  const [aud, setAud] = useState([]);
  const [incType, setIncType] = useState("user");
  const [incId, setIncId] = useState("");
  const [excType, setExcType] = useState("user");
  const [excId, setExcId] = useState("");
  const [dispatchKey, setDispatchKey] = useState("");
  const [dispatchTitle, setDispatchTitle] = useState("Test");
  const [dispatchBody, setDispatchBody] = useState("Hello from Laundry Ops");

  const load = useCallback(async () => {
    setErr("");
    try {
      const ev = await getNotificationEvents();
      setEvents(ev.data?.events || []);
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!sel) {
      setAud([]);
      return;
    }
    (async () => {
      try {
        const res = await getNotificationEventAudiences(sel.id);
        setAud(res.data?.audiences || []);
      } catch (e) {
        setErr(e?.response?.data?.error || e?.message || "Load failed");
      }
    })();
  }, [sel]);

  const includes = useMemo(
    () => aud.filter((a) => a.rule_kind === "include"),
    [aud]
  );
  const excludes = useMemo(
    () => aud.filter((a) => a.rule_kind === "exclude"),
    [aud]
  );

  const pushAudience = async (kind, type, id) => {
    if (!sel || !id) return;
    const n = Number(id);
    if (!Number.isFinite(n)) return;
    const inc = includes.map((a) => ({ type: a.target_type, id: a.target_id }));
    const exc = excludes.map((a) => ({ type: a.target_type, id: a.target_id }));
    const row = { type, id: n };
    const key = `${type}:${n}`;
    if (kind === "include") {
      if (inc.some((x) => `${x.type}:${x.id}` === key)) return;
      inc.push(row);
    } else {
      if (exc.some((x) => `${x.type}:${x.id}` === key)) return;
      exc.push(row);
    }
    setErr("");
    try {
      await putNotificationEventAudiences(sel.id, { includes: inc, excludes: exc });
      const res = await getNotificationEventAudiences(sel.id);
      setAud(res.data?.audiences || []);
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Update failed");
    }
  };

  const removeAudienceRow = async (row, fromInclude) => {
    if (!sel) return;
    let inc = includes.map((a) => ({ type: a.target_type, id: a.target_id }));
    let exc = excludes.map((a) => ({ type: a.target_type, id: a.target_id }));
    const match = (x) => x.type === row.target_type && x.id === row.target_id;
    if (fromInclude) inc = inc.filter((x) => !match(x));
    else exc = exc.filter((x) => !match(x));
    setErr("");
    try {
      await putNotificationEventAudiences(sel.id, { includes: inc, excludes: exc });
      const res = await getNotificationEventAudiences(sel.id);
      setAud(res.data?.audiences || []);
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Update failed");
    }
  };

  const createEvent = async () => {
    if (!ek.trim() || !dn.trim()) return;
    setErr("");
    try {
      await postNotificationEvent({ event_key: ek.trim(), display_name: dn.trim() });
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
    try {
      const res = await postNotificationDispatch({
        event_key: dispatchKey.trim(),
        title: dispatchTitle,
        body: dispatchBody,
      });
      alert(JSON.stringify(res.data, null, 2));
    } catch (e) {
      setErr(e?.response?.data?.error || e?.message || "Dispatch failed");
    }
  };

  return (
    <Stack spacing={2}>
      {err && <Alert severity="error">{err}</Alert>}
      <Typography variant="subtitle2">{t("notifications.createEvent")}</Typography>
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
      <Table size="small">
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
                <Button size="small" color="error" onClick={(e) => { e.stopPropagation(); removeEvent(ev); }}>
                  {t("common.delete")}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {sel && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography fontWeight={600} gutterBottom>
            {t("notifications.routingFor")} {sel.event_key}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" gutterBottom>
            {t("notifications.routingHelp")}
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }}>
            <TextField select size="small" label={t("notifications.include")} value={incType} onChange={(e) => setIncType(e.target.value)} sx={{ minWidth: 120 }}>
              <MenuItem value="user">user</MenuItem>
              <MenuItem value="group">group</MenuItem>
            </TextField>
            <TextField
              size="small"
              label="ID"
              value={incId}
              onChange={(e) => setIncId(e.target.value)}
            />
            <Button variant="outlined" onClick={() => { pushAudience("include", incType, incId); setIncId(""); }}>
              {t("notifications.addInclude")}
            </Button>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }}>
            <TextField select size="small" label={t("notifications.exclude")} value={excType} onChange={(e) => setExcType(e.target.value)} sx={{ minWidth: 120 }}>
              <MenuItem value="user">user</MenuItem>
              <MenuItem value="group">group</MenuItem>
            </TextField>
            <TextField
              size="small"
              label="ID"
              value={excId}
              onChange={(e) => setExcId(e.target.value)}
            />
            <Button variant="outlined" color="warning" onClick={() => { pushAudience("exclude", excType, excId); setExcId(""); }}>
              {t("notifications.addExclude")}
            </Button>
          </Stack>
          <Typography variant="subtitle2">{t("notifications.includeList")}</Typography>
          <Stack spacing={0.5} sx={{ mb: 1 }}>
            {includes.map((a) => (
              <Stack direction="row" key={`${a.target_type}-${a.target_id}-inc`} spacing={1} alignItems="center">
                <Typography variant="body2">
                  {a.target_type} #{a.target_id}
                </Typography>
                <Button size="small" onClick={() => removeAudienceRow(a, true)}>
                  {t("common.delete")}
                </Button>
              </Stack>
            ))}
          </Stack>
          <Typography variant="subtitle2">{t("notifications.excludeList")}</Typography>
          <Stack spacing={0.5}>
            {excludes.map((a) => (
              <Stack direction="row" key={`${a.target_type}-${a.target_id}-exc`} spacing={1} alignItems="center">
                <Typography variant="body2">
                  {a.target_type} #{a.target_id}
                </Typography>
                <Button size="small" onClick={() => removeAudienceRow(a, false)}>
                  {t("common.delete")}
                </Button>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography fontWeight={600} gutterBottom>
          {t("notifications.manualDispatch")}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block" gutterBottom>
          {t("notifications.dispatchHelp")}
        </Typography>
        <Stack spacing={1} sx={{ maxWidth: 480 }}>
          <TextField
            size="small"
            label={t("notifications.eventKey")}
            value={dispatchKey}
            onChange={(e) => setDispatchKey(e.target.value)}
          />
          <TextField size="small" label={t("notifications.dispatchTitle")} value={dispatchTitle} onChange={(e) => setDispatchTitle(e.target.value)} />
          <TextField size="small" label={t("notifications.dispatchBody")} value={dispatchBody} onChange={(e) => setDispatchBody(e.target.value)} multiline minRows={2} />
          <Button variant="contained" onClick={runDispatch}>
            {t("notifications.sendTest")}
          </Button>
        </Stack>
      </Paper>
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
