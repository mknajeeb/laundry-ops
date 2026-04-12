import { ArrowBack, HomeRounded } from "@mui/icons-material";
import { Box, IconButton, Stack, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";

/**
 * Ops sub-screen header: back + home (icons), centered title, trailing actions.
 * Optional date line below — keep copy minimal for floor use.
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
    <Box
      sx={{
        mb: dense ? 0.65 : 1,
        pb: dense ? 0.65 : 0.85,
        borderBottom: "1px solid rgba(148, 163, 184, 0.32)",
        background: "linear-gradient(105deg, rgba(255,255,255,0.97) 0%, rgba(241, 248, 255, 0.88) 55%, rgba(255, 250, 252, 0.92) 100%)",
        borderRadius: 2,
        px: { xs: 0.35, sm: 0.5 },
      }}
    >
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ minHeight: 50 }}>
        <Stack direction="row" spacing={0.35} alignItems="center" sx={{ flexShrink: 0 }}>
          <IconButton
            onClick={handleBack}
            aria-label="Back"
            size="large"
            sx={{
              bgcolor: "rgba(226, 232, 240, 0.95)",
              "&:hover": { bgcolor: "rgba(203, 213, 225, 0.95)" },
              width: 48,
              height: 48,
            }}
          >
            <ArrowBack />
          </IconButton>
          <IconButton
            onClick={() => navigate(homePath)}
            aria-label="Main menu"
            size="large"
            sx={{
              bgcolor: "rgba(219, 234, 254, 0.95)",
              color: "primary.main",
              "&:hover": { bgcolor: "rgba(191, 219, 254, 0.98)" },
              width: 48,
              height: 48,
            }}
          >
            <HomeRounded />
          </IconButton>
        </Stack>
        <Typography
          component="div"
          sx={{
            flex: 1,
            minWidth: 0,
            textAlign: "center",
            fontWeight: 700,
            fontSize: { xs: "1.12rem", sm: "1.28rem" },
            letterSpacing: 0.15,
            color: "#0f172a",
            lineHeight: 1.25,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            px: 0.5,
          }}
        >
          {title || "\u00a0"}
        </Typography>
        <Box sx={{ flexShrink: 0, display: "flex", alignItems: "center", gap: 0.65, flexWrap: "nowrap" }}>{right}</Box>
      </Stack>
      {dateLabel ? (
        <Typography
          sx={{
            mt: 0.15,
            textAlign: "center",
            fontSize: 12,
            fontWeight: 500,
            color: "text.secondary",
            lineHeight: 1.35,
            px: 1,
          }}
        >
          {dateLabel}
        </Typography>
      ) : null}
    </Box>
  );
}
