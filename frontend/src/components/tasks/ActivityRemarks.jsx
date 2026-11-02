import { useState } from "react";
import { Box, Button, Collapse, MenuItem, Stack, TextField, Typography } from "@mui/material";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import { useI18n } from "../../i18n/I18nContext";
import { remarkRoleLabel, splitActivityRemarks } from "./taskEmployeeI18n";

function remarkKey(remark, index) {
  return remark.id || `${remark.author_user_id}-${remark.created_at}-${index}`;
}

function RemarkLine({ remark }) {
  const { t } = useI18n();
  return (
    <Box>
      <Typography variant="caption" sx={{ fontWeight: 800 }} display="block">
        {remark.author_name || t("tasks.pin.authorMissing")} · {remarkRoleLabel(t, remark.author_role)}
        {remark.task_code ? ` · ${remark.task_code}` : ""}
        {remark.created_at_label ? ` · ${remark.created_at_label}` : ""}
      </Typography>
      <Typography variant="body2">{remark.body}</Typography>
    </Box>
  );
}

function VerificationLog({ remarks }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState({});
  const groups = [];
  for (const remark of remarks) {
    const key = `${remark.author_name || ""}|${remark.author_role || ""}|${remark.body || ""}`;
    const current = groups.find((group) => group.key === key);
    if (current) current.records.push(remark);
    else groups.push({ key, records: [remark] });
  }
  return (
    <Box>
      <Button
        size="small"
        startIcon={<FactCheckOutlinedIcon />}
        onClick={() => setOpen((value) => !value)}
        sx={{ textTransform: "none", fontWeight: 800, px: 0 }}
        aria-expanded={open}
      >
        {t("tasks.pin.verificationCount", { count: remarks.length })}
      </Button>
      <Collapse in={open}>
        <Stack spacing={0.75} sx={{ mt: 0.5 }}>
          {groups.map((group) => {
            const sample = group.records[0];
            const showEach = Boolean(expanded[group.key]);
            return (
              <Box key={group.key}>
                {showEach ? null : <RemarkLine remark={sample} />}
                {group.records.length > 1 ? (
                  <>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {t("tasks.pin.verificationRecords", { count: group.records.length })}
                    </Typography>
                    <Button
                      size="small"
                      onClick={() => setExpanded((value) => ({ ...value, [group.key]: !value[group.key] }))}
                      sx={{ textTransform: "none", px: 0, fontWeight: 700 }}
                    >
                      {showEach ? t("tasks.pin.hideEach") : t("tasks.pin.showEach")}
                    </Button>
                    <Collapse in={showEach}>
                      <Stack spacing={0.5}>
                        {group.records.map((remark, index) => (
                          <RemarkLine key={remarkKey(remark, index)} remark={remark} />
                        ))}
                      </Stack>
                    </Collapse>
                  </>
                ) : null}
              </Box>
            );
          })}
        </Stack>
      </Collapse>
    </Box>
  );
}

export default function ActivityRemarks({
  remarks = [],
  items = [],
  readOnly = false,
  busy = false,
  onAdd,
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [taskCode, setTaskCode] = useState("");
  const split = splitActivityRemarks(remarks);
  const count = split.comments.length;
  const choices = (items || []).filter((item) => item.task_code);

  const submit = async () => {
    const body = text.trim();
    if (!body || !onAdd) return;
    await onAdd(body, taskCode || null);
    setText("");
  };

  return (
    <Stack spacing={0.25}>
      <Box>
        <Button
          size="small"
          startIcon={<ChatBubbleOutlineIcon />}
          onClick={() => setOpen((value) => !value)}
          sx={{ textTransform: "none", fontWeight: 800, px: 0 }}
          aria-expanded={open}
        >
          {count ? t("tasks.pin.remarksCount", { count }) : t("tasks.pin.remarks")}
        </Button>
        <Collapse in={open}>
          <Stack spacing={0.75} sx={{ mt: 0.5 }}>
            {count ? (
              split.comments.map((remark, index) => <RemarkLine key={remarkKey(remark, index)} remark={remark} />)
            ) : (
              <Typography variant="caption" color="text.secondary">
                {t("tasks.pin.noRemarks")}
              </Typography>
            )}
            {!readOnly && onAdd ? (
              <Stack spacing={0.75}>
                {choices.length ? (
                  <TextField
                    select
                    size="small"
                    label={t("tasks.pin.about")}
                    value={taskCode}
                    onChange={(event) => setTaskCode(event.target.value)}
                  >
                    <MenuItem value="">{t("tasks.pin.aboutActivity")}</MenuItem>
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
                  label={t("tasks.pin.addRemark")}
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
                  {t("tasks.pin.addRemarkButton")}
                </Button>
              </Stack>
            ) : null}
          </Stack>
        </Collapse>
      </Box>
      {split.verification.length ? <VerificationLog remarks={split.verification} /> : null}
    </Stack>
  );
}
