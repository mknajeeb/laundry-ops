import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Container,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import { getPublicRoster, postPublicRosterVerify } from "../api";
import { formatTime12, SCHEDULE_THEME } from "../payroll/scheduleTheme";
import ScheduleEmptyState from "../components/schedule/ScheduleEmptyState";
import EventBusyOutlinedIcon from "@mui/icons-material/EventBusyOutlined";

function friendlyRosterError(raw, status) {
  const msg = String(raw || "").toLowerCase();
  if (status === 404 || msg.includes("invalid")) return "This schedule link is invalid or no longer available.";
  if (msg.includes("revoked")) return "This schedule link has been revoked. Ask your contact for a new link.";
  if (msg.includes("expired")) return "This schedule link has expired. Ask your contact for a new link.";
  if (msg.includes("pin")) return "Incorrect PIN. Please try again.";
  return "We could not load this roster. Please check the link or contact your manager.";
}

function formatDateLong(ymd) {
  try {
    return new Date(`${ymd}T12:00:00`).toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
  } catch {
    return ymd;
  }
}

export default function PartnerRosterPage() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pin, setPin] = useState("");
  const [needsPin, setNeedsPin] = useState(false);

  const load = useCallback(
    async (pinValue) => {
      setLoading(true);
      setError("");
      try {
        const res = await getPublicRoster(token, pinValue ? { pin: pinValue } : {});
        if (res.data?.requires_pin) {
          setNeedsPin(true);
          setData(null);
        } else {
          setNeedsPin(false);
          setData(res.data);
        }
      } catch (e) {
        if (e.response?.status === 401) {
          setNeedsPin(true);
          setError(friendlyRosterError(e.response?.data?.error, 401));
        } else {
          setError(friendlyRosterError(e.response?.data?.error, e.response?.status));
        }
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    load();
  }, [load]);

  const submitPin = async () => {
    try {
      const res = await postPublicRosterVerify(token, { pin });
      setData(res.data);
      setNeedsPin(false);
    } catch (e) {
      setError(friendlyRosterError(e.response?.data?.error, e.response?.status));
    }
  };

  if (loading && !needsPin) {
    return (
      <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", bgcolor: "#f8fafc" }}>
        <CircularProgress />
      </Box>
    );
  }

  if (needsPin) {
    return (
      <Container maxWidth="xs" sx={{ py: 6 }}>
        <Stack spacing={2} alignItems="center">
          <LockOutlinedIcon sx={{ fontSize: 48, color: "primary.main" }} />
          <Typography variant="h6" fontWeight={700}>
            Roster protected
          </Typography>
          <TextField
            label="PIN"
            type="password"
            fullWidth
            value={pin}
            onChange={(e) => setPin(e.target.value)}
          />
          {error ? <Alert severity="error">{error}</Alert> : null}
          <Button variant="contained" fullWidth onClick={submitPin}>
            View roster
          </Button>
        </Stack>
      </Container>
    );
  }

  if (error && !data && !needsPin) {
    return (
      <Container maxWidth="sm" sx={{ py: 4 }}>
        <ScheduleEmptyState icon={EventBusyOutlinedIcon} title="Roster unavailable" description={error} />
      </Container>
    );
  }

  const grouped = data?.grouped_by_date || {};

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#f8fafc", py: 3 }}>
      <Container maxWidth="sm">
        <Box sx={{ mb: 3, textAlign: "center" }}>
          <Typography variant="overline" color="text.secondary">
            {data?.organization_name}
            {data?.location_name ? ` · ${data.location_name}` : ""}
          </Typography>
          <Typography variant="h5" fontWeight={800} sx={{ mt: 0.5 }}>
            {data?.title || "Staff Roster"}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {data?.date_start} – {data?.date_end}
          </Typography>
          <Alert severity="info" sx={{ mt: 2, textAlign: "left" }}>
            Read-only roster. Last updated:{" "}
            {data?.last_updated ? new Date(data.last_updated).toLocaleString() : "—"}
          </Alert>
        </Box>

        <Stack spacing={2.5}>
          {Object.keys(grouped)
            .sort()
            .map((dateKey) => (
              <Card key={dateKey} sx={SCHEDULE_THEME.card}>
                <CardContent>
                  <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>
                    {formatDateLong(dateKey)}
                  </Typography>
                  {Object.entries(grouped[dateKey]).map(([shiftName, workers]) => (
                    <Box key={shiftName} sx={{ mb: 2 }}>
                      <Typography variant="caption" fontWeight={700} color="primary.main" display="block" sx={{ mb: 1 }}>
                        {shiftName}
                      </Typography>
                      <Stack spacing={1}>
                        {(workers || []).map((w, i) => (
                          <Box
                            key={`${w.worker_name}-${i}`}
                            sx={{
                              py: 1,
                              px: 1.25,
                              borderRadius: 2,
                              bgcolor: SCHEDULE_THEME.accentSoft,
                            }}
                          >
                            <Typography variant="body2" fontWeight={600}>
                              {w.worker_name}
                              {w.role ? ` — ${w.role}` : ""}
                              {w.work_stream ? ` — ${w.work_stream}` : ""}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {formatTime12(w.start_time)} – {formatTime12(w.end_time)}
                              {w.status ? ` · ${w.status}` : ""}
                            </Typography>
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  ))}
                </CardContent>
              </Card>
            ))}
          {!Object.keys(grouped).length ? (
            <ScheduleEmptyState
              icon={EventBusyOutlinedIcon}
              title="No published schedule yet"
              description="Shifts may not have been published for this date range. Check back later or contact your manager."
            />
          ) : null}
        </Stack>
      </Container>
    </Box>
  );
}
