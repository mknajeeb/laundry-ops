import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
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
  createEmploymentCategory,
  createGeofence,
  createUserRate,
  deleteEmploymentCategory,
  deleteGeofence,
  deleteUserRate,
  getAuditLog,
  getEmploymentCategories,
  getGeofences,
  getTaBagRates,
  getTaSettings,
  getTaUsers,
  getUserRates,
  putTaSettings,
  updateEmploymentCategory,
  updateGeofence,
  updateUserRate,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function TabPanel({ children, value, index }) {
  if (value !== index) return null;
  return (
    <Box role="tabpanel" sx={{ pt: 2, width: "100%", maxWidth: "100%", minWidth: 0 }}>
      {children}
    </Box>
  );
}

function labelForAxiosError(err, fallback) {
  const status = err?.response?.status;
  const prefix = status ? `${status} ` : "";
  const d = err?.response?.data;
  if (typeof d?.error === "string") return `${prefix}${d.error}`;
  if (typeof d?.message === "string") return `${prefix}${d.message}`;
  if (err?.message) return `${prefix}${err.message}`;
  return `${prefix}${fallback}`;
}

function AttendanceSetupPage({ embedded = false }) {
  const { hasPerm, loading: authLoading } = useAuth();
  const { t } = useI18n();
  const [tab, setTab] = useState(0);
  const [error, setError] = useState("");
  const [geofences, setGeofences] = useState([]);
  const [cats, setCats] = useState([]);
  const [rates, setRates] = useState([]);
  const [settings, setSettings] = useState({});
  const [audit, setAudit] = useState([]);

  const [gfName, setGfName] = useState("");
  const [gfLat, setGfLat] = useState("");
  const [gfLng, setGfLng] = useState("");
  const [gfRad, setGfRad] = useState("150");

  const [catCode, setCatCode] = useState("");
  const [catName, setCatName] = useState("");

  const [rateUser, setRateUser] = useState("");
  const [rateCat, setRateCat] = useState("");
  const [rateAmt, setRateAmt] = useState("");
  const [rateEff, setRateEff] = useState(() => new Date().toISOString().slice(0, 10));
  const [taUsersList, setTaUsersList] = useState([]);
  const [bagRates, setBagRates] = useState([]);
  const [geoDialog, setGeoDialog] = useState(null);
  const [catDialog, setCatDialog] = useState(null);
  const [rateDialog, setRateDialog] = useState(null);

  const canTaSettings = hasPerm("ta.settings");
  const canUsersEdit = hasPerm("users.edit");
  const can = canTaSettings || canUsersEdit;

  useEffect(() => {
    if (!canTaSettings && canUsersEdit) setTab(2);
  }, [canTaSettings, canUsersEdit]);

  const loadAll = useCallback(async () => {
    if (!can || authLoading) return;
    setError("");
    const errs = [];

    async function run(name, fn, onOk) {
      try {
        const res = await fn();
        onOk(res);
      } catch (e) {
        errs.push(`${name}: ${labelForAxiosError(e, "request failed")}`);
        onOk(null);
      }
    }

    await run("Geofences", getGeofences, (res) => setGeofences(res?.data || []));
    await run("Categories", getEmploymentCategories, (res) => setCats(res?.data || []));
    await run("User rates", getUserRates, (res) => setRates(res?.data || []));
    await run("Payroll users", getTaUsers, (res) => setTaUsersList(res?.data || []));
    await run("Bag rates", getTaBagRates, (res) => setBagRates(res?.data || []));

    if (canTaSettings) {
      await run("Settings", getTaSettings, (res) => setSettings(res?.data || {}));
      await run("Audit log", getAuditLog, (res) => setAudit(res?.data || []));
    } else {
      setSettings({});
      setAudit([]);
    }

    if (errs.length) {
      setError(
        `Could not load everything. ${errs.join(" · ")} — 403 usually means TA permissions (run grant SQL, then sign out/in). 500 means the API crashed (Azure: laundryops-api → Log stream for the traceback; often missing TA tables or wrong DB env). Local dev: run the Flask API and vite proxy, or set VITE_API_BASE.`
      );
    }
  }, [can, canTaSettings, authLoading]);

  useEffect(() => {
    const t = setTimeout(() => {
      loadAll();
    }, 0);
    return () => clearTimeout(t);
  }, [loadAll]);

  async function addGeofence(e) {
    e.preventDefault();
    setError("");
    try {
      await createGeofence({
        name: gfName,
        latitude: parseFloat(gfLat),
        longitude: parseFloat(gfLng),
        radius_meters: parseInt(gfRad, 10),
        active: true,
      });
      setGfName("");
      setGfLat("");
      setGfLng("");
      await loadAll();
    } catch (err) {
      setError(err.response?.data?.error || "Failed");
    }
  }

  async function addCat(e) {
    e.preventDefault();
    try {
      await createEmploymentCategory({ code: catCode, name: catName, active: true });
      setCatCode("");
      setCatName("");
      await loadAll();
    } catch (err) {
      setError(err.response?.data?.error || "Failed");
    }
  }

  async function addRate(e) {
    e.preventDefault();
    try {
      await createUserRate({
        user_id: parseInt(rateUser, 10),
        employment_category_id: parseInt(rateCat, 10),
        hourly_rate: parseFloat(rateAmt),
        effective_date: rateEff,
      });
      await loadAll();
    } catch (err) {
      setError(err.response?.data?.error || "Failed");
    }
  }

  async function saveSettings(e) {
    e.preventDefault();
    try {
      await putTaSettings(settings);
      await loadAll();
    } catch (err) {
      setError(err.response?.data?.error || "Failed");
    }
  }

  async function toggleGeofenceActive(g) {
    setError("");
    try {
      await updateGeofence(g.id, { active: !g.active });
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Update failed"));
    }
  }

  async function removeGeofence(g) {
    if (!window.confirm(`Deactivate geofence “${g.name}”?`)) return;
    setError("");
    try {
      await deleteGeofence(g.id);
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Delete failed"));
    }
  }

  async function saveGeoDialog() {
    if (!geoDialog) return;
    setError("");
    try {
      await updateGeofence(geoDialog.id, {
        name: geoDialog.name,
        latitude: parseFloat(geoDialog.latitude),
        longitude: parseFloat(geoDialog.longitude),
        radius_meters: parseInt(geoDialog.radius_meters, 10),
      });
      setGeoDialog(null);
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Save failed"));
    }
  }

  async function toggleCatActive(c) {
    setError("");
    try {
      await updateEmploymentCategory(c.id, { active: !c.active });
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Update failed"));
    }
  }

  async function removeCat(c) {
    if (!window.confirm(`Deactivate category “${c.name}”?`)) return;
    setError("");
    try {
      await deleteEmploymentCategory(c.id);
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Delete failed"));
    }
  }

  async function saveCatDialog() {
    if (!catDialog) return;
    setError("");
    try {
      await updateEmploymentCategory(catDialog.id, {
        code: catDialog.code,
        name: catDialog.name,
      });
      setCatDialog(null);
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Save failed"));
    }
  }

  async function saveRateDialog() {
    if (!rateDialog) return;
    setError("");
    try {
      await updateUserRate(rateDialog.id, {
        hourly_rate: parseFloat(rateDialog.hourly_rate),
        effective_date: rateDialog.effective_date,
        end_date: rateDialog.end_date || null,
      });
      setRateDialog(null);
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Save failed"));
    }
  }

  async function removeRate(r) {
    if (!window.confirm("Delete this rate row?")) return;
    setError("");
    try {
      await deleteUserRate(r.id);
      await loadAll();
    } catch (err) {
      setError(labelForAxiosError(err, "Delete failed"));
    }
  }

  if (!can) {
    return (
      <Box sx={{ p: embedded ? 0 : { xs: 1.2, md: 2 } }}>
        <Alert severity="info">{t("attendance.needPerm")}</Alert>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        minHeight: "100%",
        width: "100%",
        maxWidth: "100%",
        minWidth: 0,
        p: embedded ? 0 : { xs: 1.2, md: 2 },
        boxSizing: "border-box",
      }}
    >
      {!embedded ? (
        <Typography sx={{ fontSize: 28, fontWeight: 700, mb: 1 }}>{t("attendance.title")}</Typography>
      ) : null}

      {error ? (
        <Alert
          severity="error"
          sx={{ mb: 2, "& .MuiAlert-message": { overflow: "hidden", wordBreak: "break-word" } }}
          onClose={() => setError("")}
        >
          {error}
        </Alert>
      ) : null}

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
        sx={{
          borderBottom: 1,
          borderColor: "divider",
          mb: 0,
          "& .MuiTabScrollButton-root": { width: 28 },
        }}
      >
        <Tab label={t("attendance.tabGeofences")} disabled={!canTaSettings} />
        <Tab label={t("attendance.tabCategories")} disabled={!canTaSettings} />
        <Tab label={t("attendance.tabRates")} />
        <Tab label={t("attendance.tabSettings")} disabled={!canTaSettings} />
        <Tab label={t("attendance.tabAudit")} disabled={!canTaSettings} />
      </Tabs>

      <TabPanel value={tab} index={0}>
        <Paper sx={{ p: 2, borderRadius: 2 }}>
          <Typography variant="subtitle1" gutterBottom>
            {t("attendance.addGeofence")}
          </Typography>
          <Stack
            component="form"
            onSubmit={addGeofence}
            spacing={2}
            direction={{ xs: "column", sm: "row" }}
            useFlexGap
            flexWrap="wrap"
            sx={{ alignItems: { xs: "stretch", sm: "flex-end" }, width: "100%" }}
          >
            <TextField
              label={t("attendance.name")}
              value={gfName}
              onChange={(e) => setGfName(e.target.value)}
              required
              size="small"
              sx={{ flex: { sm: "1 1 160px" }, minWidth: { sm: 140 } }}
            />
            <TextField
              label={t("attendance.lat")}
              value={gfLat}
              onChange={(e) => setGfLat(e.target.value)}
              required
              size="small"
              sx={{ flex: { sm: "1 1 120px" }, minWidth: { sm: 100 } }}
            />
            <TextField
              label={t("attendance.lng")}
              value={gfLng}
              onChange={(e) => setGfLng(e.target.value)}
              required
              size="small"
              sx={{ flex: { sm: "1 1 120px" }, minWidth: { sm: 100 } }}
            />
            <TextField
              label={t("attendance.radiusM")}
              value={gfRad}
              onChange={(e) => setGfRad(e.target.value)}
              size="small"
              sx={{ width: { xs: "100%", sm: 120 } }}
            />
            <Button type="submit" variant="contained" sx={{ alignSelf: { xs: "stretch", sm: "center" } }}>
              {t("attendance.saveBtn")}
            </Button>
          </Stack>
          <Box className="table-wrapper" sx={{ mt: 2 }}>
            <Table size="small" className="orders-table">
              <TableHead>
                <TableRow>
                  <TableCell>{t("attendance.name")}</TableCell>
                  <TableCell>{t("attendance.lat")}</TableCell>
                  <TableCell>{t("attendance.lng")}</TableCell>
                  <TableCell>{t("attendance.radiusM")}</TableCell>
                  <TableCell>{t("common.active")}</TableCell>
                  <TableCell align="right">{t("common.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {geofences.map((g) => (
                  <TableRow key={g.id}>
                    <TableCell>{g.name}</TableCell>
                    <TableCell>{g.latitude}</TableCell>
                    <TableCell>{g.longitude}</TableCell>
                    <TableCell>{g.radius_meters}</TableCell>
                    <TableCell>
                      <FormControlLabel
                        control={
                          <Switch
                            size="small"
                            checked={!!g.active}
                            onChange={() => toggleGeofenceActive(g)}
                          />
                        }
                        label={g.active ? t("common.yes") : t("common.no")}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end" flexWrap="wrap">
                        <Button
                          size="small"
                          onClick={() =>
                            setGeoDialog({
                              id: g.id,
                              name: g.name || "",
                              latitude: g.latitude ?? "",
                              longitude: g.longitude ?? "",
                              radius_meters: g.radius_meters ?? 150,
                            })
                          }
                        >
                          {t("common.edit")}
                        </Button>
                        <Button size="small" color="error" onClick={() => removeGeofence(g)}>
                          {t("common.delete")}
                        </Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        </Paper>
      </TabPanel>

      <TabPanel value={tab} index={1}>
        <Paper sx={{ p: 2, borderRadius: 2 }}>
          <Stack
            component="form"
            onSubmit={addCat}
            spacing={2}
            direction={{ xs: "column", sm: "row" }}
            useFlexGap
            flexWrap="wrap"
            sx={{ alignItems: { xs: "stretch", sm: "flex-end" }, mb: 2 }}
          >
            <TextField
              label={t("attendance.code")}
              value={catCode}
              onChange={(e) => setCatCode(e.target.value)}
              required
              size="small"
              sx={{ flex: { sm: "1 1 180px" }, minWidth: 0 }}
            />
            <TextField
              label={t("attendance.name")}
              value={catName}
              onChange={(e) => setCatName(e.target.value)}
              required
              size="small"
              sx={{ flex: { sm: "2 1 220px" }, minWidth: 0 }}
            />
            <Button type="submit" variant="contained" sx={{ alignSelf: { xs: "stretch", sm: "center" } }}>
              {t("attendance.addCategory")}
            </Button>
          </Stack>
          <Box className="table-wrapper">
            <Table size="small" className="orders-table">
              <TableHead>
                <TableRow>
                  <TableCell>{t("attendance.code")}</TableCell>
                  <TableCell>{t("attendance.name")}</TableCell>
                  <TableCell>{t("common.active")}</TableCell>
                  <TableCell align="right">{t("common.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {cats.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>{c.code}</TableCell>
                    <TableCell>{c.name}</TableCell>
                    <TableCell>
                      <FormControlLabel
                        control={
                          <Switch
                            size="small"
                            checked={!!c.active}
                            onChange={() => toggleCatActive(c)}
                          />
                        }
                        label={c.active ? t("common.yes") : t("common.no")}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end" flexWrap="wrap">
                        <Button
                          size="small"
                          onClick={() =>
                            setCatDialog({
                              id: c.id,
                              code: c.code || "",
                              name: c.name || "",
                            })
                          }
                        >
                          {t("common.edit")}
                        </Button>
                        <Button size="small" color="error" onClick={() => removeCat(c)}>
                          {t("common.delete")}
                        </Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        </Paper>
      </TabPanel>

      <TabPanel value={tab} index={2}>
        <Paper sx={{ p: 2, borderRadius: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t("attendance.ratesHelp")}
          </Typography>
          <Stack
            component="form"
            onSubmit={addRate}
            spacing={2}
            direction={{ xs: "column", md: "row" }}
            useFlexGap
            flexWrap="wrap"
            alignItems={{ xs: "stretch", md: "flex-start" }}
            sx={{ width: "100%" }}
          >
            <FormControl sx={{ minWidth: 0, width: { xs: "100%", md: 260 } }} size="small" required>
              <InputLabel id="rate-user-label">{t("attendance.payrollUser")}</InputLabel>
              <Select
                labelId="rate-user-label"
                label={t("attendance.payrollUser")}
                value={rateUser}
                onChange={(e) => setRateUser(e.target.value)}
              >
                {taUsersList.map((u) => (
                  <MenuItem key={u.id} value={String(u.id)}>
                    {u.first_name} {u.last_name} ({u.email})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl sx={{ minWidth: 0, width: { xs: "100%", md: 220 } }} size="small" required>
              <InputLabel id="rate-cat-label">{t("attendance.category")}</InputLabel>
              <Select
                labelId="rate-cat-label"
                label={t("attendance.category")}
                value={rateCat}
                onChange={(e) => setRateCat(e.target.value)}
              >
                {cats.map((c) => (
                  <MenuItem key={c.id} value={String(c.id)}>
                    {c.code} — {c.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label={t("attendance.hourlyRate")}
              value={rateAmt}
              onChange={(e) => setRateAmt(e.target.value)}
              required
              sx={{ width: { xs: "100%", md: 140 } }}
            />
            <TextField
              size="small"
              label={t("attendance.effectiveDate")}
              type="date"
              InputLabelProps={{ shrink: true }}
              value={rateEff}
              onChange={(e) => setRateEff(e.target.value)}
              required
              sx={{ width: { xs: "100%", md: 180 } }}
            />
            <Button type="submit" variant="contained" sx={{ alignSelf: { md: "center" } }}>
              {t("attendance.addRate")}
            </Button>
          </Stack>
          <Box className="table-wrapper" sx={{ mt: 2 }}>
            <Table size="small" className="orders-table">
              <TableHead>
                <TableRow>
                  <TableCell>{t("attendance.colUser")}</TableCell>
                  <TableCell>{t("attendance.colCategory")}</TableCell>
                  <TableCell>{t("attendance.colRate")}</TableCell>
                  <TableCell>{t("attendance.colFrom")}</TableCell>
                  <TableCell>{t("attendance.colTo")}</TableCell>
                  <TableCell align="right">{t("common.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rates.slice(0, 50).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell sx={{ maxWidth: 280, wordBreak: "break-word" }}>
                      {r.user_email || r.user_id}
                    </TableCell>
                    <TableCell>{r.category_name}</TableCell>
                    <TableCell>{r.hourly_rate}</TableCell>
                    <TableCell>{String(r.effective_date)}</TableCell>
                    <TableCell>{r.end_date ? String(r.end_date) : "—"}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end" flexWrap="wrap">
                        <Button
                          size="small"
                          onClick={() =>
                            setRateDialog({
                              id: r.id,
                              hourly_rate: r.hourly_rate ?? "",
                              effective_date: r.effective_date
                                ? String(r.effective_date).slice(0, 10)
                                : "",
                              end_date: r.end_date ? String(r.end_date).slice(0, 10) : "",
                            })
                          }
                        >
                          {t("common.edit")}
                        </Button>
                        <Button size="small" color="error" onClick={() => removeRate(r)}>
                          {t("common.delete")}
                        </Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        </Paper>
      </TabPanel>

      <TabPanel value={tab} index={3}>
        <Stack spacing={2} sx={{ width: "100%" }}>
          <Paper sx={{ p: 2, borderRadius: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
              {t("attendance.bagTableTitle")}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
              {t("attendance.bagTableHint")}
            </Typography>
            <Box className="table-wrapper">
              <Table size="small" className="orders-table">
                <TableHead>
                  <TableRow>
                    <TableCell>{t("attendance.bagEffectiveFrom")}</TableCell>
                    <TableCell>{t("attendance.bagCentsPerBag")}</TableCell>
                    <TableCell>{t("attendance.bagDollarsPerBag")}</TableCell>
                    <TableCell>{t("common.active")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {bagRates.slice(0, 20).map((b) => (
                    <TableRow key={b.id}>
                      <TableCell>{String(b.effective_from)}</TableCell>
                      <TableCell>{b.rate_per_bag_cents ?? "—"}</TableCell>
                      <TableCell>
                        {b.rate_per_bag_cents != null
                          ? `$${(Number(b.rate_per_bag_cents) / 100).toFixed(2)}`
                          : "—"}
                      </TableCell>
                      <TableCell>{b.active ? t("common.yes") : t("common.no")}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Paper>
          <Paper sx={{ p: 2, borderRadius: 2, maxWidth: 480 }}>
            <Typography variant="subtitle2" sx={{ mb: 1.5 }}>
              {t("attendance.tabSettings")}
            </Typography>
            <Stack component="form" onSubmit={saveSettings} spacing={2}>
              <TextField
                fullWidth
                label={t("attendance.maxShift")}
                value={settings.max_shift_hours || ""}
                onChange={(e) => setSettings({ ...settings, max_shift_hours: e.target.value })}
              />
              <TextField
                fullWidth
                label={t("attendance.bagDeductionFlag")}
                value={settings.bag_deduction_enabled || ""}
                onChange={(e) => setSettings({ ...settings, bag_deduction_enabled: e.target.value })}
              />
              <TextField
                fullWidth
                label={t("attendance.deductionPerBagDollars")}
                value={settings.bag_deduction_dollars_per_bag ?? ""}
                onChange={(e) =>
                  setSettings({ ...settings, bag_deduction_dollars_per_bag: e.target.value })
                }
                placeholder="0.00"
              />
              <Button type="submit" variant="contained">
                {t("attendance.saveSettings")}
              </Button>
            </Stack>
          </Paper>
        </Stack>
      </TabPanel>

      <TabPanel value={tab} index={4}>
        <Paper sx={{ p: 2, borderRadius: 2 }}>
          <Box className="table-wrapper">
            <Table size="small" className="orders-table">
              <TableHead>
                <TableRow>
                  <TableCell>{t("attendance.colWhen")}</TableCell>
                  <TableCell>{t("attendance.colActor")}</TableCell>
                  <TableCell>{t("attendance.colEntity")}</TableCell>
                  <TableCell>{t("attendance.colAction")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {audit.slice(0, 100).map((a) => (
                  <TableRow key={a.id}>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{String(a.created_at)}</TableCell>
                    <TableCell sx={{ maxWidth: 200, wordBreak: "break-word" }}>
                      {a.actor_email || a.actor_user_id}
                    </TableCell>
                    <TableCell sx={{ maxWidth: 220, wordBreak: "break-word" }}>
                      {a.entity_type} #{a.entity_id}
                    </TableCell>
                    <TableCell>{a.action}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        </Paper>
      </TabPanel>

      <Dialog open={!!geoDialog} onClose={() => setGeoDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t("attendance.tabGeofences")}</DialogTitle>
        <DialogContent>
          {geoDialog ? (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                label={t("attendance.name")}
                value={geoDialog.name}
                onChange={(e) => setGeoDialog({ ...geoDialog, name: e.target.value })}
                fullWidth
              />
              <TextField
                label={t("attendance.lat")}
                value={geoDialog.latitude}
                onChange={(e) => setGeoDialog({ ...geoDialog, latitude: e.target.value })}
                fullWidth
              />
              <TextField
                label={t("attendance.lng")}
                value={geoDialog.longitude}
                onChange={(e) => setGeoDialog({ ...geoDialog, longitude: e.target.value })}
                fullWidth
              />
              <TextField
                label={t("attendance.radiusM")}
                value={geoDialog.radius_meters}
                onChange={(e) => setGeoDialog({ ...geoDialog, radius_meters: e.target.value })}
                fullWidth
              />
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGeoDialog(null)}>{t("common.cancel")}</Button>
          <Button variant="contained" onClick={saveGeoDialog}>
            {t("common.save")}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!catDialog} onClose={() => setCatDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t("attendance.tabCategories")}</DialogTitle>
        <DialogContent>
          {catDialog ? (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                label={t("attendance.code")}
                value={catDialog.code}
                onChange={(e) => setCatDialog({ ...catDialog, code: e.target.value })}
                fullWidth
              />
              <TextField
                label={t("attendance.name")}
                value={catDialog.name}
                onChange={(e) => setCatDialog({ ...catDialog, name: e.target.value })}
                fullWidth
              />
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCatDialog(null)}>{t("common.cancel")}</Button>
          <Button variant="contained" onClick={saveCatDialog}>
            {t("common.save")}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!rateDialog} onClose={() => setRateDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t("attendance.tabRates")}</DialogTitle>
        <DialogContent>
          {rateDialog ? (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                label={t("attendance.hourlyRate")}
                value={rateDialog.hourly_rate}
                onChange={(e) => setRateDialog({ ...rateDialog, hourly_rate: e.target.value })}
                fullWidth
              />
              <TextField
                label={t("attendance.effectiveDate")}
                type="date"
                InputLabelProps={{ shrink: true }}
                value={rateDialog.effective_date}
                onChange={(e) => setRateDialog({ ...rateDialog, effective_date: e.target.value })}
                fullWidth
              />
              <TextField
                label={t("attendance.colTo")}
                type="date"
                InputLabelProps={{ shrink: true }}
                value={rateDialog.end_date}
                onChange={(e) => setRateDialog({ ...rateDialog, end_date: e.target.value })}
                fullWidth
                helperText="Leave empty if open-ended"
              />
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRateDialog(null)}>{t("common.cancel")}</Button>
          <Button variant="contained" onClick={saveRateDialog}>
            {t("common.save")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default AttendanceSetupPage;
