import { Box, Button, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import { useI18n } from "../i18n/I18nContext";
import OpsLocaleToggle from "./OpsLocaleToggle";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsRoleFirstSelector from "./OpsRoleFirstSelector";
import OpsTopBar from "./OpsTopBar";
import { successAssignmentLabelFromBody } from "./mobileOpsCopy";
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
  onSuccessDone,
  unavailable = false,
  unavailableMessage = "",
  success = false,
  successLabel = "",
  successBody = null,
  defaultExpandedRole = null,
}) {
  void employeeName;
  const { t } = useI18n();
  const confirmationLabel =
    successAssignmentLabelFromBody(successBody, t) ||
    successLabel ||
    t("mobileOps.roleChanged");

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
        title={t("mobileOps.changeRole")}
        identity=""
        onBack={success ? null : onBack}
        backLabel={t("mobileOps.backPin")}
        onLock={success ? null : onLock}
        lockLabel={t("mobileOps.lock")}
        right={<OpsLocaleToggle />}
        sticky
      />

      {success ? (
        <Stack
          spacing={2.5}
          alignItems="center"
          sx={{
            py: { xs: 4, sm: 5 },
            px: 1,
            maxWidth: 480,
            mx: "auto",
            width: "100%",
          }}
        >
          <Box
            sx={{
              width: { xs: 72, sm: 80 },
              height: { xs: 72, sm: 80 },
              borderRadius: "50%",
              display: "grid",
              placeItems: "center",
              bgcolor: alpha(OPS_MOBILE.success, 0.14),
              color: OPS_MOBILE.success,
            }}
          >
            <CheckCircleOutlineIcon sx={{ fontSize: { xs: 44, sm: 48 } }} />
          </Box>
          <Typography
            sx={{
              fontWeight: 900,
              fontSize: { xs: "1.55rem", sm: "1.75rem" },
              color: OPS_MOBILE.navy,
              textAlign: "center",
              letterSpacing: "-0.03em",
            }}
          >
            {t("mobileOps.roleChanged")}
          </Typography>
          <Typography
            sx={{
              fontWeight: 800,
              fontSize: { xs: "1.15rem", sm: "1.25rem" },
              color: OPS_MOBILE.blue,
              textAlign: "center",
              lineHeight: 1.35,
              px: 1,
            }}
          >
            {confirmationLabel}
          </Typography>
          <Button
            fullWidth
            onClick={() => onSuccessDone?.()}
            sx={{
              mt: 1,
              minHeight: { xs: 56, sm: 58 },
              borderRadius: `${OPS_MOBILE.radius.button}px`,
              textTransform: "none",
              fontWeight: 900,
              fontSize: "1.05rem",
              color: "#fff",
              bgcolor: OPS_MOBILE.blue,
              "&:hover": { bgcolor: OPS_MOBILE.cobalt },
            }}
          >
            {t("mobileOps.done")}
          </Button>
        </Stack>
      ) : null}

      {!success && unavailable ? (
        <Stack spacing={2} sx={{ py: 2, maxWidth: 420, mx: "auto", width: "100%" }}>
          <Typography
            sx={{ fontWeight: 800, fontSize: "1.1rem", color: OPS_MOBILE.navy, textAlign: "center" }}
          >
            {unavailableMessage || t("mobileOps.roleUnavailable")}
          </Typography>
          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
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
                {t("mobileOps.tryAgain")}
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
            emptyMessage={t("mobileOps.roleUnavailable")}
            singleWorkTypeHint={t("mobileOps.tapToSwitch")}
            multiWorkTypeHint={t("mobileOps.tapToChooseWork")}
          />
        </>
      ) : null}
    </OpsMobileShell>
  );
}
