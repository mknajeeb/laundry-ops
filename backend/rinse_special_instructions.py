"""Parse and normalize Rinse portal Special Instructions for supply reporting."""

from __future__ import annotations

import re
from typing import Any

STANDARD_INTERPRETATION = "Standard soap"
STANDARD_SUPPLIES = ("Tide",)

_TOKEN_FAB = "USE FABRIC SOFTENER"
_TOKEN_OXIC = "USE OXICLEAN"
_TOKEN_HYPO = "USE HYPOALLERGENIC SOAP"
_MENU_TOKEN_NORMS = frozenset({_TOKEN_FAB, _TOKEN_OXIC, _TOKEN_HYPO})

_HYPO_PART_RE = re.compile(
    r"\bHYPOALLERGENIC\b|\bHYPO\s*[- ]?\s*ALLERG(?:ENIC)?\b|\bUSE\s+HYPO\b",
    re.I,
)
_OXIC_PART_RE = re.compile(r"\bUSE\s+OXIC(?:LEAN)?\b|\bOXI\s*CLEAN\b|\bOXICLEAN\b", re.I)
_FAB_PART_RE = re.compile(
    r"\bUSE\s+FAB(?:RIC)?(?:\s+SOFTENER)?\b|\bFABRIC\s+SOFTENER\b|\bUSE\s+SOFTENER\b",
    re.I,
)


def _norm_token(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).upper()


