import { useState } from "react";
import { Box, Button, Collapse, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { OPS_MOBILE } from "../../opsMobile";
import TaskCompletionInputs from "../../opsMobile/TaskCompletionInputs";
import { useI18n } from "../../i18n/I18nContext";
import { localizedConfigured, localizedInstruction } from "./taskEmployeeI18n";
import {
  groupChecklistSections,
  responsibilityLabel,
  splitSharedChecklist,
  TEAM_RESPONSIBILITY_LABEL,
  visibleSectionLabel,
} from "./sharedChecklistOwnership";

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
  const { t, locale } = useI18n();
  const [info, setInfo] = useState(false);
  const done = ["completed", "approved", "verified"].includes(String(item.status || "").toLowerCase());
  const instructions = localizedInstruction(item, locale);
  const itemName =
    localizedConfigured(
      { task_name: item.task_name || item.task_label, task_name_es: item.task_name_es },
      locale,
      "task_name",
      "task_name_es",
    ) || item.task_code;
  const responsibility = responsibilityLabel(item);
  const responsibilityText =
    responsibility === TEAM_RESPONSIBILITY_LABEL ? t("tasks.pin.anyone") : responsibility;
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
            {itemName}
            {item.required === false ? ` ${t("tasks.pin.optionalParen")}` : ""}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {responsibilityText}
            {done
              ? item.completed_by_name
                ? ` · ${t("tasks.pin.checkedOffBy", { name: item.completed_by_name })}`
                : ` · ${t("tasks.pin.checkedOff")}`
              : ""}
          </Typography>
        </Box>
        {instructions ? (
          <Tooltip title={instructions} enterTouchDelay={0} leaveTouchDelay={4000} arrow>
            <IconButton size="small" aria-label={t("tasks.pin.instructions")} onClick={() => setInfo((open) => !open)}>
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
            sx={{ mt: 1, minHeight: 48, fontWeight: 800, textTransform: "none" }}
          >
            {editing ? t("tasks.pin.saveCheckoff") : t("tasks.pin.checkOff")}
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
  const { t, locale } = useI18n();
  const [othersOpen, setOthersOpen] = useState(false);
  const split = splitSharedChecklist(items, userId);
  const renderSections = (source, keyPrefix, startOpen) => {
    const sections = groupChecklistSections(source);
    return sections.map((section) => {
      const rows = (
        <Stack spacing={1}>
          {section.items.map((item) => (
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
      );
      const title = visibleSectionLabel(
        (locale === "es" && section.labelEs) || section.label,
        sections.length,
      );
      if (!title) return <Box key={`${keyPrefix}-${section.label}`}>{rows}</Box>;
      return (
        <SectionBlock
          key={`${keyPrefix}-${section.label}`}
          title={title}
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
          startOpen={startOpen && section.done < section.total}
        />
      );
    });
  };
  return (
    <Stack spacing={1}>
      <Typography variant="body2" sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
        {t("tasks.pin.progress", { done: split.requiredDone, total: split.requiredTotal })}
      </Typography>
      <Typography variant="caption" sx={{ fontWeight: 800, color: "text.secondary" }}>
        {t("tasks.pin.myItems")}
      </Typography>
      {split.myItems.length ? (
        renderSections(split.myItems, "mine", true)
      ) : (
        <Typography variant="body2" color="text.secondary">
          {t("tasks.pin.noneAssigned")}
        </Typography>
      )}
      {split.otherItems.length ? (
        <>
          <Button
            size="small"
            onClick={() => setOthersOpen((open) => !open)}
            sx={{ textTransform: "none", px: 0, fontWeight: 800, alignSelf: "flex-start" }}
          >
            {othersOpen
              ? t("tasks.pin.hideOthers")
              : t("tasks.pin.otherItems", { count: split.otherItems.length })}
          </Button>
          <Collapse in={othersOpen}>
            <Stack spacing={1}>
              {renderSections(split.otherItems, "other", false)}
            </Stack>
          </Collapse>
        </>
      ) : null}
    </Stack>
  );
}
