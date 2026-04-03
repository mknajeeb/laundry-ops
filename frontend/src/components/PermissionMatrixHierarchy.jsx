import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Checkbox,
  Chip,
  FormControlLabel,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import PeopleOutlineIcon from "@mui/icons-material/PeopleOutline";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import GavelOutlinedIcon from "@mui/icons-material/GavelOutlined";
import ScheduleOutlinedIcon from "@mui/icons-material/ScheduleOutlined";
import MapOutlinedIcon from "@mui/icons-material/MapOutlined";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import PaymentsOutlinedIcon from "@mui/icons-material/PaymentsOutlined";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import ExtensionOutlinedIcon from "@mui/icons-material/ExtensionOutlined";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import {
  PERMISSION_DESCRIPTION_OVERRIDES,
  PERMISSION_KEY_DISPLAY_OVERRIDES,
  buildSyntheticModuleHierarchy,
  displayPermissionKey,
  normalizeHierarchyRoutes,
} from "../constants/permissionMatrixLayout";

function PermKeyPill({ permKey }) {
  const label = displayPermissionKey(permKey) || "—";
  return (
    <Chip
      size="small"
      label={label}
      variant="outlined"
      sx={{
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontWeight: 600,
        fontSize: "0.8rem",
        height: 26,
        maxWidth: "100%",
        "& .MuiChip-label": { px: 1, overflow: "hidden", textOverflow: "ellipsis" },
      }}
    />
  );
}

function SectionHeaderIcon({ label }) {
  const sx = { fontSize: 20 };
  switch (label) {
    case "User accounts":
      return <PeopleOutlineIcon sx={sx} />;
    case "Overrides & corrections":
      return <GavelOutlinedIcon sx={sx} />;
    case "Clock / sessions":
      return <ScheduleOutlinedIcon sx={sx} />;
    case "Geofences, categories, settings":
      return <MapOutlinedIcon sx={sx} />;
    case "Live monitor":
      return <DashboardOutlinedIcon sx={sx} />;
    case "Payroll payments":
      return <PaymentsOutlinedIcon sx={sx} />;
    case "Reports & exports":
      return <AssessmentOutlinedIcon sx={sx} />;
    default:
      return <ExtensionOutlinedIcon sx={sx} />;
  }
}

function ModuleHeaderIcon({ routeKey }) {
  const sx = { fontSize: 26 };
  switch (routeKey) {
    case "access":
      return <PeopleOutlineIcon sx={sx} />;
    case "time_attendance":
      return <WorkOutlineIcon sx={sx} />;
    default:
      return <ExtensionOutlinedIcon sx={sx} />;
  }
}

function ActionCrudCell({ actionKey }) {
  const k = String(actionKey || "view").toLowerCase();
  let Icon = VisibilityOutlinedIcon;
  if (k === "create" || k === "add") Icon = PersonAddAltOutlinedIcon;
  else if (k === "update" || k === "edit") Icon = EditOutlinedIcon;
  else if (k === "delete" || k === "remove") Icon = DeleteOutlineIcon;
  else if (k === "manage") Icon = TuneOutlinedIcon;
  const label = k;
  return (
    <Tooltip title={label} placement="left">
      <Box
        component="span"
        sx={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 36,
          height: 36,
          borderRadius: 1,
          bgcolor: (theme) => (theme.palette.mode === "dark" ? "action.selected" : "grey.100"),
          color: "primary.main",
        }}
      >
        <Icon sx={{ fontSize: 20 }} />
      </Box>
    </Tooltip>
  );
}

function groupedFlatToPermissions(groupedFlat) {
  const perms = [];
  for (const grp of Object.keys(groupedFlat || {})) {
    for (const p of groupedFlat[grp] || []) {
      perms.push({ ...p });
    }
  }
  return perms;
}

function actionLabel(a) {
  return (a.action_key || "view").toLowerCase();
}

function rowDescription(a) {
  const pk = a.perm_key || "";
  if (PERMISSION_DESCRIPTION_OVERRIDES[pk]) return PERMISSION_DESCRIPTION_OVERRIDES[pk];
  return a.description || "—";
}

