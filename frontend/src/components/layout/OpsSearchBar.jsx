import { Search } from "@mui/icons-material";
import { Button, InputAdornment, Paper, TextField } from "@mui/material";

/** Same pattern as Orders: full-width search with clear. */
export default function OpsSearchBar({ value, onChange, placeholder = "Search name, type, weight/count" }) {
  return (
    <Paper sx={{ mt: 1.1, p: 1.1, borderRadius: 2, border: "1px solid #e5e7eb" }}>
      <TextField
        fullWidth
        size="small"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <Search fontSize="small" />
            </InputAdornment>
          ),
          endAdornment: (
            <InputAdornment position="end">
              <Button size="small" onClick={() => onChange("")} sx={{ textTransform: "none", minWidth: 48, fontWeight: 400 }}>
                Clear
              </Button>
            </InputAdornment>
          ),
        }}
      />
    </Paper>
  );
}