def _split_instruction_parts(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    parts = re.split(r"[;\n|]+", text)
    out: list[str] = []
    for part in parts:
        p = re.sub(r"\s+", " ", part).strip()
        if p:
            out.append(p)
    return out


def _is_portal_vendor_catalog_part(part: str) -> bool:
    """Portal expanded rows often include the full vendor item-type picker as one blob."""
    u = _norm_token(part)
    if not u.startswith("VENDOR NOTES"):
        return False
    return bool(
        re.search(
            r"\b(VENDOR PRICE|WASH AND FOLD|HANG DRY|DRY CLEAN|PRESS ONLY|SPECIALTY ITEMS)\b",
            u,
        )
    )


def _should_skip_instruction_part(part: str, *, had_vendor_catalog: bool) -> bool:
    if _is_portal_vendor_catalog_part(part):
        return True
    # When vendor UI was scraped in, appended menu labels are not customer prefs.
    if had_vendor_catalog and _norm_token(part) in _MENU_TOKEN_NORMS:
        return True
    return False


def _parts_for_interpretation(raw: str | None) -> list[str]:
    parts = _split_instruction_parts(str(raw or ""))
    had_vendor_catalog = any(_is_portal_vendor_catalog_part(p) for p in parts)
    return [
        part
        for part in parts
        if not _should_skip_instruction_part(part, had_vendor_catalog=had_vendor_catalog)
    ]


def _classify_part(part: str) -> str | None:
    u = _norm_token(part)
    if not u:
        return None
    if _HYPO_PART_RE.search(u) and "HYPOCHLOR" not in u:
        return _TOKEN_HYPO
    if _OXIC_PART_RE.search(u):
        return _TOKEN_OXIC
    if _FAB_PART_RE.search(u):
        return _TOKEN_FAB
    if u in {"X", "YES", "Y", "TRUE", "1"}:
        return None
    return "UNKNOWN"


def build_special_instructions_raw(
    *,
    special_instructions_col: str | None = None,
    use_oxic: str | None = None,
    use_hypo: str | None = None,
    use_fab: str | None = None,
    notes: str | None = None,
) -> str | None:
    """Combine explicit Special Instructions column with portal flag columns and notes."""
    parts: list[str] = []
    seen: set[str] = set()

    def _add(text: str | None) -> None:
        t = re.sub(r"\s+", " ", str(text or "").strip())
        if not t:
            return
        if _is_portal_vendor_catalog_part(t):
            return
        key = _norm_token(t)
        if key in seen:
            return
        seen.add(key)
        parts.append(t)

    si_col = re.sub(r"\s+", " ", str(special_instructions_col or "").strip())
    if si_col and not _is_portal_vendor_catalog_part(si_col):
        _add(si_col)
    for chunk in _split_instruction_parts(notes or ""):
        if not _is_portal_vendor_catalog_part(chunk):
            _add(chunk)

    if _flag_marked(use_fab):
        _add("USE FABRIC SOFTENER")
    if _flag_marked(use_oxic):
        _add("USE OXICLEAN")
    if _flag_marked(use_hypo):
        _add("Use Hypoallergenic Soap")

    if not parts:
        return None
    return "; ".join(parts)


def _flag_marked(val: str | None) -> bool:
    s = str(val or "").strip().upper()
    return s in {"X", "YES", "Y", "TRUE", "1", "✓"}


def interpret_special_instructions(raw: str | None) -> dict[str, Any]:
    """
    Map raw Special Instructions text to normalized interpretation and supplies.

    Returns:
        interpretation: human-readable label
        supplies: tuple of supply product names
        special_instruction_review: True when text is unmapped
    """
    if not str(raw or "").strip():
        return {
            "special_instructions_raw": None,
            "supply_interpretation": STANDARD_INTERPRETATION,
            "supplies_used": list(STANDARD_SUPPLIES),
            "special_instruction_review": False,
        }

    parts = _parts_for_interpretation(raw)
    if not parts:
        return {
            "special_instructions_raw": None,
            "supply_interpretation": STANDARD_INTERPRETATION,
            "supplies_used": list(STANDARD_SUPPLIES),
            "special_instruction_review": False,
        }

    tokens: set[str] = set()
    unknown_parts: list[str] = []

    for part in parts:
        kind = _classify_part(part)
        if kind == "UNKNOWN":
            unknown_parts.append(part)
        elif kind:
            tokens.add(kind)

    if unknown_parts and not tokens:
        return {
            "special_instructions_raw": raw,
            "supply_interpretation": "Needs review",
            "supplies_used": [],
            "special_instruction_review": True,
        }

    hypo = _TOKEN_HYPO in tokens
    fab = _TOKEN_FAB in tokens
    oxic = _TOKEN_OXIC in tokens

    if hypo:
        soap = "Hypoallergenic soap"
        detergent = "Hypoallergenic detergent"
        if fab and oxic:
            interpretation = "Hypoallergenic soap + softener + OxiClean"
            supplies = (detergent, "Downy", "OxiClean")
        elif fab:
            interpretation = "Hypoallergenic soap + softener"
            supplies = (detergent, "Downy")
        elif oxic:
            interpretation = "Hypoallergenic soap + OxiClean"
            supplies = (detergent, "OxiClean")
        else:
            interpretation = soap
            supplies = (detergent,)
    elif fab and oxic:
        interpretation = "Soap + softener + OxiClean"
        supplies = ("Tide", "Downy", "OxiClean")
    elif fab:
        interpretation = "Soap + softener"
        supplies = ("Tide", "Downy")
    elif oxic:
        interpretation = "Soap + OxiClean"
        supplies = ("Tide", "OxiClean")
    else:
        interpretation = STANDARD_INTERPRETATION
        supplies = STANDARD_SUPPLIES

    needs_review = bool(unknown_parts)
    if needs_review and interpretation == STANDARD_INTERPRETATION:
        interpretation = "Needs review"

    return {
        "special_instructions_raw": raw,
        "supply_interpretation": interpretation,
        "supplies_used": list(supplies),
        "special_instruction_review": needs_review,
    }


def enrich_row_with_special_instructions(row: dict[str, Any]) -> dict[str, Any]:
    """Add special instruction fields to a portal/staging row dict."""
    raw = build_special_instructions_raw(
        special_instructions_col=row.get("Special_Instructions") or row.get("special_instructions"),
        use_oxic=row.get("USE OXIC") or row.get("USE_OXIC"),
        use_hypo=row.get("Use Hypo") or row.get("Use_Hypo"),
        use_fab=row.get("USE FAB") or row.get("USE_FAB"),
        notes=row.get("Notes") or row.get("notes"),
    )
    parsed = interpret_special_instructions(raw)
    out = dict(row)
    out["special_instructions_raw"] = parsed["special_instructions_raw"]
    out["supply_interpretation"] = parsed["supply_interpretation"]
    out["supplies_used"] = parsed["supplies_used"]
    out["special_instruction_review"] = parsed["special_instruction_review"]
    return out
