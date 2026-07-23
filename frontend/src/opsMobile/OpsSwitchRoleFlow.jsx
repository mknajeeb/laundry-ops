import { Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import OpsChoiceCard from "./OpsChoiceCard";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import {
  resolveCategoryId,
  resolveRoleId,
  resolveRoleName,
  rolesForCategory,
} from "./switchRoleFlowHelpers";

/**
 * Shared full-screen Switch Role UI (hub + /attendance/role).
 */
export default function OpsSwitchRoleFlow({
  employeeName = "",
  selectionTree = [],
  categoryId = null,
  onSelectCategory,
  currentCategoryId = null,
  currentRoleId = null,
  pending = false,
  pendingRoleId = null,
  error = "",
  onClearError,
  onSelectRole,
  onRetry,
  onBack,
  onLock,
  unavailable = false,
  unavailableMessage = "Role change isn’t available right now.",
  success = false,
  successLabel = "",
}) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  const multiCategory = tree.length > 1;
  const roles = rolesForCategory(tree, categoryId);
  const selectedCat = tree.find((c) => Number(resolveCategoryId(c)) === Number(categoryId));

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
          onBack={onBack}
          backLabel="PIN"
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

            {multiCategory ? (
              <Stack spacing={1}>
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
                  {tree.map((cat) => {
                    const cid = resolveCategoryId(cat);
                    const selected = Number(cid) === Number(categoryId);
                    return (
                      <Button
                        key={cid}
                        disabled={pending}
                        onClick={() => onSelectCategory?.(cid)}
                        sx={{
                          textTransform: "none",
                          fontWeight: 800,
                          minHeight: OPS_MOBILE.touchMin,
                          px: 2,
                          borderRadius: 999,
                          bgcolor: selected
                            ? alpha(OPS_MOBILE.cobalt, 0.16)
                            : alpha(OPS_MOBILE.navy, 0.05),
                          color: OPS_MOBILE.navy,
                          border: selected
                            ? `2px solid ${OPS_MOBILE.cobalt}`
                            : "2px solid transparent",
                        }}
                      >
                        {cat.name}
                      </Button>
                    );
                  })}
                </Box>
                {selectedCat?.name ? (
                  <Typography sx={{ fontWeight: 800, fontSize: "0.95rem", color: OPS_MOBILE.muted }}>
                    {selectedCat.name}
                  </Typography>
                ) : null}
              </Stack>
            ) : null}

            <Stack spacing={1.25} sx={{ width: "100%" }}>
              {roles.map((role) => {
                const rid = resolveRoleId(role);
                const name = resolveRoleName(role);
                const isCurrent =
                  Number(categoryId) === Number(currentCategoryId) &&
                  Number(rid) === Number(currentRoleId);
                const isBusy = pending && Number(pendingRoleId) === Number(rid);
                return (
                  <OpsChoiceCard
                    key={`${categoryId}-${rid}`}
                    title={name || "Role"}
                    current={isCurrent}
                    busy={isBusy}
                    disabled={pending && !isBusy}
                    onClick={() => {
                      if (isCurrent || pending) return;
                      onSelectRole?.(role);
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
              {!roles.length && categoryId != null ? (
                <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, textAlign: "center" }}>
                  Role change isn’t available right now.
                </Typography>
              ) : null}
              {pending && pendingRoleId == null ? (
                <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
                  <CircularProgress size={28} />
                </Box>
              ) : null}
            </Stack>
          </>
        ) : null}
      </Box>
    </OpsMobileShell>
  );
}
