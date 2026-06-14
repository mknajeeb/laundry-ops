import { Box, Typography } from "@mui/material";
import ShiftCountCard from "./ShiftCountCard";

const GRID_BY_LAYOUT = {
  kpi: {
    xs: "repeat(1, minmax(0, 1fr))",
    sm: "repeat(3, minmax(0, 1fr))",
  },
  snapshot: {
    xs: "repeat(1, minmax(0, 1fr))",
    sm: "repeat(2, minmax(0, 1fr))",
  },
  default: {
    xs: "repeat(2, minmax(0, 1fr))",
    sm: "repeat(3, minmax(0, 1fr))",
  },
};

const SIZE_BY_LAYOUT = {
  kpi: "kpi",
  snapshot: "snapshot",
  default: "default",
};

/** Grouped metric cards — mobile-first, large tap targets. */
export default function MetricCardGrid({
  sections,
  onCardClick,
  activeKey,
  compact = false,
}) {
  if (!sections?.length) return null;

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {sections.map((section) => {
        const cards = (section.cards || []).filter((card) => card != null && card.hidden !== true);
        if (!cards.length) return null;
        const layout = section.layout || "default";
        const gridCols = GRID_BY_LAYOUT[layout] || GRID_BY_LAYOUT.default;
        const cardSize = SIZE_BY_LAYOUT[layout] || (compact ? "snapshot" : "default");
        return (
          <Box key={section.key || section.title || cards[0]?.key}>
            {section.title ? (
              <Typography
                variant="subtitle2"
                fontWeight={700}
                color="text.primary"
                display="block"
                sx={{ mb: 1 }}
              >
                {section.title}
              </Typography>
            ) : null}
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: gridCols,
                gap: layout === "kpi" ? 1.5 : 1.1,
                maxWidth: "100%",
                overflow: "hidden",
              }}
            >
              {cards.map((card) => {
                const clickable = card.clickable !== false && Boolean(onCardClick) && (card.count != null || card.sub);
                const cardKey = card.key || card.drilldownTag || card.label;
                return (
                  <ShiftCountCard
                    key={cardKey}
                    label={card.label}
                    value={card.count ?? "—"}
                    sub={card.sub}
                    onClick={clickable && card.count != null ? () => onCardClick(card) : undefined}
                    active={activeKey === cardKey}
                    warn={card.warn}
                    compact={compact || card.compact}
                    variant={card.variant || "default"}
                    large={card.large}
                    size={card.size || cardSize}
                    subPreLine={Boolean(card.sub)}
                  />
                );
              })}
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
