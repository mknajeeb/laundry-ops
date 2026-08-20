import { Box, Button, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsRoleFirstSelector from "./OpsRoleFirstSelector";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";

/**
 * PIN Change Role shell — shared OpsRoleFirstSelector + PIN chrome.
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
  void employeeName;

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

          <OpsRoleFirstSelector
            selectionTree={selectionTree}
            currentCategoryId={currentCategoryId}
            currentRoleId={currentRoleId}
            markCurrent
            pending={pending}
            pendingCategoryId={pendingCategoryId}
            pendingRoleId={pendingRoleId}
            onSelectCombo={onSelectCombo}
            defaultExpandedRole={defaultExpandedRole}
            emptyMessage="Role change isn’t available right now."
            singleWorkTypeHint="Tap to switch"
            multiWorkTypeHint="Tap to choose work type"
          />
        </>
      ) : null}
    </OpsMobileShell>
  );
}
