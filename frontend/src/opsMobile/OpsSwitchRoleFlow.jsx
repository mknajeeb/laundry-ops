import { useState } from "react";
import { Box, Button, CircularProgress, Collapse, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import CheckIcon from "@mui/icons-material/Check";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import {
  currentRoleCaption,
  flattenRoleCombos,
  groupCombosByPrimaryRole,
  isCurrentRoleAssignment,
  resolvePrimaryRoleTap,
} from "./switchRoleFlowHelpers";

/**
 * Role-first Change Role UI: Wash-Dry / Sort / Fold, then work types in place.
 */
export default function OpsSwitchRoleFlow({
  employeeName = "",
  selectionTree = [],
  currentCategoryId = null,
  currentRoleId = null,
  pending = false,
  pendingCategoryId = null,
  pendingRoleId = null,
  error = "",
  onClearError,
  onRetry,
  onSelectCombo,
  onBack,
  onLock,
  unavailable = false,
  unavailableMessage = "Role change isn’t available right now.",
  success = false,
  successLabel = "",
  defaultExpandedRole = null,
}) {
  const combos = flattenRoleCombos(selectionTree);
  const roleGroups = groupCombosByPrimaryRole(combos);
  const [expandedRole, setExpandedRole] = useState(defaultExpandedRole);
  const currentCombo = combos.find((c) =>
    isCurrentRoleAssignment(c.categoryId, c.roleId, currentCategoryId, currentRoleId),
  );

  const tapRole = (roleLabel, workTypes) => {
    if (pending) return;
    const result = resolvePrimaryRoleTap({
      workTypes,
      expandedRole,
      roleLabel,
      currentCategoryId,
      currentRoleId,
    });
    if (result.action === "switch" && result.combo) {
      onSelectCombo?.(result.combo);
      return;
    }
    if (result.action === "expand") setExpandedRole(roleLabel);
    if (result.action === "collapse") setExpandedRole(null);
  };

  const tapWorkType = (combo) => {
    if (pending) return;
    if (isCurrentRoleAssignment(combo.categoryId, combo.roleId, currentCategoryId, currentRoleId)) {
      return;
    }
    onSelectCombo?.(combo);
  };

  return (
    <OpsMobileShell contentSx={{ gap: 1 }}>
      <Box
        sx={{
          width: "100%",
          maxWidth: 390,
          mx: "auto",
          px: 0.25,
          display: "flex",
          flexDirection: "column",
          gap: 1,
        }}
      >
        <OpsTopBar
          title="Change Role"
          identity=""
          onBack={onBack}
          backLabel="PIN"
          onLock={onLock}
          lockLabel="Lock"
          sticky
        />

        {success ? (
          <Stack spacing={1.5} alignItems="center" sx={{ py: 4 }}>
            <Typography sx={{ fontWeight: 900, fontSize: "1.35rem", color: OPS_MOBILE.navy, textAlign: "center" }}>
              {successLabel || "Role updated"}
            </Typography>
          </Stack>
        ) : null}

        {!success && unavailable ? (
          <Stack spacing={2} sx={{ py: 2 }}>
            <Typography sx={{ fontWeight: 800, fontSize: "1.1rem", color: OPS_MOBILE.navy, textAlign: "center" }}>
              {unavailableMessage}
            </Typography>
            <OpsLockButton onClick={onLock} fullWidth />
          </Stack>
        ) : null}

        {!success && !unavailable ? (
          <>
            {error ? (
              <Box
                sx={{
                  bgcolor: alpha(OPS_MOBILE.danger, 0.08),
                  borderRadius: 1.5,
                  px: 1.25,
                  py: 1,
                }}
              >
                <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.danger, mb: 0.25, fontSize: 14 }}>
                  {error}
                </Typography>
                <Button
                  onClick={() => {
                    onClearError?.();
                    onRetry?.();
                  }}
                  disabled={pending}
                  sx={{
                    textTransform: "none",
                    fontWeight: 800,
                    minHeight: 44,
                    color: OPS_MOBILE.navy,
                  }}
                >
                  Try again
                </Button>
              </Box>
            ) : null}

            {!combos.length ? (
              <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, textAlign: "center" }}>
                Role change isn’t available right now.
              </Typography>
            ) : (
              <Box
                sx={{
                  width: "100%",
                  bgcolor: alpha("#fff", 0.96),
                  borderRadius: 2,
                  overflow: "hidden",
                  border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
                }}
              >
                {roleGroups.map((group, index) => {
                  const isExpanded = expandedRole === group.roleLabel;
                  const isCurrentRole = currentCombo?.roleLabel === group.roleLabel;
                  const canExpand = group.workTypes.length > 1;
                  const pendingOnRole = pending && group.workTypes.some(
                    (wt) =>
                      Number(wt.combo.categoryId) === Number(pendingCategoryId) &&
                      Number(wt.combo.roleId) === Number(pendingRoleId),
                  );
                  return (
                    <Box
                      key={group.roleLabel}
                      sx={{
                        borderTop: index === 0 ? 0 : `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
                      }}
                    >
                      <Button
                        fullWidth
                        disabled={pending && !pendingOnRole}
                        onClick={() => tapRole(group.roleLabel, group.workTypes)}
                        aria-expanded={canExpand ? isExpanded : undefined}
                        aria-label={
                          isCurrentRole
                            ? `${group.roleLabel}, ${currentRoleCaption(currentCombo)}`
                            : group.roleLabel
                        }
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          minHeight: OPS_MOBILE.touchMin,
                          px: 1.75,
                          py: 1,
                          borderRadius: 0,
                          textTransform: "none",
                          textAlign: "left",
                          color: OPS_MOBILE.navy,
                          bgcolor: isCurrentRole ? alpha(OPS_MOBILE.success, 0.07) : "transparent",
                          "&:hover": {
                            bgcolor: isCurrentRole
                              ? alpha(OPS_MOBILE.success, 0.11)
                              : alpha(OPS_MOBILE.navy, 0.04),
                          },
                          "&.Mui-disabled": { opacity: pendingOnRole ? 1 : 0.45 },
                        }}
                      >
                        <Box sx={{ minWidth: 0, pr: 1 }}>
                          <Typography sx={{ fontWeight: 800, fontSize: "1.12rem", letterSpacing: "-0.02em", lineHeight: 1.15 }}>
                            {group.roleLabel}
                          </Typography>
                          {isCurrentRole ? (
                            <Typography sx={{ fontWeight: 650, fontSize: "0.78rem", color: OPS_MOBILE.success, mt: 0.2 }}>
                              {currentRoleCaption(currentCombo)}
                            </Typography>
                          ) : null}
                        </Box>
                        <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, flexShrink: 0 }}>
                          {pendingOnRole ? <CircularProgress size={18} /> : null}
                          {canExpand ? (
                            <KeyboardArrowDownIcon
                              sx={{
                                fontSize: 22,
                                color: OPS_MOBILE.muted,
                                transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                                transition: "transform 180ms ease",
                              }}
                            />
                          ) : null}
                        </Box>
                      </Button>
                      <Collapse in={isExpanded} timeout={180} unmountOnExit>
                        <Stack sx={{ pb: 0.75, px: 0.5 }}>
                          {group.workTypes.map((wt) => {
                            const isCurrent = isCurrentRoleAssignment(
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
                                  minHeight: 48,
                                  px: 2,
                                  py: 0.75,
                                  pl: 2.5,
                                  borderRadius: 1.25,
                                  textTransform: "none",
                                  color: OPS_MOBILE.navy,
                                  bgcolor: isCurrent ? alpha(OPS_MOBILE.success, 0.1) : "transparent",
                                  fontWeight: isCurrent ? 800 : 650,
                                  fontSize: "0.95rem",
                                  "&:hover": {
                                    bgcolor: isCurrent
                                      ? alpha(OPS_MOBILE.success, 0.14)
                                      : alpha(OPS_MOBILE.navy, 0.04),
                                  },
                                }}
                              >
                                <Box component="span">{wt.label}</Box>
                                {isBusy ? (
                                  <CircularProgress size={16} />
                                ) : isCurrent ? (
                                  <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, color: OPS_MOBILE.success }}>
                                    <CheckIcon sx={{ fontSize: 18 }} />
                                    <Typography sx={{ fontWeight: 800, fontSize: "0.72rem", letterSpacing: 0.2 }}>
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
            )}
          </>
        ) : null}
      </Box>
    </OpsMobileShell>
  );
}
