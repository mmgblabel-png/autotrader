import json
from pathlib import Path

INPUT = Path("research/roku_content_drafts.json")


def main() -> None:
    rows = json.loads(INPUT.read_text(encoding="utf-8"))
    print(f"artifacts={len(rows)}")
    for row in rows:
        print(
            f"{row['artifact_type']}: {row['status']}, "
            f"policy_allowed={row['policy']['allowed']}, title={row['title']}"
        )


if __name__ == "__main__":
    main()
