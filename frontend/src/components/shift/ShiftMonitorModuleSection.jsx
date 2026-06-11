import { Alert, Box, Typography } from "@mui/material";
import ModuleFilterBar from "./ModuleFilterBar";
import ShiftCountCard from "./ShiftCountCard";
import { filterCardsForScope, getModuleCardCount } from "../../utils/shiftMonitorHelpers";
import { formatLastWash } from "../../utils/shiftMonitorHelpers";

export default function ShiftMonitorModuleSection({
  moduleKey,
  module,
  records,
  rushFilter,
  serviceFilter,
  onRushChange,
  onServiceChange,
  onDrilldown,
  activeTag,
  operationsLabel,
}) {
  if (!module) return null;

  const filtersEnabled = module.filters_enabled !== false;
  const cards = filterCardsForScope(module.cards || [], serviceFilter);
  const subtitle = module.subtitle || (moduleKey !== "portal_snapshot" ? operationsLabel : null);

  const openDrilldown = (card) => {
    if (!card?.module_tag || card.informational || !filtersEnabled) return;
    onDrilldown?.({
      moduleTag: card.module_tag,
      moduleTitle: module.title,
      cardLabel: card.label,
      moduleKey,
    });
  };

  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 0.25 }}>
        {module.title}
      </Typography>
      {subtitle ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
          {subtitle}
        </Typography>
      ) : null}
      {module.note ? (
        <Alert severity="info" sx={{ mb: 1, py: 0.25 }}>
          {module.note}
        </Alert>
      ) : null}
      <ModuleFilterBar
        rushFilter={rushFilter}
        serviceFilter={serviceFilter}
        onRushChange={onRushChange}
        onServiceChange={onServiceChange}
        disabled={!filtersEnabled}
      />
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
          gap: 1,
        }}
      >
        {cards.map((card) => {
          const count = getModuleCardCount(records, card, rushFilter, serviceFilter, module);
          const clickable = Boolean(card.module_tag && filtersEnabled && !card.informational);
          const active = activeTag?.moduleTag === card.module_tag && activeTag?.moduleKey === moduleKey;
          if (card.detail) {
            return (
              <ShiftCountCard
                key={card.id}
                label={card.label}
                value=" "
                sub={formatLastWash(card.detail, "—")}
                subPreLine
                compact
              />
            );
          }
          if (card.id === "mon_weight" && serviceFilter === "hd") {
            return (
              <ShiftCountCard key={card.id} label={card.label} value="N/A" sub="HD has no weighing" compact />
            );
          }
          const parityMismatch = clickable && card.records_count != null && count !== card.records_count;
          return (
            <ShiftCountCard
              key={card.id}
              label={card.label}
              value={count ?? card.count ?? "—"}
              onClick={clickable ? () => openDrilldown(card) : undefined}
              active={active}
              warn={parityMismatch || (card.needs_review && clickable)}
              sub={parityMismatch ? "Needs Review" : undefined}
              compact
            />
          );
        })}
      </Box>
    </Box>
  );
}
