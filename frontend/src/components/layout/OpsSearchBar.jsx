import { Clear, Search } from "@mui/icons-material";
import { IconButton, InputAdornment, Paper, TextField } from "@mui/material";

/** Full-width search with icon clear (compact for floor screens). */
export default function OpsSearchBar({ value, onChange, placeholder = "Search…" }) {
  return (
    <Paper
      elevation={0}
      sx={{
        mt: 0.85,
        p: 1,
        borderRadius: 2,
        border: "1px solid rgba(148, 163, 184, 0.45)",
        bgcolor: "rgba(255,255,255,0.92)",
      }}
    >
      <TextField
        fullWidth
        size="small"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <Search fontSize="small" sx={{ color: "text.secondary" }} />
            </InputAdornment>
          ),
          endAdornment: value ? (
            <InputAdornment position="end">
              <IconButton size="small" aria-label="Clear search" onClick={() => onChange("")} edge="end">
                <Clear fontSize="small" />
              </IconButton>
            </InputAdornment>
          ) : null,
        }}
      />
    </Paper>
  );
}
