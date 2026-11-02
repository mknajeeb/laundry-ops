import { useState } from "react";
import { Box, Button, Collapse, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { OPS_MOBILE } from "../../opsMobile";
import TaskCompletionInputs from "../../opsMobile/TaskCompletionInputs";
import { groupChecklistSections, responsibilityLabel, splitSharedChecklist } from "./sharedChecklistOwnership";

function SectionBlock({ title, done, total, items, busy, editingCode, inputValues, inputRemarks, onChangeValues, onChangeRemarks, onCheckoff, startOpen }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <Box>
      <Button
        fullWidth
        onClick={() => setOpen((value) => !value)}
        sx={{ justifyContent: "space-between", textTransform: "none", fontWeight: 800, px: 0 }}
      >
        <span>{title}</span>
        <span>
          {done}/{total}
        </span>
      </Button>
      <Collapse in={open}>
        <Stack spacing={1}>
          {items.map((item) => (
            <ItemRow
              key={item.task_code || item.id}
              item={item}
              busy={busy}
              editing={editingCode === item.task_code}
              inputValues={inputValues}
              inputRemarks={inputRemarks}
              onChangeValues={onChangeValues}
              onChangeRemarks={onChangeRemarks}
              onCheckoff={onCheckoff}
            />
          ))}
        </Stack>
      </Collapse>
    </Box>
  );
}

function ItemRow({ item, busy, editing, inputValues, inputRemarks, onChangeValues, onChangeRemarks, onCheckoff }) {
  const [info, setInfo] = useState(false);
  const done = ["completed", "approved", "verified"].includes(String(item.status || "").toLowerCase());
  const instructions = String(item.instructions || "").trim();
  return (
    <Box
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: `1px solid ${OPS_MOBILE.border}`,
        bgcolor: done ? "#f0fdf4" : "#fff",
      }}
    >
      <Stack direction="row" alignItems="flex-start" spacing={0.5}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
            {item.task_name || item.task_label || item.task_code}
            {item.required === false ? " (optional)" : ""}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {responsibilityLabel(item)}
            {done
              ? item.completed_by_name
                ? ` · Checked off by ${item.completed_by_name}`
                : " · Checked off"
              : ""}
          </Typography>
        </Box>
        {instructions ? (
          <Tooltip title={instructions} enterTouchDelay={0} leaveTouchDelay={4000} arrow>
            <IconButton size="small" aria-label="Instructions" onClick={() => setInfo((open) => !open)}>
              <InfoOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : null}
      </Stack>
      <Collapse in={info}>
        <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: "pre-wrap" }}>
          {instructions}
        </Typography>
      </Collapse>
      {!done ? (
        <>
          {editing ? (
            <TaskCompletionInputs
              schema={item.input_schema || []}
              values={inputValues}
              remarks={inputRemarks}
              onChangeValues={onChangeValues}
              onChangeRemarks={onChangeRemarks}
              disabled={busy}
            />
          ) : null}
          <Button
            fullWidth
            variant="outlined"
            disabled={busy}
            onClick={() => onCheckoff?.(item)}
            sx={{ mt: 1, fontWeight: 800, textTransform: "none" }}
          >
            {editing ? "Save check-off" : "Check off"}
          </Button>
        </>
      ) : null}
    </Box>
  );
}

/**
 * Compact shared Activity checklist: my items, collapsed team items, one progress line.
 */
export default function SharedActivityChecklist({
  items = [],
  userId,
  busy = false,
  editingCode = "",
  inputValues,
  inputRemarks,
  onChangeValues,
  onChangeRemarks,
  onCheckoff,
}) {
  const [othersOpen, setOthersOpen] = useState(false);
  const split = splitSharedChecklist(items, userId);
  return (
    <Stack spacing={1}>
      <Typography variant="body2" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
        Progress: {split.requiredDone}/{split.requiredTotal}
      </Typography>
      <Typography variant="caption" sx={{ fontWeight: 800, color: "text.secondary" }}>
        My Items
      </Typography>
      {split.myItems.length ? (
        groupChecklistSections(split.myItems).map((section) => (
          <SectionBlock
            key={section.label}
            title={section.label}
            done={section.done}
            total={section.total}
            items={section.items}
            busy={busy}
            editingCode={editingCode}
            inputValues={inputValues}
            inputRemarks={inputRemarks}
            onChangeValues={onChangeValues}
            onChangeRemarks={onChangeRemarks}
            onCheckoff={onCheckoff}
            startOpen={section.done < section.total}
          />
        ))
      ) : (
        <Typography variant="body2" color="text.secondary">
          None assigned to you
        </Typography>
      )}
      {split.otherItems.length ? (
        <>
          <Button
            size="small"
            onClick={() => setOthersOpen((open) => !open)}
            sx={{ textTransform: "none", px: 0, fontWeight: 800, alignSelf: "flex-start" }}
          >
            {othersOpen ? "Hide other team items" : `Other Team Items (${split.otherItems.length})`}
          </Button>
          <Collapse in={othersOpen}>
            <Stack spacing={1}>
              {groupChecklistSections(split.otherItems).map((section) => (
                <SectionBlock
                  key={`other-${section.label}`}
                  title={section.label}
                  done={section.done}
                  total={section.total}
                  items={section.items}
                  busy={busy}
                  editingCode={editingCode}
                  inputValues={inputValues}
                  inputRemarks={inputRemarks}
                  onChangeValues={onChangeValues}
                  onChangeRemarks={onChangeRemarks}
                  onCheckoff={onCheckoff}
                  startOpen={false}
                />
              ))}
            </Stack>
          </Collapse>
        </>
      ) : null}
    </Stack>
  );
}
