import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
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
  getTaSettings,
  getUserRates,
  putTaSettings,
} from "../api";
import { useAuth } from "../context/AuthContext";

function TabPanel({ children, value, index }) {
  if (value !== index) return null;
  return <Box sx={{ pt: 2 }}>{children}</Box>;
}

function AttendanceSetupPage() {
  const { hasPerm } = useAuth();
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
  const [rateEff, setRateEff] = useState("");

  const can = hasPerm("ta.settings");

  const loadAll = useCallback(async () => {
    if (!can) return;
    try {
      const [g, c, r, s, a] = await Promise.all([
        getGeofences(),
        getEmploymentCategories(),
        getUserRates(),
        getTaSettings(),
        getAuditLog(),
      ]);
      setGeofences(g.data || []);
      setCats(c.data || []);
      setRates(r.data || []);
      setSettings(s.data || {});
      setAudit(a.data || []);
    } catch (e) {
      setError(e.response?.data?.error || "Load failed");
    }
  }, [can]);

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
        <Alert severity="info">This area is for administrators only.</Alert>
      </div>
    );
  }

  return (
    <div className="page">
      <Typography variant="h4" className="page-title" sx={{ mb: 2 }}>
        Attendance setup
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label="Geofences" />
        <Tab label="Categories" />
        <Tab label="Rates" />
        <Tab label="Settings" />
        <Tab label="Audit" />
      </Tabs>

      <TabPanel value={tab} index={0}>
        <Typography variant="subtitle1" gutterBottom>
          Add geofence
        </Typography>
        <Stack component="form" onSubmit={addGeofence} spacing={2} direction={{ xs: "column", sm: "row" }} useFlexGap flexWrap="wrap">
          <TextField label="Name" value={gfName} onChange={(e) => setGfName(e.target.value)} required />
          <TextField label="Latitude" value={gfLat} onChange={(e) => setGfLat(e.target.value)} required />
          <TextField label="Longitude" value={gfLng} onChange={(e) => setGfLng(e.target.value)} required />
          <TextField label="Radius (m)" value={gfRad} onChange={(e) => setGfRad(e.target.value)} />
          <Button type="submit" variant="contained">
            Save
          </Button>
        </Stack>
        <Box className="table-wrapper" sx={{ mt: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Lat</TableCell>
                <TableCell>Lng</TableCell>
                <TableCell>Radius</TableCell>
                <TableCell>Active</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {geofences.map((g) => (
                <TableRow key={g.id}>
                  <TableCell>{g.name}</TableCell>
                  <TableCell>{g.latitude}</TableCell>
                  <TableCell>{g.longitude}</TableCell>
                  <TableCell>{g.radius_meters}</TableCell>
                  <TableCell>{g.active ? "yes" : "no"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </TabPanel>

      <TabPanel value={tab} index={1}>
        <Stack component="form" onSubmit={addCat} spacing={2} direction="row" useFlexGap flexWrap="wrap">
          <TextField label="Code" value={catCode} onChange={(e) => setCatCode(e.target.value)} required />
          <TextField label="Name" value={catName} onChange={(e) => setCatName(e.target.value)} required />
          <Button type="submit" variant="contained">
            Add category
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
          Create a rate for a user + category + effective date.
        </Typography>
        <Stack component="form" onSubmit={addRate} spacing={2} direction={{ xs: "column", sm: "row" }} useFlexGap flexWrap="wrap">
          <TextField label="User ID" value={rateUser} onChange={(e) => setRateUser(e.target.value)} required />
          <TextField label="Category ID" value={rateCat} onChange={(e) => setRateCat(e.target.value)} required />
          <TextField label="Hourly rate" value={rateAmt} onChange={(e) => setRateAmt(e.target.value)} required />
          <TextField
            label="Effective date"
            type="date"
            InputLabelProps={{ shrink: true }}
            value={rateEff}
            onChange={(e) => setRateEff(e.target.value)}
            required
          />
          <Button type="submit" variant="contained">
            Add rate
          </Button>
        </Stack>
        <Box className="table-wrapper" sx={{ mt: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>User</TableCell>
                <TableCell>Category</TableCell>
                <TableCell>Rate</TableCell>
                <TableCell>From</TableCell>
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
        <Stack component="form" onSubmit={saveSettings} spacing={2} sx={{ maxWidth: 400 }}>
          <TextField
            label="Max shift hours"
            value={settings.max_shift_hours || ""}
            onChange={(e) => setSettings({ ...settings, max_shift_hours: e.target.value })}
          />
          <TextField
            label="Bag deduction enabled (0/1)"
            value={settings.bag_deduction_enabled || ""}
            onChange={(e) => setSettings({ ...settings, bag_deduction_enabled: e.target.value })}
          />
          <Button type="submit" variant="contained">
            Save settings
          </Button>
        </Stack>
      </TabPanel>

      <TabPanel value={tab} index={4}>
        <Box className="table-wrapper">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>When</TableCell>
                <TableCell>Actor</TableCell>
                <TableCell>Entity</TableCell>
                <TableCell>Action</TableCell>
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
