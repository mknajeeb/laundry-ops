import { Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import OpsChoiceCard from "./OpsChoiceCard";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import {
  flattenRoleCombos,
  groupCombosByBucket,
  roleHelperText,
} from "./switchRoleFlowHelpers";

/**
 * Shared full-screen Switch Role UI — one screen, one tap per category×role combo.
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
}) {
  const combos = flattenRoleCombos(selectionTree);
  const groups = groupCombosByBucket(combos);

  return (
    <OpsMobileShell contentSx={{ gap: 1.5 }}>
      <Box
        sx={{
          width: "100%",
          maxWidth: 390,
          mx: "auto",
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
          title="Change Role"
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

            {!combos.length ? (
              <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, textAlign: "center" }}>
                Role change isn’t available right now.
              </Typography>
            ) : (
              <Stack spacing={2} sx={{ width: "100%" }}>
                <Typography sx={{ fontWeight: 800, fontSize: "0.95rem", color: OPS_MOBILE.muted }}>
                  Tap your role — one tap switches immediately
                </Typography>
                {groups.map(({ bucket, combos: bucketCombos }) => (
                  <Stack key={bucket} spacing={1}>
                    <Typography
                      sx={{
                        fontWeight: 900,
                        fontSize: "0.82rem",
                        letterSpacing: 0.6,
                        textTransform: "uppercase",
                        color: alpha(OPS_MOBILE.navy, 0.55),
                      }}
                    >
                      {bucket}
                    </Typography>
                    {bucketCombos.map((combo) => {
                      const isCurrent =
                        Number(combo.categoryId) === Number(currentCategoryId) &&
                        Number(combo.roleId) === Number(currentRoleId);
                      const isBusy =
                        pending &&
                        Number(pendingCategoryId) === Number(combo.categoryId) &&
                        Number(pendingRoleId) === Number(combo.roleId);
                      const helper = roleHelperText(combo.role);
                      return (
                        <OpsChoiceCard
                          key={`${combo.categoryId}-${combo.roleId}`}
                          title={combo.roleLabel}
                          subtitle={
                            bucket === "Non-Rinse" && combo.categoryName
                              ? `${combo.categoryName}${helper ? ` · ${helper}` : ""}`
                              : helper
                          }
                          current={isCurrent}
                          busy={isBusy}
                          disabled={pending && !isBusy}
                          onClick={() => {
                            if (isCurrent || pending) return;
                            onSelectCombo?.(combo);
                          }}
                          aria-label={isCurrent ? `${combo.comboLabel}, current` : combo.comboLabel}
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
                  </Stack>
                ))}
                {pending && pendingCategoryId == null ? (
                  <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
                    <CircularProgress size={28} />
                  </Box>
                ) : null}
              </Stack>
            )}
          </>
        ) : null}
      </Box>
    </OpsMobileShell>
  );
}
