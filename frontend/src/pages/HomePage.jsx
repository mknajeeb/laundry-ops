import { Box, Button, Paper, Stack, Typography } from "@mui/material";
import {
  AccessTime,
  BuildCircle,
  CloudUpload,
  Inventory2,
  LocalShipping,
  PrecisionManufacturing,
} from "@mui/icons-material";
import { useNavigate } from "react-router-dom";

const SECTION_CARD = {
  borderRadius: 3,
  p: 2,
  border: "1px solid #e5e7eb",
  boxShadow: "none",
};

const TILE_BASE = {
  borderRadius: 2.5,
  textTransform: "none",
  justifyContent: "flex-start",
  py: 1.5,
  px: 1.5,
  fontWeight: 500,
  fontSize: 16,
};

function HomePage() {
  const navigate = useNavigate();

  return (
    <Box sx={{ minHeight: "100%", bgcolor: "#ffffff", p: { xs: 1.2, sm: 2 } }}>
      <Stack spacing={1.2} sx={{ mb: 1.5 }}>
        <Typography sx={{ fontSize: { xs: 26, sm: 32 }, fontWeight: 500, lineHeight: 1.05 }}>
          Washpro Operations
        </Typography>
        <Typography sx={{ color: "#6b7280", fontWeight: 500 }}>
          Choose a module to continue.
        </Typography>
      </Stack>

      <Stack spacing={1.2}>
        <Paper sx={SECTION_CARD}>
          <Typography sx={{ mb: 1, fontWeight: 500, fontSize: 14, letterSpacing: 0.3 }}>
            RINSE FLOW
          </Typography>
          <Stack spacing={1}>
            <Button
              fullWidth
              startIcon={<LocalShipping />}
              sx={{
                ...TILE_BASE,
                bgcolor: "#0097b2",
                color: "#ffffff",
                "&:hover": { bgcolor: "#007f95" },
              }}
              onClick={() => navigate("/dashboard")}
            >
              Dashboard
            </Button>
            <Button
              fullWidth
              startIcon={<CloudUpload />}
              sx={{
                ...TILE_BASE,
                bgcolor: "#111827",
                color: "#ffbd59",
                border: "1px solid #ffbd59",
                "&:hover": { bgcolor: "#0b1220" },
              }}
              onClick={() => navigate("/upload")}
            >
              Upload Orders
            </Button>
            <Button
              fullWidth
              startIcon={<Inventory2 />}
              sx={{
                ...TILE_BASE,
                bgcolor: "#f8fafc",
                color: "#111827",
                border: "1px solid #e5e7eb",
                "&:hover": { bgcolor: "#f1f5f9" },
              }}
              onClick={() => navigate("/orders")}
            >
              Orders
            </Button>
          </Stack>
        </Paper>

        <Paper sx={SECTION_CARD}>
          <Typography sx={{ mb: 1, fontWeight: 500, fontSize: 14, letterSpacing: 0.3 }}>
            EMPLOYEE FLOW
          </Typography>
          <Stack spacing={1}>
            <Button
              fullWidth
              startIcon={<AccessTime />}
              sx={{
                ...TILE_BASE,
                bgcolor: "#0f766e",
                color: "#ffffff",
                "&:hover": { bgcolor: "#0d5f59" },
              }}
              onClick={() => navigate("/clock")}
            >
              Clock In / Clock Out
            </Button>
            <Button
              fullWidth
              startIcon={<PrecisionManufacturing />}
              sx={{
                ...TILE_BASE,
                bgcolor: "#f8fafc",
                color: "#111827",
                border: "1px solid #e5e7eb",
                "&:hover": { bgcolor: "#f1f5f9" },
              }}
              onClick={() => navigate("/production")}
            >
              Production
            </Button>
            <Button
              fullWidth
              startIcon={<BuildCircle />}
              sx={{
                ...TILE_BASE,
                bgcolor: "#f8fafc",
                color: "#111827",
                border: "1px solid #e5e7eb",
                "&:hover": { bgcolor: "#f1f5f9" },
              }}
              onClick={() => navigate("/maintenance")}
            >
              Maintenance
            </Button>
          </Stack>
        </Paper>
      </Stack>
    </Box>
  );
}

export default HomePage;
