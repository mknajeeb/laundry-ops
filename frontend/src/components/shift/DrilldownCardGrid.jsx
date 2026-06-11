import ShiftCountCard from "./ShiftCountCard";

/** Render backend drilldown contract cards. */
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
        const parityMismatch =
          tag
          && card.count != null
          && card.records_count != null
          && card.records_count !== card.count;
        const showReview = Boolean(
          card.needs_review
          && (parityMismatch || card.sync_stale || card.sync_failed || card.source_missing),
        );
        const clickable = Boolean((card.clickable !== false) && tag && onDrilldown && !showReview);
        const value = showReview ? "Review" : card.count ?? "—";
        return (
          <ShiftCountCard
            key={`${card.label}-${tag || "static"}`}
            label={card.label}
            value={value}
            sub={
              showReview
                ? card.under_review_reason || "Needs Review"
                : card.records_count != null && card.count != null && card.records_count !== card.count
                  ? `Rows ${card.records_count}`
                  : undefined
            }
            onClick={clickable ? () => onDrilldown(tag) : undefined}
            active={tag && activeTag === tag}
            warn={showReview}
            compact={compact}
          />
        );
      })}
    </div>
  );
}
