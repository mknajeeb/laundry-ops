import { Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import OpsChoiceCard from "./OpsChoiceCard";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import {
  categoriesForRole,
  displayRoleLabel,
  resolveCategoryId,
  resolveCategoryName,
  resolveRoleId,
  roleHelperText,
  uniqueRolesFromTree,
} from "./switchRoleFlowHelpers";

/**
 * Shared full-screen Switch Role UI (hub + /attendance/role).
 * Step 1 — Role · Step 2 — Category · then confirm (API) / return to PIN.
 */
export default function OpsSwitchRoleFlow({
  employeeName = "",
  selectionTree = [],
  step = "role", // "role" | "category"
  roleId = null,
  onSelectRole,
  onSelectCategory,
  onBackToRoles,
  currentCategoryId = null,
  currentRoleId = null,
  pending = false,
  pendingCategoryId = null,
  error = "",
  onClearError,
  onRetry,
  onBack,
  onLock,
  unavailable = false,
  unavailableMessage = "Role change isn’t available right now.",
  success = false,
  successLabel = "",
}) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  const roles = uniqueRolesFromTree(tree);
  const categories = categoriesForRole(tree, roleId);
  const showRoleStep = !success && !unavailable && step !== "category";
  const showCategoryStep = !success && !unavailable && step === "category";

  return (
    <OpsMobileShell contentSx={{ gap: 1.5 }}>
      <Box
        sx={{
          width: "100%",
          borderRadius: `${OPS_MOBILE.radius.card}px`,
          bgcolor: alpha("#fff", 0.96),
          boxShadow: `0 8px 28px -16px ${alpha(OPS_MOBILE.navy, 0.35)}`,
          p: { xs: 1.75, sm: 2.25 },
          display: "flex",
          flexDirection: "column",
          gap: 1.75,
        }}
      >
        <OpsTopBar
          title="Role"
          identity={employeeName || ""}
          onBack={
            showCategoryStep && roles.length > 1
              ? () => onBackToRoles?.()
              : onBack
          }
          backLabel={showCategoryStep && roles.length > 1 ? "Role" : "PIN"}
          onLock={onLock}
          lockLabel="Lock"
          sticky
        />

        {success ? (
          <Stack spacing={1.5} alignItems="center" sx={{ py: 4 }}>
            <Typography sx={{ fontWeight: 900, fontSize: "1.5rem", color: OPS_MOBILE.navy, textAlign: "center" }}>
              {successLabel || "Role updated"}
            </Typography>
          </Stack>
        ) : null}

        {!success && unavailable ? (
          <Stack spacing={2.5} sx={{ py: 2 }}>
            <Typography
              sx={{
                fontWeight: 800,
                fontSize: "1.15rem",
                color: OPS_MOBILE.navy,
                textAlign: "center",
              }}
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
                  borderRadius: 2,
                  px: 1.5,
                  py: 1.25,
                }}
              >
                <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.danger, mb: 0.5 }}>
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
                    minHeight: OPS_MOBILE.touchMin,
                    color: OPS_MOBILE.navy,
                  }}
                >
                  Try again
                </Button>
              </Box>
            ) : null}

            {showRoleStep ? (
              <Stack spacing={1.25} sx={{ width: "100%" }}>
                <Typography sx={{ fontWeight: 800, fontSize: "0.95rem", color: OPS_MOBILE.muted }}>
                  Select role
                </Typography>
                {roles.map((role) => {
                  const rid = resolveRoleId(role);
                  const label = displayRoleLabel(role);
                  const helper = roleHelperText(role);
                  const isCurrent = Number(rid) === Number(currentRoleId) && currentRoleId != null;
                  return (
                    <OpsChoiceCard
                      key={`role-${rid}`}
                      title={label || "Role"}
                      subtitle={helper}
                      current={isCurrent}
                      busy={false}
                      disabled={pending}
                      onClick={() => {
                        if (pending) return;
                        onSelectRole?.(role);
                      }}
                      aria-label={isCurrent ? `${label}, current` : label}
                      sx={{
                        opacity: pending ? 0.55 : 1,
                        ...(isCurrent
                          ? {
                              bgcolor: alpha(OPS_MOBILE.success, 0.1),
                              border: `2px solid ${alpha(OPS_MOBILE.success, 0.45)}`,
                            }
                          : null),
                      }}
                    />
                  );
                })}
                {!roles.length ? (
                  <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, textAlign: "center" }}>
                    Role change isn’t available right now.
                  </Typography>
                ) : null}
              </Stack>
            ) : null}

            {showCategoryStep ? (
              <Stack spacing={1.25} sx={{ width: "100%" }}>
                <Typography sx={{ fontWeight: 800, fontSize: "0.95rem", color: OPS_MOBILE.muted }}>
                  Select category
                </Typography>
                {categories.map((cat) => {
                  const cid = resolveCategoryId(cat);
                  const name = resolveCategoryName(cat);
                  const isCurrent =
                    Number(cid) === Number(currentCategoryId) &&
                    Number(roleId) === Number(currentRoleId);
                  const isBusy = pending && Number(pendingCategoryId) === Number(cid);
                  return (
                    <OpsChoiceCard
                      key={`cat-${cid}`}
                      title={name || "Category"}
                      current={isCurrent}
                      busy={isBusy}
                      disabled={pending && !isBusy}
                      onClick={() => {
                        if (isCurrent || pending) return;
                        onSelectCategory?.(cat);
                      }}
                      aria-label={isCurrent ? `${name}, current` : name}
                      sx={{
                        opacity: pending && !isBusy ? 0.55 : 1,
                        cursor: isCurrent ? "default" : "pointer",
                        ...(isCurrent
                          ? {
                              bgcolor: alpha(OPS_MOBILE.success, 0.1),
                              border: `2px solid ${alpha(OPS_MOBILE.success, 0.45)}`,
                            }
                          : null),
                      }}
                    />
                  );
                })}
                {!categories.length && roleId != null ? (
                  <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, textAlign: "center" }}>
                    Role change isn’t available right now.
                  </Typography>
                ) : null}
                {pending && pendingCategoryId == null ? (
                  <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
                    <CircularProgress size={28} />
                  </Box>
                ) : null}
              </Stack>
            ) : null}
          </>
        ) : null}
      </Box>
    </OpsMobileShell>
  );
}
