import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getTaUsers } from "../api";
import { useAuth } from "../context/AuthContext";
import HrTimelinePanel from "./hr/HrTimelinePanel";
import {
  filterPayrollTimelineUsers,
  mapAccountantDocumentUserOption,
  workerLaneForCategory,
} from "../payroll/accountantDocumentUsers";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const CATEGORY_LABELS = {
  w2: "W-2 employee",
  contractor_1099: "1099 contractor",
  temp: "Temp worker",
};

/**
 * HR Timeline inside Payroll Management → Documents.
 * Optional controlled worker (shared with document checklist when embedded).
 */
export default function PayrollHrTimelinePanel({
  category = "w2",
  selectedWorker = null,
  onWorkerChange = null,
  compact = false,
}) {
  const { hasPerm, user } = useAuth();
  const canEdit = hasPerm("users.edit") || hasPerm("ta.settings");
  const managerName = user?.name || user?.email || "";

  const [workers, setWorkers] = useState([]);
  const [internalSelected, setInternalSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selected = onWorkerChange ? selectedWorker : internalSelected;
  const setSelected = onWorkerChange || setInternalSelected;

  const loadWorkers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getTaUsers();
      const raw = res.data?.users || res.data || [];
      const list = filterPayrollTimelineUsers(raw, category).map(mapAccountantDocumentUserOption);
      list.sort((a, b) => String(a.label).localeCompare(String(b.label)));
      setWorkers(list);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load workers");
      setWorkers([]);
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    loadWorkers();
  }, [loadWorkers]);

  useEffect(() => {
    if (!onWorkerChange) setInternalSelected(null);
  }, [category, onWorkerChange]);

  const workerLane = useMemo(() => workerLaneForCategory(category), [category]);

  return (
    <Stack spacing={2}>
      {!compact ? (
        <Paper variant="outlined" sx={{ p: 2, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}>
          <Typography variant="subtitle1" fontWeight={700}>
            HR Timeline
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Internal discipline log for {CATEGORY_LABELS[category] || "payroll workers"} — email
            templates + timeline entries. No worker signatures.
          </Typography>
        </Paper>
      ) : null}

      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {!onWorkerChange ? (
        <Autocomplete
          size="small"
          options={workers}
          value={selected}
          onChange={(_, val) => setSelected(val)}
          getOptionLabel={(opt) => opt?.label || ""}
          isOptionEqualToValue={(a, b) => a?.id === b?.id}
          loading={loading}
          renderInput={(params) => (
            <TextField
              {...params}
              label={`Select ${CATEGORY_LABELS[category] || "worker"}`}
              InputProps={{
                ...params.InputProps,
                endAdornment: (
                  <>
                    {loading ? <CircularProgress color="inherit" size={18} /> : null}
                    {params.InputProps.endAdornment}
                  </>
                ),
              }}
            />
          )}
          sx={{ maxWidth: 420 }}
        />
      ) : null}

      {selected?.id ? (
        <HrTimelinePanel
          userId={selected.id}
          workerName={selected.label}
          workerLane={workerLane}
          managerName={managerName}
          canEdit={canEdit}
        />
      ) : (
        <Typography variant="body2" color="text.secondary">
          {onWorkerChange
            ? "Select an employee above to view or add HR Timeline entries."
            : "Choose a worker to view coaching, warnings, and internal notes."}
        </Typography>
      )}
    </Stack>
  );
}
