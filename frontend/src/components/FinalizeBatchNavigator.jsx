import { useMemo, useState } from "react";
import { Box, Button, Chip, Collapse, Stack, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { displayStatusColor } from "../payroll/payrollBatchStatus";
import {
  FINALIZE_NAV_INITIAL_COUNT,
  formatFinalizeBatchRow,
  groupFinalizeBatches,
  visibleFinalizeBatches,
} from "../payroll/finalizeBatchNav";

export default function FinalizeBatchNavigator({ batches = [], selectedId, onSelect }) {
  const groups = useMemo(() => groupFinalizeBatches(batches), [batches]);
  const [open, setOpen] = useState({ w2: true, contractor_1099: true, temp: true });
  const [expanded, setExpanded] = useState({});

  return (
    <Stack spacing={1}>
      {groups.map((section) => {
        const shown = visibleFinalizeBatches(section.items, Boolean(expanded[section.key]));
        const hidden = section.items.length - shown.length;
        return (
          <Box key={section.key}>
            <Button
              size="small"
              onClick={() => setOpen((prev) => ({ ...prev, [section.key]: !prev[section.key] }))}
              startIcon={
                <ExpandMoreIcon
                  fontSize="small"
                  sx={{ transform: open[section.key] ? "rotate(180deg)" : "none" }}
                />
              }
              sx={{ fontWeight: 700, color: "text.primary" }}
            >
              {section.label}
              <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                {section.items.length}
              </Typography>
            </Button>
            <Collapse in={Boolean(open[section.key])}>
              <Stack spacing={0.5} sx={{ pl: 1, pb: 0.5 }}>
                {shown.map((b) => {
                  const selected = String(selectedId) === String(b.id);
                  return (
                    <Button
                      key={b.id}
                      size="small"
                      variant={selected ? "contained" : "text"}
                      color={selected ? "primary" : "inherit"}
                      onClick={() => onSelect?.(b.id)}
                      sx={{
                        justifyContent: "space-between",
                        textTransform: "none",
                        fontWeight: selected ? 700 : 500,
                      }}
                    >
                      <span>{formatFinalizeBatchRow(b)}</span>
                      <Chip
                        size="small"
                        label={b.payroll_display?.display_status_label || "Draft"}
                        color={displayStatusColor(b)}
                        sx={{ ml: 1 }}
                      />
                    </Button>
                  );
                })}
                {section.items.length > FINALIZE_NAV_INITIAL_COUNT ? (
                  <Button
                    size="small"
                    onClick={() =>
                      setExpanded((prev) => ({ ...prev, [section.key]: !prev[section.key] }))
                    }
                    sx={{ alignSelf: "flex-start" }}
                  >
                    {expanded[section.key]
                      ? "Show less"
                      : `Show more (${hidden})`}
                  </Button>
                ) : null}
              </Stack>
            </Collapse>
          </Box>
        );
      })}
    </Stack>
  );
}
