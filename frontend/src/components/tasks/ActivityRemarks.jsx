import { useState } from "react";
import { Box, Button, Collapse, MenuItem, Stack, TextField, Typography } from "@mui/material";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";

function remarkKey(remark, index) {
  return remark.id || `${remark.author_user_id}-${remark.created_at}-${index}`;
}

export default function ActivityRemarks({
  remarks = [],
  items = [],
  readOnly = false,
  busy = false,
  onAdd,
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [taskCode, setTaskCode] = useState("");
  const count = Array.isArray(remarks) ? remarks.length : 0;
  const choices = (items || []).filter((item) => item.task_code);

  const submit = async () => {
    const body = text.trim();
    if (!body || !onAdd) return;
    await onAdd(body, taskCode || null);
    setText("");
  };

  return (
    <Box>
      <Button
        size="small"
        startIcon={<ChatBubbleOutlineIcon />}
        onClick={() => setOpen((value) => !value)}
        sx={{ textTransform: "none", fontWeight: 800, px: 0 }}
        aria-expanded={open}
      >
        {count ? `Remarks (${count})` : "Remarks"}
      </Button>
      <Collapse in={open}>
        <Stack spacing={0.75} sx={{ mt: 0.5 }}>
          {count ? (
            remarks.map((remark, index) => (
              <Box key={remarkKey(remark, index)}>
                <Typography variant="caption" sx={{ fontWeight: 800 }} display="block">
                  {remark.author_name || "User"} · {remark.author_role || "employee"}
                  {remark.task_code ? ` · ${remark.task_code}` : ""}
                  {remark.created_at_label ? ` · ${remark.created_at_label}` : ""}
                </Typography>
                <Typography variant="body2">{remark.body}</Typography>
              </Box>
            ))
          ) : (
            <Typography variant="caption" color="text.secondary">
              No remarks yet.
            </Typography>
          )}
          {!readOnly && onAdd ? (
            <Stack spacing={0.75}>
              {choices.length ? (
                <TextField
                  select
                  size="small"
                  label="About"
                  value={taskCode}
                  onChange={(event) => setTaskCode(event.target.value)}
                >
                  <MenuItem value="">Activity</MenuItem>
                  {choices.map((item) => (
                    <MenuItem key={item.task_code} value={item.task_code}>
                      {item.task_name || item.task_label || item.task_code}
                    </MenuItem>
                  ))}
                </TextField>
              ) : null}
              <TextField
                size="small"
                multiline
                minRows={2}
                label="Add a remark"
                value={text}
                onChange={(event) => setText(event.target.value)}
                inputProps={{ maxLength: 1000 }}
              />
              <Button
                size="small"
                variant="outlined"
                disabled={busy || !text.trim()}
                onClick={submit}
                sx={{ textTransform: "none", fontWeight: 800, alignSelf: "flex-start" }}
              >
                Add remark
              </Button>
            </Stack>
          ) : null}
        </Stack>
      </Collapse>
    </Box>
  );
}