function CrudTable({ resources, t, selected, setSelected, readOnly }) {
  return (
    <Table
      size="small"
      sx={{
        "& .MuiTableCell-head": {
          fontWeight: 700,
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          color: "text.secondary",
          borderBottom: "2px solid",
          borderColor: "divider",
          bgcolor: "transparent",
        },
        "& .MuiTableRow-root:nth-of-type(even) .MuiTableCell-body": {
          bgcolor: (theme) => (theme.palette.mode === "dark" ? "action.hover" : "grey.50"),
        },
      }}
    >
      <TableHead>
        <TableRow>
          <TableCell width={72} align="center">
            {t("permissions.colActionCrud")}
          </TableCell>
          <TableCell width={200}>{t("permissions.colPermission")}</TableCell>
          <TableCell>{t("permissions.colDescription")}</TableCell>
          <TableCell align="center" width={88}>
            {t("permissions.colAllow")}
          </TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {(resources || []).flatMap((res) =>
          (res.actions || []).map((a) => (
            <TableRow key={a.perm_key} hover>
              <TableCell align="center">
                <ActionCrudCell actionKey={a.action_key} />
              </TableCell>
              <TableCell>
                <PermKeyPill permKey={a.perm_key} />
              </TableCell>
              <TableCell>
                <Typography variant="body2" color="text.secondary">
                  {rowDescription(a)}
                </Typography>
              </TableCell>
              <TableCell align="center">
                <Checkbox
                  size="small"
                  checked={!!selected[a.perm_key]}
                  disabled={readOnly}
                  onChange={(e) =>
                    setSelected((prev) => ({
                      ...prev,
                      [a.perm_key]: e.target.checked,
                    }))
                  }
                />
              </TableCell>
            </TableRow>
          )),
        )}
      </TableBody>
    </Table>
  );
}

/** Module → tab/function → CRUD (three-level hierarchy). */
function renderModuleTabCrudHierarchy(routes, t, selected, setSelected, readOnly) {
  return (
    <Stack spacing={3}>
      {routes.map((route) => (
        <Paper
          key={route.route_key}
          elevation={0}
          sx={{
            borderRadius: 2,
            overflow: "hidden",
            border: "1px solid",
            borderColor: "divider",
            borderLeftWidth: 4,
            borderLeftColor: (theme) => theme.palette.primary.dark,
          }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 2,
              px: 2,
              py: 1.75,
              bgcolor: (theme) => (theme.palette.mode === "dark" ? "action.hover" : "grey.100"),
              borderBottom: "1px solid",
              borderColor: "divider",
            }}
          >
            <Box
              sx={{
                width: 48,
                height: 48,
                borderRadius: 1.5,
                display: "grid",
                placeItems: "center",
                bgcolor: "background.paper",
                color: "primary.main",
                border: "1px solid",
                borderColor: "divider",
              }}
            >
              <ModuleHeaderIcon routeKey={route.route_key} />
            </Box>
            <Box sx={{ minWidth: 0 }}>
              <Typography
                variant="overline"
                color="text.secondary"
                sx={{ display: "block", letterSpacing: 1.2, lineHeight: 1.2 }}
              >
                {t("permissions.moduleLevel")}
              </Typography>
              <Typography variant="h6" sx={{ fontWeight: 700, fontSize: "1.1rem", color: "text.primary" }}>
                {route.route_label || route.route_key}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.25 }}>
                {t("permissions.routeKeyHint")}: {route.route_key}
              </Typography>
            </Box>
          </Box>

          <Stack spacing={2} sx={{ p: 2 }}>
            {(route.sections || []).map((sec) => (
              <Box
                key={`${route.route_key}-${sec.section_key}`}
                sx={{
                  borderRadius: 1.5,
                  border: "1px solid",
                  borderColor: "divider",
                  bgcolor: (theme) => (theme.palette.mode === "dark" ? "background.default" : "grey.50"),
                  overflow: "hidden",
                }}
              >
                <Box
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 1.5,
                    px: 2,
                    py: 1.25,
                    borderBottom: "1px solid",
                    borderColor: "divider",
                    bgcolor: "background.paper",
                  }}
                >
                  <Box
                    sx={{
                      width: 36,
                      height: 36,
                      borderRadius: 1,
                      display: "grid",
                      placeItems: "center",
                      bgcolor: (theme) => (theme.palette.mode === "dark" ? "action.selected" : "grey.100"),
                      color: "text.secondary",
                    }}
                  >
                    <SectionHeaderIcon label={sec.section_label} />
                  </Box>
                  <Box>
                    <Typography variant="overline" color="text.secondary" sx={{ letterSpacing: 1 }}>
                      {t("permissions.tabFunctionLevel")}
                    </Typography>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
                      {sec.section_label}
                    </Typography>
                  </Box>
                </Box>
                <Box sx={{ p: 2, pt: 1.5 }}>
                  <CrudTable
                    resources={sec.resources || []}
                    t={t}
                    selected={selected}
                    setSelected={setSelected}
                    readOnly={readOnly}
                  />
                </Box>
              </Box>
            ))}
          </Stack>
        </Paper>
      ))}
    </Stack>
  );
}

/**
 * Route → tab/function → CRUD matrix for role permission editing.
 * layoutVariant "flatFunctionality": three-level UI — module → tab/function → CRUD (uses API hierarchy or synthesizes from permissions[]).
 */
