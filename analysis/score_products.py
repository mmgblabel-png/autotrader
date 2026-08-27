from pathlib import Path

import pandas as pd

INPUT = Path("analysis/product_candidates.csv")
OUTPUT = Path("analysis/product_scored.csv")


def normalized(series: pd.Series) -> pd.Series:
    low = series.min()
    high = series.max()
    if high == low:
        return pd.Series(1.0, index=series.index)
    return (series - low) / (high - low)


def main() -> None:
    frame = pd.read_csv(INPUT)
    frame["review_proof"] = normalized(frame["rating_count"].astype(float))
    frame["rating_signal"] = normalized(frame["rating"].astype(float))
    frame["price_accessibility"] = 1 - normalized(frame["displayed_price_usd"].astype(float))
    frame["rank_signal"] = 1 - normalized(frame["bestseller_rank"].astype(float))
    frame["commission_signal"] = normalized(frame["commission_rate_pct"].astype(float))
    frame["conversion_hypothesis_score"] = (
        0.30 * normalized(frame["need_urgency"].astype(float))
        + 0.25 * normalized(frame["audience_fit"].astype(float))
        + 0.15 * frame["price_accessibility"]
        + 0.12 * frame["review_proof"]
        + 0.08 * frame["rating_signal"]
        + 0.05 * frame["rank_signal"]
        + 0.05 * frame["commission_signal"]
        - 0.30 * normalized(frame["claim_or_policy_risk"].astype(float))
    ).clip(lower=0)
    frame["test_priority"] = frame["conversion_hypothesis_score"].rank(
        method="dense", ascending=False
    ).astype(int)
    frame = frame.sort_values(["test_priority", "product"]).reset_index(drop=True)
    frame.to_csv(OUTPUT, index=False)
    print(frame[["test_priority", "product", "conversion_hypothesis_score"]].to_string(index=False))


if __name__ == "__main__":
    main()
