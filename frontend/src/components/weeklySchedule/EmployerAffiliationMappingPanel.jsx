import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { getPayrollEmployerAffiliations, putPayrollEmployerAffiliation } from "../../api";
import { useAuth } from "../../context/AuthContext";
import {
  EMPLOYER_AFFILIATION,
  employerAffiliationFromFlags,
  employerAffiliationLabel,
  entityLabel,
  entitySummaryTitle,
  workerEntityOptionsForOrganization,
} from "../../payroll/employerAffiliation";
import { defaultEntityForOrg, normalizeOrgSlug } from "../../payroll/businessEntity";

function tabPreviewChips(affiliation, organizationSlug) {
  const slug = normalizeOrgSlug(organizationSlug);
  if (affiliation === EMPLOYER_AFFILIATION.NONE) {
    return [
      <Chip key="none" size="small" label="No entity tabs" variant="outlined" color="default" />,
    ];
  }
  if (affiliation === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE) {
    return [<Chip key="rinse" size="small" label="Rinse Exclusive tab" color="primary" variant="outlined" />];
  }
  if (affiliation === EMPLOYER_AFFILIATION.SHARED) {
    return [
      <Chip key="shared" size="small" label="Shared (multi-entity tabs)" color="info" variant="outlined" />,
    ];
  }
  if (affiliation === EMPLOYER_AFFILIATION.WASHMATE) {
    return [<Chip key="washmate" size="small" label="WashMate tab" color="secondary" variant="outlined" />];
  }
  if (affiliation === EMPLOYER_AFFILIATION.VEEWASH || (affiliation === EMPLOYER_AFFILIATION.WASHPRO && slug === "veewash")) {
    return [<Chip key="veewash" size="small" label="VeeWash tab" color="secondary" variant="outlined" />];
  }
  if (affiliation === EMPLOYER_AFFILIATION.WASHPRO) {
    return [<Chip key="washpro" size="small" label="WashPro tab" color="secondary" variant="outlined" />];
  }
  return [
    <Chip key="default" size="small" label={`${entityLabel(defaultEntityForOrg(slug))} tab`} color="secondary" variant="outlined" />,
  ];
}

export default function EmployerAffiliationMappingPanel() {
  const { user } = useAuth();
  const organizationSlug = user?.organization_slug || null;
  const entityOptions = useMemo(
    () => workerEntityOptionsForOrganization(organizationSlug),
    [organizationSlug],
  );
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [savingUserId, setSavingUserId] = useState(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const res = await getPayrollEmployerAffiliations();
      setRows(res.data?.items || []);
    } catch (e) {
      setMessage(e?.response?.data?.error || e?.message || "Failed to load business entities");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const counts = useMemo(() => {
    const tally = Object.fromEntries(entityOptions.map((opt) => [opt.value, 0]));
    for (const row of rows) {
      let aff = row.business_entity || row.employer_affiliation || employerAffiliationFromFlags(row, organizationSlug);
      if (aff === "both") aff = EMPLOYER_AFFILIATION.SHARED;
      if (normalizeOrgSlug(organizationSlug) === "veewash" && aff === EMPLOYER_AFFILIATION.WASHPRO) {
        aff = EMPLOYER_AFFILIATION.VEEWASH;
      }
      if (tally[aff] != null) tally[aff] += 1;
    }
    return tally;
  }, [rows, entityOptions, organizationSlug]);

  const saveAffiliation = async (row, nextAffiliation) => {
    if (!row?.user_id || nextAffiliation === row.employer_affiliation) return;
    setSavingUserId(row.user_id);
    setMessage("");
    try {
      const res = await putPayrollEmployerAffiliation(row.user_id, {
        employer_affiliation: nextAffiliation,
      });
      const updated = res.data || {};
      setRows((prev) =>
        prev.map((item) =>
          item.user_id === row.user_id
            ? {
                ...item,
                ...updated,
                employer_affiliation: updated.employer_affiliation || nextAffiliation,
                business_entity: updated.business_entity || nextAffiliation,
              }
            : item,
        ),
      );
    } catch (e) {
      setMessage(e?.response?.data?.error || "Could not save business entity");
    } finally {
      setSavingUserId(null);
    }
  };

  const resolveRowAffiliation = (row) => {
    let aff = row.business_entity || row.employer_affiliation || employerAffiliationFromFlags(row, organizationSlug);
    if (aff === "both") aff = EMPLOYER_AFFILIATION.SHARED;
    if (normalizeOrgSlug(organizationSlug) === "veewash" && aff === EMPLOYER_AFFILIATION.WASHPRO) {
      aff = EMPLOYER_AFFILIATION.VEEWASH;
    }
    const allowed = new Set(entityOptions.map((opt) => opt.value));
    return allowed.has(aff) ? aff : defaultEntityForOrg(organizationSlug);
  };

  return (
    <Paper sx={{ p: 2, mb: 3, border: "1px dashed", borderColor: "divider" }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Business entity ({entitySummaryTitle(organizationSlug)})
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" mb={1.5}>
        Stored on each worker&apos;s payroll scheduling profile. Controls which Weekly Schedule entity tabs they appear on.
        Use <strong>None</strong> for system / admin accounts that should not appear on entity-specific schedule tabs.
        Changes here are the same as editing the profile under People → Scheduling.
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        {entityOptions.map((opt) => (
          <Chip key={opt.value} size="small" label={`${opt.label}: ${counts[opt.value] || 0}`} />
        ))}
      </Stack>
      {message ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setMessage("")}>
          {message}
        </Alert>
      ) : null}
      {loading ? (
        <Stack alignItems="center" py={3}>
          <CircularProgress size={28} />
        </Stack>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Employee</TableCell>
              <TableCell sx={{ minWidth: 190 }}>Business entity</TableCell>
              <TableCell>Weekly schedule tabs</TableCell>
              <TableCell align="right">Profile</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} align="center">
                  No active payroll workers found.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const affiliation = resolveRowAffiliation(row);
                return (
                  <TableRow key={row.user_id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>
                        {row.display_name || `User #${row.user_id}`}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        User #{row.user_id}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <FormControl size="small" fullWidth disabled={savingUserId === row.user_id}>
                        <InputLabel>Entity</InputLabel>
                        <Select
                          label="Entity"
                          value={affiliation}
                          onChange={(e) => saveAffiliation(row, e.target.value)}
                        >
                          {entityOptions.map((opt) => (
                            <MenuItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                        {tabPreviewChips(affiliation, organizationSlug)}
                      </Stack>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                        {employerAffiliationLabel(affiliation)}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography
                        component={RouterLink}
                        to={`/employees/${row.user_id}`}
                        variant="body2"
                        sx={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 0.5,
                          textDecoration: "none",
                          color: "primary.main",
                          fontWeight: 600,
                        }}
                      >
                        Open profile
                        <OpenInNewIcon sx={{ fontSize: 14 }} />
                      </Typography>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      )}
    </Paper>
  );
}
