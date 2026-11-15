import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Alert, Button, Stack, Typography } from "@mui/material";
import { getPinTraining, savePinTrainingProgress } from "../api";
import { OpsMobileShell, OpsTopBar } from "../opsMobile";
import { loadPinHubSession, pinHubMenuPath } from "../utils/pinHubSession";

function slugOf(raw) {
  try {
    return decodeURIComponent(String(raw || "")).toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 64);
  } catch {
    return "";
  }
}

function statusLabel(row) {
  if (row.competency_result === "pass" || row.status === "completed") return "Competency approved";
  if (row.status === "failed" || row.competency_result === "retrain") return "Retraining required";
  if (row.status === "awaiting_verification") return "Waiting for supervisor";
  if (row.status === "in_progress") return "In progress";
  return "Assigned";
}

export default function PinTrainingPage() {
  const { orgSlug } = useParams();
  const navigate = useNavigate();
  const slug = slugOf(orgSlug);
  const hub = useMemo(() => loadPinHubSession(), []);
  const [rows, setRows] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [error, setError] = useState("");

  const load = () => {
    if (!hub?.token) return Promise.resolve();
    return getPinTraining(hub.token)
      .then((res) => setRows(res.data.assignments || []))
      .catch((err) => setError(err?.response?.data?.error || "Could not load training"));
  };

  useEffect(() => {
    load();
  }, [hub]);

  return (
    <OpsMobileShell>
      <OpsTopBar title="My Training" onBack={() => navigate(pinHubMenuPath(slug))} />
      <Stack spacing={1.25} sx={{ p: 2 }}>
        {!hub?.token ? <Alert severity="warning">Enter your PIN again to open training.</Alert> : null}
        {error ? <Alert severity="error">{error}</Alert> : null}
        {rows && rows.length === 0 ? <Typography color="text.secondary">No training is assigned.</Typography> : null}
        {(rows || []).map((row) => (
          <Stack key={row.id} spacing={1} sx={{ bgcolor: "#fff", border: "1px solid #e6e8ef", borderRadius: 2, p: 1.5 }}>
            <Typography sx={{ fontWeight: 800 }}>{row.title}</Typography>
            <Typography sx={{ fontSize: 13, color: "#64748b" }}>{statusLabel(row)}{row.due_on ? ` · Due ${row.due_on}` : ""}</Typography>
            <Button size="small" onClick={() => setOpenId(openId === row.id ? null : row.id)} sx={{ textTransform: "none", alignSelf: "flex-start" }}>
              {openId === row.id ? "Hide steps" : "Open instructions"}
            </Button>
            {openId === row.id ? (
              <Stack spacing={1}>
                {row.instructions ? <Typography sx={{ fontSize: 14 }}>{row.instructions}</Typography> : null}
                {(row.items || []).map((item) => (
                  <Stack key={item.id} direction="row" justifyContent="space-between" alignItems="center">
                    <Typography sx={{ fontSize: 14 }}>{item.label}{item.required ? "" : " (optional)"}</Typography>
                    <Button
                      size="small"
                      disabled={item.done || row.status === "completed" || row.status === "awaiting_verification"}
                      onClick={() => savePinTrainingProgress({
                        hub_token: hub.token,
                        assignment_id: row.id,
                        item_id: item.id,
                        done: true,
                        status: row.status === "assigned" ? "in_progress" : undefined,
                      }).then(load).catch((err) => setError(err?.response?.data?.error || "Could not save the step"))}
                    >
                      {item.done ? "Done" : "Complete"}
                    </Button>
                  </Stack>
                ))}
                {row.status === "in_progress" || row.status === "assigned" ? (
                  <Button
                    variant="contained"
                    disabled={!row.checklist_complete}
                    onClick={async () => {
                      try {
                        if (row.status === "assigned") {
                          await savePinTrainingProgress({ hub_token: hub.token, assignment_id: row.id, status: "in_progress" });
                        }
                        await savePinTrainingProgress({ hub_token: hub.token, assignment_id: row.id, status: "awaiting_verification" });
                        await load();
                      } catch (err) {
                        setError(err?.response?.data?.error || "Could not submit training");
                      }
                    }}
                    sx={{ textTransform: "none" }}
                  >
                    Submit for verification
                  </Button>
                ) : null}
              </Stack>
            ) : null}
          </Stack>
        ))}
      </Stack>
    </OpsMobileShell>
  );
}
