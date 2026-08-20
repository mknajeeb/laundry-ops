import { useState } from "react";
import { Box, Button, CircularProgress, Collapse, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import CheckIcon from "@mui/icons-material/Check";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import LocalLaundryServiceOutlinedIcon from "@mui/icons-material/LocalLaundryServiceOutlined";
import SortOutlinedIcon from "@mui/icons-material/SortOutlined";
import CheckroomOutlinedIcon from "@mui/icons-material/CheckroomOutlined";
import { OPS_MOBILE } from "./tokens";
import {
  currentRoleCaption,
  flattenRoleCombos,
  groupCombosByFamily,
  isCurrentRoleAssignment,
  resolvePrimaryRoleTap,
} from "./switchRoleFlowHelpers";

const ROLE_ICONS = {
  "Wash-Dry": LocalLaundryServiceOutlinedIcon,
  Sort: SortOutlinedIcon,
  Fold: CheckroomOutlinedIcon,
};

function expandKey(familyLabel, roleLabel) {
  return `${familyLabel}::${roleLabel}`;
}

/**
 * Shared family-first selector: Rinse / Non-Rinse → Wash-Dry / Sort / Fold.
 * Used by PIN Change Role, attendance clock-in, and break resume.
 * Presentation only — callers own punch/switch/resume semantics.
 */
export default function OpsRoleFirstSelector({
  selectionTree = [],
  currentCategoryId = null,
  currentRoleId = null,
  markCurrent = true,
  pending = false,
  pendingCategoryId = null,
  pendingRoleId = null,
  onSelectCombo,
  defaultExpandedRole = null,
  emptyMessage = "Role selection isn’t available right now.",
  singleWorkTypeHint = "Tap to select",
  multiWorkTypeHint = "Tap to choose work type",
}) {
  const combos = flattenRoleCombos(selectionTree);
  const families = groupCombosByFamily(combos, {
    currentCategoryId,
    currentRoleId,
  });
  const [expandedKey, setExpandedKey] = useState(defaultExpandedRole);
  const currentCombo =
    markCurrent &&
    combos.find((c) =>
      isCurrentRoleAssignment(c.categoryId, c.roleId, currentCategoryId, currentRoleId),
    );

  const tapRole = (familyLabel, roleLabel, workTypes) => {
    if (pending) return;
    const key = expandKey(familyLabel, roleLabel);
    const result = resolvePrimaryRoleTap({
      workTypes,
      expandedRole: expandedKey === key ? roleLabel : null,
      roleLabel,
      currentCategoryId: markCurrent ? currentCategoryId : null,
      currentRoleId: markCurrent ? currentRoleId : null,
    });
    if (result.action === "switch" && result.combo) {
      onSelectCombo?.(result.combo);
      return;
    }
    if (result.action === "expand") setExpandedKey(key);
    if (result.action === "collapse") setExpandedKey(null);
  };

  const tapWorkType = (combo) => {
    if (pending) return;
    if (
      markCurrent &&
      isCurrentRoleAssignment(combo.categoryId, combo.roleId, currentCategoryId, currentRoleId)
    ) {
      return;
    }
    onSelectCombo?.(combo);
  };

  if (!combos.length) {
    return (
      <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, textAlign: "center" }}>
        {emptyMessage}
      </Typography>
    );
  }

  return (
    <Stack
      spacing={{ xs: 3.5, sm: 4 }}
      sx={{
        width: "100%",
        maxWidth: { xs: 440, sm: 520, md: 880 },
        mx: "auto",
      }}
    >
      {families.map((family) => (
        <Box key={family.familyLabel} sx={{ width: "100%" }}>
          <Typography
            component="h2"
            sx={{
              fontWeight: 900,
              fontSize: { xs: "0.78rem", sm: "0.82rem" },
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: OPS_MOBILE.blue,
              mb: { xs: 1.5, sm: 1.75 },
              px: 0.25,
            }}
          >
            {family.familyLabel}
          </Typography>

          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "1fr",
                sm: "1fr",
                md:
                  family.roleGroups.length <= 1
                    ? "minmax(0, 440px)"
                    : family.roleGroups.length === 2
                      ? "1fr 1fr"
                      : "1fr 1fr 1fr",
              },
              justifyContent: "center",
              gap: { xs: 3, sm: 3.25, md: 2.75 },
              alignItems: "start",
            }}
          >
            {family.roleGroups.map((group) => {
              const key = expandKey(family.familyLabel, group.roleLabel);
              const isExpanded = expandedKey === key;
              const isCurrentRole = Boolean(
                currentCombo &&
                  currentCombo.roleLabel === group.roleLabel &&
                  (family.familyLabel === "Non-Rinse"
                    ? currentCombo.bucket === "Non-Rinse"
                    : currentCombo.bucket !== "Non-Rinse"),
              );
              const canExpand = group.workTypes.length > 1;
              const pendingOnRole =
                pending &&
                group.workTypes.some(
                  (wt) =>
                    Number(wt.combo.categoryId) === Number(pendingCategoryId) &&
                    Number(wt.combo.roleId) === Number(pendingRoleId),
                );
              const RoleIcon = ROLE_ICONS[group.roleLabel] || LocalLaundryServiceOutlinedIcon;

              return (
                <Box key={key} sx={{ minWidth: 0 }}>
                  <Button
                    fullWidth
                    disabled={pending && !pendingOnRole}
                    onClick={() => tapRole(family.familyLabel, group.roleLabel, group.workTypes)}
                    aria-expanded={canExpand ? isExpanded : undefined}
                    aria-label={
                      isCurrentRole
                        ? `${family.familyLabel} ${group.roleLabel}, ${currentRoleCaption(currentCombo)}`
                        : `${family.familyLabel} ${group.roleLabel}`
                    }
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 1.5,
                      minHeight: { xs: 96, sm: 104, md: 108 },
                      px: { xs: 2, sm: 2.5 },
                      py: { xs: 2, sm: 2.25 },
                      borderRadius: `${OPS_MOBILE.radius.card}px`,
                      textTransform: "none",
                      textAlign: "left",
                      color: OPS_MOBILE.navy,
                      bgcolor: isCurrentRole
                        ? alpha(OPS_MOBILE.success, 0.12)
                        : alpha("#fff", 0.96),
                      border: `2px solid ${
                        isCurrentRole
                          ? alpha(OPS_MOBILE.success, 0.45)
                          : isExpanded
                            ? alpha(OPS_MOBILE.cobalt, 0.45)
                            : alpha(OPS_MOBILE.navy, 0.1)
                      }`,
                      boxShadow: isExpanded
                        ? `0 10px 28px -18px ${alpha(OPS_MOBILE.navy, 0.45)}`
                        : `0 8px 22px -18px ${alpha(OPS_MOBILE.navy, 0.35)}`,
                      "&:hover": {
                        bgcolor: isCurrentRole
                          ? alpha(OPS_MOBILE.success, 0.16)
                          : alpha("#fff", 1),
                        borderColor: isCurrentRole
                          ? alpha(OPS_MOBILE.success, 0.55)
                          : alpha(OPS_MOBILE.cobalt, 0.4),
                      },
                      "&.Mui-disabled": { opacity: pendingOnRole ? 1 : 0.45 },
                    }}
                  >
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, minWidth: 0 }}>
                      <Box
                        sx={{
                          width: { xs: 52, sm: 56 },
                          height: { xs: 52, sm: 56 },
                          borderRadius: 2,
                          flexShrink: 0,
                          display: "grid",
                          placeItems: "center",
                          bgcolor: isCurrentRole
                            ? alpha(OPS_MOBILE.success, 0.16)
                            : alpha(OPS_MOBILE.cobalt, 0.12),
                          color: isCurrentRole ? OPS_MOBILE.success : OPS_MOBILE.blue,
                        }}
                      >
                        <RoleIcon sx={{ fontSize: { xs: 30, sm: 32 } }} />
                      </Box>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography
                          sx={{
                            fontWeight: 900,
                            fontSize: { xs: "1.32rem", sm: "1.42rem" },
                            letterSpacing: "-0.03em",
                            lineHeight: 1.1,
                          }}
                        >
                          {group.roleLabel}
                        </Typography>
                        {isCurrentRole ? (
                          <Typography
                            sx={{
                              fontWeight: 700,
                              fontSize: { xs: "0.82rem", sm: "0.88rem" },
                              color: OPS_MOBILE.success,
                              mt: 0.4,
                            }}
                          >
                            {currentRoleCaption(currentCombo)}
                          </Typography>
                        ) : (
                          <Typography
                            sx={{
                              fontWeight: 650,
                              fontSize: { xs: "0.78rem", sm: "0.82rem" },
                              color: OPS_MOBILE.muted,
                              mt: 0.4,
                            }}
                          >
                            {canExpand ? multiWorkTypeHint : singleWorkTypeHint}
                          </Typography>
                        )}
                      </Box>
                    </Box>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, flexShrink: 0 }}>
                      {pendingOnRole ? <CircularProgress size={22} /> : null}
                      {canExpand ? (
                        <KeyboardArrowDownIcon
                          sx={{
                            fontSize: 28,
                            color: OPS_MOBILE.muted,
                            transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                            transition: "transform 180ms ease",
                          }}
                        />
                      ) : null}
                    </Box>
                  </Button>

                  <Collapse in={isExpanded} timeout={180} unmountOnExit>
                    <Stack
                      spacing={1.25}
                      sx={{
                        mt: 1.5,
                        p: { xs: 1.25, sm: 1.5 },
                        borderRadius: `${OPS_MOBILE.radius.card}px`,
                        bgcolor: alpha("#fff", 0.9),
                        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
                      }}
                    >
                      {group.workTypes.map((wt) => {
                        const isCurrent =
                          markCurrent &&
                          isCurrentRoleAssignment(
                            wt.combo.categoryId,
                            wt.combo.roleId,
                            currentCategoryId,
                            currentRoleId,
                          );
                        const isBusy =
                          pending &&
                          Number(pendingCategoryId) === Number(wt.combo.categoryId) &&
                          Number(pendingRoleId) === Number(wt.combo.roleId);
                        return (
                          <Button
                            key={wt.key}
                            fullWidth
                            disabled={pending && !isBusy}
                            onClick={() => tapWorkType(wt.combo)}
                            aria-label={isCurrent ? `${wt.label}, current` : wt.label}
                            sx={{
                              justifyContent: "space-between",
                              minHeight: { xs: 58, sm: 62 },
                              px: 2,
                              py: 1.25,
                              borderRadius: `${OPS_MOBILE.radius.button}px`,
                              textTransform: "none",
                              color: OPS_MOBILE.navy,
                              bgcolor: isCurrent
                                ? alpha(OPS_MOBILE.success, 0.12)
                                : alpha(OPS_MOBILE.mist, 0.7),
                              border: `1px solid ${
                                isCurrent
                                  ? alpha(OPS_MOBILE.success, 0.35)
                                  : alpha(OPS_MOBILE.navy, 0.08)
                              }`,
                              fontWeight: isCurrent ? 800 : 700,
                              fontSize: { xs: "1rem", sm: "1.05rem" },
                              "&:hover": {
                                bgcolor: isCurrent
                                  ? alpha(OPS_MOBILE.success, 0.16)
                                  : alpha(OPS_MOBILE.cobalt, 0.08),
                              },
                            }}
                          >
                            <Box component="span">{wt.label}</Box>
                            {isBusy ? (
                              <CircularProgress size={18} />
                            ) : isCurrent ? (
                              <Box
                                sx={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 0.5,
                                  color: OPS_MOBILE.success,
                                }}
                              >
                                <CheckIcon sx={{ fontSize: 20 }} />
                                <Typography
                                  sx={{
                                    fontWeight: 800,
                                    fontSize: "0.78rem",
                                    letterSpacing: 0.2,
                                  }}
                                >
                                  Current
                                </Typography>
                              </Box>
                            ) : null}
                          </Button>
                        );
                      })}
                    </Stack>
                  </Collapse>
                </Box>
              );
            })}
          </Box>
        </Box>
      ))}
    </Stack>
  );
}
