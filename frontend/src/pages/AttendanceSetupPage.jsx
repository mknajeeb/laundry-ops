import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  createEmploymentCategory,
  createGeofence,
  createUserRate,
  getAuditLog,
  getEmploymentCategories,
  getGeofences,
  getTaBagRates,
  getTaSettings,
  getTaUsers,
  getUserRates,
  putTaSettings,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function TabPanel({ children, value, index }) {
  if (value !== index) return null;
  return <Box sx={{ pt: 2 }}>{children}</Box>;
}

function labelForAxiosError(err, fallback) {
  const d = err?.response?.data;
  if (typeof d?.error === "string") return d.error;
  if (typeof d?.message === "string") return d.message;
  if (err?.message) return err.message;
  return fallback;
}

function AttendanceSetupPage() {
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
        `Could not load everything. ${errs.join(" · ")} — Local dev: start the Flask API (default proxy target http://127.0.0.1:5000 in vite.config.js), or set VITE_API_BASE to your API. After fixing TA permissions, sign out and back in.`
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

  if (!can) {
    return (
      <div className="page">
        <Alert severity="info">{t("attendance.needPerm")}</Alert>
      </div>
    );
  }

  return (
    <div className="page">
      <Typography variant="h4" className="page-title" sx={{ mb: 2 }}>
        {t("attendance.title")}
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label={t("attendance.tabGeofences")} disabled={!canTaSettings} />
        <Tab label={t("attendance.tabCategories")} disabled={!canTaSettings} />
        <Tab label={t("attendance.tabRates")} />
        <Tab label={t("attendance.tabSettings")} disabled={!canTaSettings} />
        <Tab label={t("attendance.tabAudit")} disabled={!canTaSettings} />
      </Tabs>

      <TabPanel value={tab} index={0}>
        <Typography variant="subtitle1" gutterBottom>
          {t("attendance.addGeofence")}
        </Typography>
        <Stack component="form" onSubmit={addGeofence} spacing={2} direction={{ xs: "column", sm: "row" }} useFlexGap flexWrap="wrap">
          <TextField label={t("attendance.name")} value={gfName} onChange={(e) => setGfName(e.target.value)} required />
          <TextField label={t("attendance.lat")} value={gfLat} onChange={(e) => setGfLat(e.target.value)} required />
          <TextField label={t("attendance.lng")} value={gfLng} onChange={(e) => setGfLng(e.target.value)} required />
          <TextField label={t("attendance.radiusM")} value={gfRad} onChange={(e) => setGfRad(e.target.value)} />
          <Button type="submit" variant="contained">
            {t("attendance.saveBtn")}
          </Button>
        </Stack>
        <Box className="table-wrapper" sx={{ mt: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("attendance.name")}</TableCell>
                <TableCell>{t("attendance.lat")}</TableCell>
                <TableCell>{t("attendance.lng")}</TableCell>
                <TableCell>{t("attendance.radiusM")}</TableCell>
                <TableCell>{t("common.active")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {geofences.map((g) => (
                <TableRow key={g.id}>
                  <TableCell>{g.name}</TableCell>
                  <TableCell>{g.latitude}</TableCell>
                  <TableCell>{g.longitude}</TableCell>
                  <TableCell>{g.radius_meters}</TableCell>
                  <TableCell>{g.active ? t("common.yes") : t("common.no")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </TabPanel>

      <TabPanel value={tab} index={1}>
        <Stack component="form" onSubmit={addCat} spacing={2} direction="row" useFlexGap flexWrap="wrap">
          <TextField label={t("attendance.code")} value={catCode} onChange={(e) => setCatCode(e.target.value)} required />
          <TextField label={t("attendance.name")} value={catName} onChange={(e) => setCatName(e.target.value)} required />
          <Button type="submit" variant="contained">
            {t("attendance.addCategory")}
          </Button>
        </Stack>
        <Box sx={{ mt: 2 }}>
          {cats.map((c) => (
            <Typography key={c.id}>
              {c.code} — {c.name}
            </Typography>
          ))}
        </Box>
      </TabPanel>

      <TabPanel value={tab} index={2}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {t("attendance.ratesHelp")}
        </Typography>
        <Stack component="form" onSubmit={addRate} spacing={2} direction={{ xs: "column", sm: "row" }} useFlexGap flexWrap="wrap" alignItems="flex-start">
          <FormControl sx={{ minWidth: 220 }} size="small" required>
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
          <FormControl sx={{ minWidth: 200 }} size="small" required>
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
          />
          <TextField
            size="small"
            label={t("attendance.effectiveDate")}
            type="date"
            InputLabelProps={{ shrink: true }}
            value={rateEff}
            onChange={(e) => setRateEff(e.target.value)}
            required
          />
          <Button type="submit" variant="contained" sx={{ mt: 0.5 }}>
            {t("attendance.addRate")}
          </Button>
        </Stack>
        <Box className="table-wrapper" sx={{ mt: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("attendance.colUser")}</TableCell>
                <TableCell>{t("attendance.colCategory")}</TableCell>
                <TableCell>{t("attendance.colRate")}</TableCell>
                <TableCell>{t("attendance.colFrom")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rates.slice(0, 50).map((r) => (
                <TableRow key={r.id}>
                  <TableCell>{r.user_email || r.user_id}</TableCell>
                  <TableCell>{r.category_name}</TableCell>
                  <TableCell>{r.hourly_rate}</TableCell>
                  <TableCell>{String(r.effective_date)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </TabPanel>

      <TabPanel value={tab} index={3}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          {t("attendance.bagTableTitle")}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {t("attendance.bagTableHint")}
        </Typography>
        <Box className="table-wrapper" sx={{ mb: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("attendance.bagEffectiveFrom")}</TableCell>
                <TableCell>¢ / bag</TableCell>
                <TableCell>$ / bag</TableCell>
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
        <Stack component="form" onSubmit={saveSettings} spacing={2} sx={{ maxWidth: 400 }}>
          <TextField
            label={t("attendance.maxShift")}
            value={settings.max_shift_hours || ""}
            onChange={(e) => setSettings({ ...settings, max_shift_hours: e.target.value })}
          />
          <TextField
            label={t("attendance.bagDeductionFlag")}
            value={settings.bag_deduction_enabled || ""}
            onChange={(e) => setSettings({ ...settings, bag_deduction_enabled: e.target.value })}
          />
          <Button type="submit" variant="contained">
            {t("attendance.saveSettings")}
          </Button>
        </Stack>
      </TabPanel>

      <TabPanel value={tab} index={4}>
        <Box className="table-wrapper">
          <Table size="small">
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
                  <TableCell>{String(a.created_at)}</TableCell>
                  <TableCell>{a.actor_email || a.actor_user_id}</TableCell>
                  <TableCell>
                    {a.entity_type} #{a.entity_id}
                  </TableCell>
                  <TableCell>{a.action}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </TabPanel>
    </div>
  );
}

export default AttendanceSetupPage;
