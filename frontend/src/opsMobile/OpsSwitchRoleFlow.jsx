import { useState } from "react";
import { Box, Button, CircularProgress, Collapse, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import CheckIcon from "@mui/icons-material/Check";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import LocalLaundryServiceOutlinedIcon from "@mui/icons-material/LocalLaundryServiceOutlined";
import SortOutlinedIcon from "@mui/icons-material/SortOutlined";
import CheckroomOutlinedIcon from "@mui/icons-material/CheckroomOutlined";
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

const ROLE_ICONS = {
  "Wash-Dry": LocalLaundryServiceOutlinedIcon,
  Sort: SortOutlinedIcon,
  Fold: CheckroomOutlinedIcon,
};

/**
 * Role-first Change Role UI: Wash-Dry / Sort / Fold, then work types in place.
 * Large primary touch cards; Non-Rinse is one employee-facing work type.
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
  const roleGroups = groupCombosByPrimaryRole(combos, {
    currentCategoryId,
    currentRoleId,
  });
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
    <OpsMobileShell
      maxWidth={880}
      sx={{
        px: { xs: 1.5, sm: 2.5, md: 3 },
        py: { xs: 1.5, sm: 2 },
      }}
      contentSx={{ gap: { xs: 1.5, sm: 2 } }}
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
          <Typography
            sx={{
              fontWeight: 900,
              fontSize: { xs: "1.35rem", sm: "1.5rem" },
              color: OPS_MOBILE.navy,
              textAlign: "center",
            }}
          >
            {successLabel || "Role updated"}
          </Typography>
        </Stack>
      ) : null}

      {!success && unavailable ? (
        <Stack spacing={2} sx={{ py: 2, maxWidth: 420, mx: "auto", width: "100%" }}>
          <Typography
            sx={{ fontWeight: 800, fontSize: "1.1rem", color: OPS_MOBILE.navy, textAlign: "center" }}
          >
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
                borderRadius: `${OPS_MOBILE.radius.card}px`,
                px: 1.5,
                py: 1.25,
                maxWidth: { xs: "100%", md: 560 },
                mx: "auto",
                width: "100%",
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
                  minHeight: 48,
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
                maxWidth: { xs: 440, sm: 560, md: 720 },
                mx: "auto",
                display: "grid",
                gridTemplateColumns: {
                  xs: "1fr",
                  md:
                    roleGroups.length <= 1
                      ? "minmax(0, 420px)"
                      : roleGroups.length === 2
                        ? "1fr 1fr"
                        : "1fr 1fr 1fr",
                },
                justifyContent: "center",
                gap: { xs: 1.75, sm: 2, md: 2.25 },
                alignItems: "start",
              }}
            >
              {roleGroups.map((group) => {
                const isExpanded = expandedRole === group.roleLabel;
                const isCurrentRole = currentCombo?.roleLabel === group.roleLabel;
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
                  <Box key={group.roleLabel} sx={{ minWidth: 0 }}>
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
                        gap: 1.5,
                        minHeight: { xs: 88, sm: 96, md: 100 },
                        px: { xs: 2, sm: 2.25 },
                        py: { xs: 1.75, sm: 2 },
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
                            width: { xs: 48, sm: 52 },
                            height: { xs: 48, sm: 52 },
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
                          <RoleIcon sx={{ fontSize: { xs: 28, sm: 30 } }} />
                        </Box>
                        <Box sx={{ minWidth: 0 }}>
                          <Typography
                            sx={{
                              fontWeight: 900,
                              fontSize: { xs: "1.28rem", sm: "1.38rem" },
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
                                mt: 0.35,
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
                                mt: 0.35,
                              }}
                            >
                              {canExpand ? "Tap to choose work type" : "Tap to switch"}
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
                        spacing={1}
                        sx={{
                          mt: 1.25,
                          p: { xs: 1, sm: 1.25 },
                          borderRadius: `${OPS_MOBILE.radius.card}px`,
                          bgcolor: alpha("#fff", 0.9),
                          border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
                        }}
                      >
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
                                minHeight: { xs: 56, sm: 60 },
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
                                    sx={{ fontWeight: 800, fontSize: "0.78rem", letterSpacing: 0.2 }}
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
          )}
        </>
      ) : null}
    </OpsMobileShell>
  );
}
