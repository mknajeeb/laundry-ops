import { Alert } from "@mui/material";

/**
 * @param {{ message: string | null }} props
 */
function TaOperationalBanner({ message }) {
  if (!message) return null;
  return (
    <Alert severity="warning" sx={{ mb: 2 }}>
      {message}
    </Alert>
  );
}

export default TaOperationalBanner;
