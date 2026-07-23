import { Stack, Typography } from "@mui/material";
import OpsLockButton from "./OpsLockButton";
import { OPS_MOBILE } from "./tokens";

/** Empty launcher: no paragraphs — message + large Lock only. */
export default function OpsLauncherEmpty({ onLock, message = "No actions available" }) {
  return (
    <Stack spacing={2.5} alignItems="stretch" sx={{ width: "100%", py: 2 }}>
      <Typography
        sx={{
          fontWeight: 800,
          fontSize: "1.2rem",
          color: OPS_MOBILE.navy,
          textAlign: "center",
        }}
      >
        {message}
      </Typography>
      {onLock ? <OpsLockButton onClick={onLock} fullWidth label="Lock" /> : null}
    </Stack>
  );
}
