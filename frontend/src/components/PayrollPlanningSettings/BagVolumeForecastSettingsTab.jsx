import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import {
  FORECAST_METHODS,
  TARGET_COMPLETION_OPTIONS,
  UNIT_TYPES,
  newRoleSpeedRow,
  normalizeBagVolumeForecast,
  normalizeRoleSpeedRow,
} from "../../payroll/bagVolumeForecastSettings";

export default function BagVolumeForecastSettingsTab({ extras, setExtras, settings, saving, onSave }) {
  const roles = (settings?.roles || []).filter((r) => r.active);
  const streams = (settings?.work_streams || []).filter((s) => s.active);

  const bag = useMemo(
    () => normalizeBagVolumeForecast(extras?.bag_volume_forecast, extras?.forecast_assumptions),
    [extras],
  );

  const [editRow, setEditRow] = useState(null);
  const validationErrors = extras?.bag_volume_forecast_validation_errors || [];

  const updateBag = (patch) => {
    setExtras({
      ...extras,
      bag_volume_forecast: { ...bag, ...patch },
    });
  };

  const saveBagForecast = () => {
    onSave({ bag_volume_forecast: bag });
  };

  const params = bag.role_speed_parameters || [];

  const commitRow = () => {
    if (!editRow?.role_id || !editRow.planning_speed) return;
    const role = roles.find((r) => String(r.id) === String(editRow.role_id));
    const stream = streams.find((s) => String(s.id) === String(editRow.work_stream_id));
    const normalized = normalizeRoleSpeedRow({
      ...editRow,
      role_name: role?.name || editRow.role_name,
      work_stream_name: stream?.name || editRow.work_stream_name,
    });
    const idx = params.findIndex((p) => p.id === normalized.id);
    const next =
      idx >= 0
        ? params.map((p, i) => (i === idx ? normalized : p))
        : [...params, normalized];
    updateBag({ role_speed_parameters: next });
    setEditRow(null);
  };

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Prepares bag-volume labor forecasting for a future release. Does not change the Scheduling screen or funding
        forecast today. Role speeds link to the same performance mapping used for worker suggestions.
      </Alert>

      {validationErrors.length ? (
        <Alert severity="warning">{validationErrors.join(" · ")}</Alert>
      ) : null}

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1 }}>
            Default forecast method
          </Typography>
          <ToggleButtonGroup
            exclusive
            value={bag.default_method || "compare"}
            onChange={(_, v) => v && updateBag({ default_method: v })}
            size="small"
            sx={{ flexWrap: "wrap" }}
          >
            {FORECAST_METHODS.map((m) => (
              <ToggleButton key={m.id} value={m.id} sx={{ minHeight: 40 }}>
                {m.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            Compare both will show planning-parameter vs actual-performance side by side when calculations ship.
          </Typography>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>
            Global planning inputs
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} flexWrap="wrap" useFlexGap>
            <TextField
              size="small"
              label="Default bag count (what-if)"
              type="number"
              value={bag.global_defaults?.default_bag_count ?? 100}
              onChange={(e) =>
                updateBag({
                  global_defaults: {
                    ...bag.global_defaults,
                    default_bag_count: Number(e.target.value) || 0,
                  },
                })
              }
            />
            <TextField
              size="small"
              label="Average bag weight (lbs)"
              type="number"
              value={bag.global_defaults?.average_bag_weight_lbs ?? ""}
              onChange={(e) =>
                updateBag({
                  global_defaults: {
                    ...bag.global_defaults,
                    average_bag_weight_lbs: e.target.value === "" ? null : Number(e.target.value),
                  },
                })
              }
            />
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Target completion</InputLabel>
              <Select
                label="Target completion"
                value={bag.global_defaults?.target_completion || "same_day"}
                onChange={(e) =>
                  updateBag({
                    global_defaults: { ...bag.global_defaults, target_completion: e.target.value },
                  })
                }
              >
                {TARGET_COMPLETION_OPTIONS.map((o) => (
                  <MenuItem key={o.id} value={o.id}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>
          <TextField
            fullWidth
            size="small"
            multiline
            minRows={2}
            label="Notes"
            sx={{ mt: 2 }}
            value={bag.global_defaults?.notes || ""}
            onChange={(e) =>
              updateBag({ global_defaults: { ...bag.global_defaults, notes: e.target.value } })
            }
          />
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Box>
              <Typography variant="subtitle1" fontWeight={800}>
                Role speed parameters (planning method)
              </Typography>
              <Typography variant="caption" color="text.secondary">
                By role + work stream — e.g. Rinse + Folder = 4 bags/hour
              </Typography>
            </Box>
            <Button
              size="small"
              startIcon={<AddIcon />}
              variant="outlined"
              onClick={() => setEditRow(newRoleSpeedRow(roles, streams))}
            >
              Add parameter
            </Button>
          </Stack>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Role</TableCell>
                <TableCell>Stream</TableCell>
                <TableCell>Unit</TableCell>
                <TableCell align="right">Speed</TableCell>
                <TableCell>Active</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {params.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.role_name || row.role_id}</TableCell>
                  <TableCell>{row.work_stream_name || "—"}</TableCell>
                  <TableCell>
                    {UNIT_TYPES.find((u) => u.id === row.unit_type)?.label || row.unit_type}
                  </TableCell>
                  <TableCell align="right">{row.planning_speed}</TableCell>
                  <TableCell>
                    <Chip size="small" label={row.active ? "Yes" : "No"} color={row.active ? "success" : "default"} />
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={() => setEditRow({ ...row })}>
                      <EditOutlinedIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      onClick={() =>
                        updateBag({
                          role_speed_parameters: params.filter((p) => p.id !== row.id),
                        })
                      }
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
              {!params.length ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Typography variant="body2" color="text.secondary">
                      No parameters yet — add Rinse Folder, Rinse Operator, Drop Off Folder, etc.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1 }}>
            Actual performance method
          </Typography>
          <Stack spacing={1}>
            <FormControlLabel
              control={
                <Switch
                  checked={bag.performance_link?.use_rinse_folding_productivity !== false}
                  onChange={(e) =>
                    updateBag({
                      performance_link: {
                        ...bag.performance_link,
                        use_rinse_folding_productivity: e.target.checked,
                      },
                    })
                  }
                />
              }
              label="Use Rinse folding productivity / performance mapping"
            />
            <TextField
              size="small"
              type="number"
              label="Lookback days"
              value={bag.performance_link?.lookback_days ?? 30}
              onChange={(e) =>
                updateBag({
                  performance_link: {
                    ...bag.performance_link,
                    lookback_days: Number(e.target.value) || 30,
                  },
                })
              }
              sx={{ maxWidth: 160 }}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={bag.performance_link?.fallback_to_planning_when_no_data !== false}
                  onChange={(e) =>
                    updateBag({
                      performance_link: {
                        ...bag.performance_link,
                        fallback_to_planning_when_no_data: e.target.checked,
                      },
                    })
                  }
                />
              }
              label="Fall back to planning parameters when no performance data"
            />
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ bgcolor: "action.hover" }}>
        <CardContent>
          <Typography variant="subtitle2" fontWeight={800} gutterBottom>
            Future on Scheduling (not active)
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Will compare required labor vs roster, show bottlenecks, suggest workers (same rules as Find Replacement),
            and optional draft shifts — separate from payroll batch.
          </Typography>
          <FormControlLabel
            sx={{ mt: 1 }}
            control={
              <Switch
                checked={!!bag.calculations_enabled}
                onChange={(e) => updateBag({ calculations_enabled: e.target.checked })}
              />
            }
            label="Enable calculations (dev preview — still hidden from Scheduling)"
          />
        </CardContent>
      </Card>

      <Button variant="contained" disabled={saving} onClick={saveBagForecast}>
        Save bag volume forecast settings
      </Button>

      <Dialog open={!!editRow} onClose={() => setEditRow(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{params.some((p) => p.id === editRow?.id) ? "Edit" : "Add"} speed parameter</DialogTitle>
        <DialogContent>
          {editRow ? (
            <Stack spacing={2} sx={{ pt: 1 }}>
              <FormControl size="small" fullWidth>
                <InputLabel>Role</InputLabel>
                <Select
                  label="Role"
                  value={String(editRow.role_id || "")}
                  onChange={(e) => setEditRow({ ...editRow, role_id: e.target.value })}
                >
                  {roles.map((r) => (
                    <MenuItem key={r.id} value={String(r.id)}>
                      {r.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" fullWidth>
                <InputLabel>Work stream</InputLabel>
                <Select
                  label="Work stream"
                  value={String(editRow.work_stream_id || "")}
                  onChange={(e) => setEditRow({ ...editRow, work_stream_id: e.target.value })}
                >
                  <MenuItem value="">—</MenuItem>
                  {streams.map((s) => (
                    <MenuItem key={s.id} value={String(s.id)}>
                      {s.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" fullWidth>
                <InputLabel>Unit type</InputLabel>
                <Select
                  label="Unit type"
                  value={editRow.unit_type || "bags_per_hour"}
                  onChange={(e) => setEditRow({ ...editRow, unit_type: e.target.value })}
                >
                  {UNIT_TYPES.map((u) => (
                    <MenuItem key={u.id} value={u.id}>
                      {u.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                label="Planning speed"
                type="number"
                size="small"
                fullWidth
                value={editRow.planning_speed}
                onChange={(e) => setEditRow({ ...editRow, planning_speed: e.target.value })}
                helperText="Management assumption for planning-parameter forecast"
              />
              <TextField
                label="Notes"
                size="small"
                fullWidth
                value={editRow.notes || ""}
                onChange={(e) => setEditRow({ ...editRow, notes: e.target.value })}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={editRow.active !== false}
                    onChange={(e) => setEditRow({ ...editRow, active: e.target.checked })}
                  />
                }
                label="Active"
              />
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditRow(null)}>Cancel</Button>
          <Button variant="contained" onClick={commitRow}>
            Save row
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
