import { ArrowBack } from "@mui/icons-material";
import { Box, Button, IconButton, Stack, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";

/**
 * Standard tenant sub-screen header: back (left), main menu (center), actions (right).
 * Optional title + date row below the control bar.
 */
export default function StandardScreenHeader({
  title,
  dateLabel,
  right,
  onBack,
  homePath = "/",
  dense = false,
}) {
  const navigate = useNavigate();
  const handleBack = onBack ?? (() => navigate(-1));

  return (
    <Box sx={{ mb: dense ? 0.75 : 1.2 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "48px 1fr auto", sm: "52px 1fr auto" },
          alignItems: "center",
          gap: { xs: 0.25, sm: 0.75 },
          minHeight: 48,
        }}
      >
        <IconButton
          onClick={handleBack}
          aria-label="Back"
          size="large"
          sx={{
            justifySelf: "start",
            bgcolor: "#f1f5f9",
            "&:hover": { bgcolor: "#e2e8f0" },
            width: 48,
            height: 48,
          }}
        >
          <ArrowBack />
        </IconButton>
        <Button
          variant="text"
          onClick={() => navigate(homePath)}
          sx={{
            justifySelf: "center",
            textTransform: "none",
            fontWeight: 600,
            color: "text.primary",
            px: { xs: 0.5, sm: 1.5 },
            py: 1,
            borderRadius: 999,
            maxWidth: "100%",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            fontSize: { xs: "0.8rem", sm: "0.95rem" },
          }}
        >
          Return to Main Menu
        </Button>
        <Box sx={{ justifySelf: "end", display: "flex", alignItems: "center", gap: 0.75, flexWrap: "nowrap" }}>
          {right}
        </Box>
      </Box>
      {title ? (
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="baseline"
          flexWrap="wrap"
          gap={1}
          sx={{ mt: 1 }}
        >
          <Typography sx={{ fontSize: { xs: 26, sm: 30 }, fontWeight: 500 }}>{title}</Typography>
          {dateLabel ? (
            <Typography sx={{ color: "text.secondary", fontSize: 15, fontWeight: 400 }}>{dateLabel}</Typography>
          ) : null}
        </Stack>
      ) : null}
    </Box>
  );
}
