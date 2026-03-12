import pandas as pd
import re


def clean(x):
    if pd.isna(x):
        return None
    v = str(x).strip()
    return v if v != "" else None


def extract_date_from_text(t):

    if t is None:
        return None

    txt = t.upper()
    parts = txt.split()

    tokens = [re.sub(r"[^0-9/]", "", p) for p in parts]
    candidates = [c for c in tokens if "/" in c and len(c) >= 6]

    for c in candidates:

        try:
            return pd.to_datetime(c, format="%m/%d/%Y").date()
        except:
            pass

        try:
            return pd.to_datetime(c, format="%m/%d/%y").date()
        except:
            pass

        try:
            return pd.to_datetime(c).date()
        except:
            pass

    return None


def parse_number(text):

    if text is None:
        return None

    s = re.sub(r"[^0-9.]", "", text)

    if s == "":
        return None

    try:
        return float(s)
    except:
        return None


def extract_weight(cells):

    for c in cells:

        if c is None:
            continue

        value = parse_number(c)

        if value is not None and 0 <= value <= 200:
            return value

    return None


def extract_name(cells):

    for c in cells:

        if c is None:
            continue

        u = c.upper()

        if "/" in c:
            continue

        if "TODAY" in u:
            continue

        if "RUSH" in u:
            continue

        if "LBS" in u:
            continue

        if u.startswith("USE "):
            continue

        if u == "X":
            continue

        if "?" in c:
            continue

        if "PLEASE" in u:
            continue

        try:
            float(c)
            continue
        except:
            pass

        return c

    return None


def classify_service(cells):
    has_hd_int = False

    for c in cells:

        if c is None:
            continue

        text = c.upper().strip()
        text_no_lbs = text.replace("LBS", "").strip()

        # Explicit WF markers
        if "?" in text:
            return "WF"

        if "LBS" in text:
            return "WF"

        # Decimal numeric values are WF by definition
        if re.search(r"\d+\.\d+", text_no_lbs):
            return "WF"

        # Pure integer values are HD candidates
        if re.fullmatch(r"\d+", text_no_lbs):
            has_hd_int = True

    if has_hd_int:
        return "HD"

    return "WF"


def detect_rush_hint(cells):

    for c in cells:
        if c is None:
            continue
        u = c.upper()
        if ("TODAY" in u) or ("RUSH" in u):
            return True

    return False


def build_ops_summary(df):

    result = {}

    for service in ["WF", "HD"]:

        service_df = df[df["ServiceType"] == service]

        rush_df = service_df[service_df["RushType"] == "RUSH"]
        non_rush_df = service_df[service_df["RushType"] == "NON-RUSH"]

        rush_count = len(rush_df)

        rush_date = None
        if rush_count > 0:
            rush_date = str(rush_df["Date_Clean"].iloc[0])

        non_rush_total = len(non_rush_df)

        non_rush_by_date = []

        if non_rush_total > 0:

            breakup = (
                non_rush_df
                .groupby("Date_Clean")
                .size()
                .reset_index(name="count")
                .sort_values("Date_Clean")
            )

            for _, row in breakup.iterrows():

                non_rush_by_date.append({
                    "date": str(row["Date_Clean"]),
                    "count": int(row["count"])
                })

        result[service] = {
            "rush_count": rush_count,
            "rush_date": rush_date,
            "non_rush_total": non_rush_total,
            "non_rush_by_date": non_rush_by_date
        }

    return result


def transform_orders(df_raw):

    df = df_raw.copy()

    df.columns = [f"Column{i+1}" for i in range(len(df.columns))]

    for col in df.columns:
        df[col] = df[col].apply(clean)

    df["Cells"] = df.apply(
        lambda row: [clean(v) for v in row[df.columns].tolist() if clean(v) is not None],
        axis=1
    )
    df = df[df["Cells"].apply(len) > 0].copy()

    def get_date(row):
        # Prefer row-level date detection from all cells to avoid
        # over-defaulting to an early date when sheet layout changes.
        cells = row.get("Cells") or []
        for c in cells:
            d = extract_date_from_text(c)
            if d is not None:
                return d

        # Fallback legacy behavior
        c1 = clean(row.get("Column1"))
        c2 = clean(row.get("Column2"))
        d1 = extract_date_from_text(c1)
        d2 = extract_date_from_text(c2)
        if d1 is not None:
            return d1
        return d2

    df["Date_Clean"] = df.apply(get_date, axis=1)
    # Keep forward fill only; do not backfill from future rows.
    df["Date_Clean"] = df["Date_Clean"].ffill()

    df["Weight_Num"] = df["Cells"].apply(extract_weight)

    df["Name_Clean"] = df["Cells"].apply(extract_name)

    df = df[
        (df["Date_Clean"].notna()) &
        (df["Name_Clean"].notna()) &
        (
            df["Cells"].apply(
                lambda cells: any(
                    ("?" in c) or
                    ("LBS" in c.upper()) or
                    re.search(r"\d", c)
                    for c in cells if c
                )
            )
        )
    ].copy()

    df["ServiceType"] = df["Cells"].apply(classify_service)

    # Keep direct rush marker from upload row; batch-date rush is applied in backend upload logic
    df["RushHint"] = df["Cells"].apply(detect_rush_hint)
    df["RushType"] = df["RushHint"].apply(lambda x: "RUSH" if x else "NON-RUSH")

    final = df[
        [
            "Date_Clean",
            "Name_Clean",
            "Weight_Num",
            "ServiceType",
            "RushType"
        ]
    ].copy()

    final = final.sort_values("Name_Clean").reset_index(drop=True)

    final["ServiceType"] = pd.Categorical(
        final["ServiceType"],
        categories=["WF", "HD"]
    )

    summary = (
        final
        .groupby(["Date_Clean", "RushType", "ServiceType"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    if "WF" not in summary.columns:
        summary["WF"] = 0

    if "HD" not in summary.columns:
        summary["HD"] = 0

    summary = summary[(summary["WF"] + summary["HD"]) > 0].copy()
    summary = summary.sort_values(["Date_Clean", "RushType"]).reset_index(drop=True)

    ops_summary = build_ops_summary(final)

    return final, summary, ops_summary
