import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import LightbulbOutlinedIcon from "@mui/icons-material/LightbulbOutlined";

export default function RosterBoardSuggestionsPanel({ suggestions, onAction, collapsed, onToggle }) {
  if (!suggestions?.length) {
    return (
      <Alert severity="success" icon={<LightbulbOutlinedIcon />} sx={{ borderRadius: 2 }}>
        No rule-based suggestions right now — coverage looks good.
      </Alert>
    );
  }

  return (
    <Box sx={{ borderRadius: 2, border: "1px solid", borderColor: "divider", overflow: "hidden" }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ px: 1.5, py: 1, bgcolor: "action.hover", cursor: onToggle ? "pointer" : "default" }}
        onClick={onToggle}
      >
        <Typography variant="subtitle2" fontWeight={800}>
          Suggestions ({suggestions.length})
        </Typography>
        {onToggle ? (
          <Typography variant="caption" fontWeight={700}>
            {collapsed ? "Show" : "Hide"}
          </Typography>
        ) : null}
      </Stack>
      {!collapsed ? (
        <Stack spacing={1} sx={{ p: 1.5, maxHeight: 280, overflow: "auto" }}>
          {suggestions.map((s) => (
            <Alert
              key={s.id}
              severity={s.severity === "error" ? "error" : s.severity === "warning" ? "warning" : "info"}
              sx={{ py: 0.5, "& .MuiAlert-message": { width: "100%" } }}
              action={
                s.action === "fill_gap" && s.gap ? (
                  <Button size="small" color="inherit" onClick={() => onAction?.(s)}>
                    Add
                  </Button>
                ) : s.action === "edit_entry" && s.entry ? (
                  <Button size="small" color="inherit" onClick={() => onAction?.(s)}>
                    Edit
                  </Button>
                ) : null
              }
            >
              <Typography variant="body2" fontWeight={700}>
                {s.title}
              </Typography>
              {s.subtitle ? (
                <Typography variant="caption" display="block">
                  {s.subtitle}
                </Typography>
              ) : null}
            </Alert>
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}
