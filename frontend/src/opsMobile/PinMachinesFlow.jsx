import { useEffect, useMemo, useState } from "react";
import { Alert, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";
import { getFacilityMachine, getFacilityMachines, patchFacilityMachine } from "../api";
import { useI18n } from "../i18n/I18nContext";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";

const STATUSES = ["operational", "needs_attention", "out_of_service", "under_repair", "retired"];

const STATUS_LABEL = {
  operational: "Operational",
  needs_attention: "Needs Attention",
  out_of_service: "Out of Service",
  under_repair: "Under Repair",
  retired: "Retired/Inactive",
};

export default function PinMachinesFlow({ onBack, onLock, orgSlug = "", preview = null }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [kind, setKind] = useState("washer");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState(preview?.machines || []);
  const [canUpdate, setCanUpdate] = useState(Boolean(preview?.canUpdate));
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!preview);

  useEffect(() => {
    if (preview) return undefined;
    let cancel = false;
    setLoading(true);
    getFacilityMachines({ type: kind, status: status || undefined })
      .then((res) => {
        if (cancel) return;
        setRows(res?.data?.machines || []);
        setCanUpdate(Boolean(res?.data?.can_update));
        setLoading(false);
      })
      .catch((err) => {
        if (cancel) return;
        setError(err?.response?.data?.error || err?.message || "Could not load machines");
        setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [preview, kind, status]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (row.machine_type !== kind) return false;
      if (status && row.operational_status !== status) return false;
      if (!q) return true;
      return String(row.display_number || row.machine_code).toLowerCase().includes(q);
    });
  }, [rows, kind, status, query]);

  const summary = useMemo(() => {
    const counts = {};
    for (const row of rows.filter((item) => item.machine_type === kind)) {
      counts[row.operational_status] = (counts[row.operational_status] || 0) + 1;
    }
    return counts;
  }, [rows, kind]);

  const open = async (row) => {
    if (preview) {
      setSelected({ ...row, issues: row.issues || [], events: row.events || [] });
      return;
    }
    const res = await getFacilityMachine(row.machine_code);
    setSelected(res?.data || null);
    setCanUpdate(Boolean(res?.data?.can_update));
  };

  const changeStatus = async (next) => {
    if (!selected?.machine && !selected?.machine_code) return;
    const code = selected.machine?.machine_code || selected.machine_code;
    if (preview) {
      setSelected({ ...selected, operational_status: next, machine: { ...(selected.machine || selected), operational_status: next } });
      setRows((current) => current.map((row) => (row.machine_code === code ? { ...row, operational_status: next } : row)));
      return;
    }
    await patchFacilityMachine(code, { operational_status: next });
    await open({ machine_code: code });
  };

  const report = (machine) => {
    const code = machine.machine_code;
    const type = machine.machine_type === "dryer" ? "dryer" : "washer";
    if (!orgSlug) return;
    navigate(`/attendance/lost-found/${encodeURIComponent(orgSlug)}?category=equipment&kind=${type}&number=${encodeURIComponent(code)}`);
  };

  const machine = selected?.machine || selected;

  return (
    <OpsMobileShell>
      <OpsTopBar
        title={machine && selected ? "Machine" : t("pinMgmt.machines")}
        backLabel={selected ? t("pinMgmt.machines") : "PIN"}
        onBack={selected ? () => setSelected(null) : onBack}
        onLock={onLock}
      />
      <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", pb: 2 }}>
        <Stack spacing={1.25} sx={{ pt: 1 }}>
          {error ? <Alert severity="error">{error}</Alert> : null}
          {selected && machine ? (
            <Stack spacing={1}>
              <Typography fontWeight={800}>{machine.display_number}</Typography>
              <Typography variant="body2">{STATUS_LABEL[machine.operational_status] || machine.operational_status}</Typography>
              {machine.capacity_lbs != null ? <Typography variant="body2">{machine.capacity_lbs} lb</Typography> : null}
              {machine.remarks ? <Typography variant="body2">{machine.remarks}</Typography> : null}
              {machine.exclusion_review ? (
                <Alert severity="info">Out of service needs an exclusion review. Past cleaning targets stay as they were.</Alert>
              ) : null}
              <Button variant="contained" sx={{ minHeight: 44 }} onClick={() => report(machine)}>
                Report Issue
              </Button>
              {(selected.issues || []).map((issue) => (
                <Typography key={issue.id} variant="body2">
                  #{issue.id} · {issue.status} · {issue.location_label || issue.description || "Report"}
                </Typography>
              ))}
              {(selected.events || []).map((event, index) => (
                <Typography key={index} variant="caption" display="block">
                  {event.event_type} · user {event.actor_user_id || "—"} · {event.detail}
                </Typography>
              ))}
              {canUpdate ? (
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  {STATUSES.map((item) => (
                    <Button key={item} size="small" variant="outlined" sx={{ minHeight: 40 }} onClick={() => changeStatus(item)}>
                      {STATUS_LABEL[item]}
                    </Button>
                  ))}
                </Stack>
              ) : null}
            </Stack>
          ) : (
            <>
              <Stack direction="row" spacing={1}>
                <Button variant={kind === "washer" ? "contained" : "outlined"} onClick={() => setKind("washer")} sx={{ minHeight: 40 }}>
                  Washers
                </Button>
                <Button variant={kind === "dryer" ? "contained" : "outlined"} onClick={() => setKind("dryer")} sx={{ minHeight: 40 }}>
                  Dryers
                </Button>
              </Stack>
              <TextField size="small" label="Search" value={query} onChange={(event) => setQuery(event.target.value)} />
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                <Button size="small" variant={status === "" ? "contained" : "outlined"} onClick={() => setStatus("")}>
                  All {rows.filter((row) => row.machine_type === kind).length}
                </Button>
                {STATUSES.map((item) => (
                  <Button key={item} size="small" variant={status === item ? "contained" : "outlined"} onClick={() => setStatus(item)}>
                    {STATUS_LABEL[item]} {summary[item] || 0}
                  </Button>
                ))}
              </Stack>
              {loading ? <Typography variant="body2">Loading…</Typography> : null}
              {!loading && !visible.length ? <Alert severity="info">No machines match.</Alert> : null}
              {visible.map((row) => (
                <Box
                  key={row.machine_code}
                  component="button"
                  onClick={() => open(row)}
                  sx={{
                    textAlign: "left",
                    width: "100%",
                    p: 1.25,
                    borderRadius: 2,
                    border: `1px solid ${OPS_MOBILE.border}`,
                    bgcolor: "#fff",
                  }}
                >
                  <Typography fontWeight={800}>{row.display_number}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {STATUS_LABEL[row.operational_status]}
                    {row.cleaning_eligible ? "" : " · Excluded from cleaning"}
                  </Typography>
                </Box>
              ))}
            </>
          )}
        </Stack>
      </Box>
    </OpsMobileShell>
  );
}