export default function PermissionMatrixHierarchy({
  t,
  hierarchy,
  groupedFlat,
  flatPermissions,
  selected,
  setSelected,
  readOnly = false,
  layoutVariant = "routes",
}) {
  if (layoutVariant === "flatFunctionality") {
    let routes = [];
    if (hierarchy && hierarchy.length > 0) {
      routes = normalizeHierarchyRoutes(hierarchy);
    } else if (flatPermissions && flatPermissions.length > 0) {
      routes = buildSyntheticModuleHierarchy(flatPermissions);
    } else if (groupedFlat && Object.keys(groupedFlat).length > 0) {
      routes = buildSyntheticModuleHierarchy(groupedFlatToPermissions(groupedFlat));
    }
    if (routes.length > 0) {
      return renderModuleTabCrudHierarchy(routes, t, selected, setSelected, readOnly);
    }
  }

  if (hierarchy && hierarchy.length > 0) {
    return (
      <Stack spacing={1.5}>
        {hierarchy.map((route) => (
          <Accordion key={route.route_key} defaultExpanded disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1, flex: 1, flexWrap: "wrap" }}>
                <Box>
                  <Typography component="span" variant="overline" color="text.secondary" sx={{ display: "block" }}>
                    {t("permissions.moduleLevel")}
                  </Typography>
                  <Typography component="span" fontWeight={700} sx={{ fontSize: "1.05rem" }}>
                    {route.route_label}
                  </Typography>
                </Box>
                <Tooltip title={`${t("permissions.routeKeyHint")}: ${route.route_key}`}>
                  <HelpOutlineIcon sx={{ fontSize: 18, color: "text.disabled", mt: 0.5 }} />
                </Tooltip>
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ pt: 0 }}>
              {(route.sections || []).map((sec) => (
                <Box key={`${route.route_key}-${sec.section_key}`} sx={{ mb: 2.5 }}>
                  <Typography variant="overline" color="primary" sx={{ display: "block", letterSpacing: 0.5 }}>
                    {t("permissions.tabFunctionLevel")}
                  </Typography>
                  <Typography variant="subtitle1" sx={{ mb: 1.25, fontWeight: 600 }}>
                    {sec.section_label}
                  </Typography>
                  {(sec.resources || []).map((res) => (
                    <Box key={`${res.resource_key}-${sec.section_key}`} sx={{ mb: 2 }}>
                      {res.resource_label || res.resource_key ? (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>
                          {res.resource_label || res.resource_key}
                        </Typography>
                      ) : null}
                      <Table size="small" sx={{ mb: 0 }}>
                        <TableHead>
                          <TableRow>
                            <TableCell width={110}>{t("permissions.colActionCrud")}</TableCell>
                            <TableCell>{t("permissions.colPermission")}</TableCell>
                            <TableCell>{t("permissions.colDescription")}</TableCell>
                            <TableCell align="right" width={90}>
                              {t("permissions.colAllow")}
                            </TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(res.actions || []).map((a) => (
                            <TableRow key={a.perm_key}>
                              <TableCell sx={{ textTransform: "lowercase", fontWeight: 500 }}>{actionLabel(a)}</TableCell>
                              <TableCell>
                                <PermKeyPill permKey={a.perm_key} />
                              </TableCell>
                              <TableCell>
                                <Typography variant="body2" color="text.secondary">
                                  {rowDescription(a)}
                                </Typography>
                              </TableCell>
                              <TableCell align="right">
                                <Checkbox
                                  size="small"
                                  checked={!!selected[a.perm_key]}
                                  disabled={readOnly}
                                  onChange={(e) =>
                                    setSelected((prev) => ({
                                      ...prev,
                                      [a.perm_key]: e.target.checked,
                                    }))
                                  }
                                />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </Box>
                  ))}
                </Box>
              ))}
            </AccordionDetails>
          </Accordion>
        ))}
      </Stack>
    );
  }

  return Object.keys(groupedFlat || {})
    .sort()
    .map((grp) => (
      <Box key={grp} sx={{ mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 0.5, textTransform: "capitalize" }}>
          {grp}
        </Typography>
        <Stack spacing={0.5}>
          {(groupedFlat[grp] || []).map((p) => (
            <FormControlLabel
              key={p.perm_key}
              control={
                <Checkbox
                  checked={!!selected[p.perm_key]}
                  disabled={readOnly}
                  onChange={(e) =>
                    setSelected((prev) => ({ ...prev, [p.perm_key]: e.target.checked }))
                  }
                />
              }
              label={
                <span>
                  <strong>{displayPermissionKey(p.perm_key)}</strong>
                  {p.description ? (
                    <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      {PERMISSION_DESCRIPTION_OVERRIDES[p.perm_key] || p.description}
                    </Typography>
                  ) : null}
                </span>
              }
            />
          ))}
        </Stack>
      </Box>
    ));
}
