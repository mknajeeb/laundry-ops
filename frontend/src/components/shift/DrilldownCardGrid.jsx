import ShiftCountCard from "./ShiftCountCard";

/** Render backend drilldown contract cards — clickable only when parity OK. */
export default function DrilldownCardGrid({ cards, onDrilldown, activeTag, compact = true, rushFilter = "all" }) {
  if (!cards?.length) return null;

  const visible = cards.filter((card) => {
    if (!card?.drilldown_tag) return !card?.needs_review;
    if (rushFilter === "rush" && card.drilldown_tag.includes("non_rush")) return false;
    if (rushFilter === "non_rush" && card.drilldown_tag.includes("rush") && !card.drilldown_tag.includes("non_rush")) {
      const tag = card.drilldown_tag;
      if (tag.includes("_rush") && !tag.includes("non_rush")) return false;
    }
    return true;
  });

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
        gap: 8,
      }}
    >
      {visible.map((card) => {
        const tag = card.drilldown_tag;
        const clickable = Boolean(card.clickable && tag && onDrilldown);
        const value = card.needs_review ? "Review" : card.count ?? "—";
        return (
          <ShiftCountCard
            key={`${card.label}-${tag || "review"}`}
            label={card.label}
            value={value}
            sub={
              card.needs_review
                ? card.under_review_reason || "Needs Review"
                : card.records_count != null && card.count != null && card.records_count !== card.count
                  ? `Rows ${card.records_count}`
                  : undefined
            }
            onClick={clickable ? () => onDrilldown(tag) : undefined}
            active={tag && activeTag === tag}
            warn={card.needs_review}
            compact={compact}
          />
        );
      })}
    </div>
  );
}
