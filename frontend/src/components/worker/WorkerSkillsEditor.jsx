import {
  Box,
  Checkbox,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { SKILL_LEVELS } from "../../payroll/workerSchedulingProfile";

function skillKey(roleId, streamId) {
  return `${roleId}:${streamId || ""}`;
}

export default function WorkerSkillsEditor({ value, onChange, roles = [], streams = [] }) {
  const activeRoles = (roles || []).filter((r) => r.active);
  const activeStreams = (streams || []).filter((s) => s.active);
  const skills = value || [];

  const findSkill = (roleId, streamId) =>
    skills.find(
      (s) => String(s.role_id) === String(roleId) && String(s.work_stream_id || "") === String(streamId || ""),
    );

  const toggleSkill = (roleId, streamId, checked) => {
    const existing = findSkill(roleId, streamId);
    if (checked && !existing) {
      onChange([
        ...skills,
        { role_id: Number(roleId), work_stream_id: streamId ? Number(streamId) : null, skill_level: 2, active: true },
      ]);
    } else if (!checked && existing) {
      onChange(skills.filter((s) => skillKey(s.role_id, s.work_stream_id) !== skillKey(roleId, streamId)));
    } else if (existing) {
      onChange(
        skills.map((s) =>
          skillKey(s.role_id, s.work_stream_id) === skillKey(roleId, streamId) ? { ...s, active: checked } : s,
        ),
      );
    }
  };

  const setLevel = (roleId, streamId, level) => {
    onChange(
      skills.map((s) =>
        skillKey(s.role_id, s.work_stream_id) === skillKey(roleId, streamId)
          ? { ...s, skill_level: Number(level), active: true }
          : s,
      ),
    );
  };

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Assign role + work stream combinations. Used for scheduling eligibility and replacement ranking.
      </Typography>
      <Box className="table-wrapper">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Work stream</TableCell>
              {activeRoles.map((r) => (
                <TableCell key={r.id} align="center">
                  {r.name}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {activeStreams.map((stream) => (
              <TableRow key={stream.id}>
                <TableCell>{stream.name}</TableCell>
                {activeRoles.map((role) => {
                  const sk = findSkill(role.id, stream.id);
                  const checked = !!(sk && sk.active !== false);
                  return (
                    <TableCell key={role.id} align="center">
                      <Stack alignItems="center" spacing={0.5}>
                        <Checkbox
                          size="small"
                          checked={checked}
                          onChange={(e) => toggleSkill(role.id, stream.id, e.target.checked)}
                        />
                        {checked ? (
                          <FormControl size="small" sx={{ minWidth: 96 }}>
                            <InputLabel>Level</InputLabel>
                            <Select
                              label="Level"
                              value={sk?.skill_level || 2}
                              onChange={(e) => setLevel(role.id, stream.id, e.target.value)}
                            >
                              {SKILL_LEVELS.map((lv) => (
                                <MenuItem key={lv.value} value={lv.value}>
                                  {lv.label}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        ) : null}
                      </Stack>
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Box>
  );
}
