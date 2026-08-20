import { Box, TextField, Typography } from "@mui/material";
import { moneyToInput, parseMoneyInput } from "./revenueFormat";

/**
 * Shared large amount entry for PIN + Management.
 * Blank stays blank (not entered). Explicit 0 stays 0.
 * Focus selects existing value for quick overwrite.
 */
export default function MoneyAmountField({
  label,
  value,
  onChange,
  disabled = false,
  prefix = "$",
  inputRef,
  onEnterNext,
  autoFocus = false,
  sx,
}) {
  const display = moneyToInput(value);

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: "rgba(0,151,178,0.28)",
        bgcolor: "#fff",
        ...sx,
      }}
    >
      {label ? (
        <Typography
          sx={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: 0.6,
            textTransform: "uppercase",
            color: "#64748b",
            mb: 0.75,
          }}
        >
          {label}
        </Typography>
      ) : null}
      <TextField
        inputRef={inputRef}
        value={display}
        disabled={disabled}
        autoFocus={autoFocus}
        fullWidth
        inputMode="decimal"
        autoComplete="off"
        onFocus={(e) => {
          try {
            e.target.select();
          } catch {
            /* ignore */
          }
        }}
        onChange={(e) => {
          const raw = e.target.value;
          // Allow intermediate typing ("" , ".", "0.", etc.) as string in parent via onChange(null|number|string)
          if (raw === "" || raw === "-" || raw === "." || raw === "-.") {
            onChange?.(raw === "" ? null : raw);
            return;
          }
          const cleaned = raw.replace(/[^0-9.-]/g, "");
          onChange?.(cleaned);
        }}
        onBlur={() => {
          const parsed = parseMoneyInput(display);
          onChange?.(parsed);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onEnterNext?.();
          }
        }}
        InputProps={{
          startAdornment: (
            <Typography component="span" sx={{ fontWeight: 800, mr: 0.5, color: "#0f172a" }}>
              {prefix}
            </Typography>
          ),
        }}
        sx={{
          "& .MuiOutlinedInput-root": {
            minHeight: 56,
            fontWeight: 800,
            fontSize: "1.35rem",
            bgcolor: "#F6FAFB",
          },
          "& fieldset": { borderColor: "transparent" },
          "&:hover fieldset": { borderColor: "rgba(0,151,178,0.35)" },
          "&.Mui-focused fieldset": { borderColor: "#0097b2" },
        }}
      />
    </Box>
  );
}
