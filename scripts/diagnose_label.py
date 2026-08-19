"""Show why a label will or will not train.

    docker compose exec olim python scripts/diagnose_label.py 1

Prints the label's declared class values next to the values actually annotated, so
a mismatch between the two — the usual cause of "No trainable labeled data" — is
visible at a glance.
"""

import sys
from collections import Counter
from pathlib import Path

# Add project root to path — running `python scripts/x.py` puts scripts/ on
# sys.path, not the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from olim import app
from olim.database import get_label, get_label_entries
from olim.label_types import (
    get_abstain_values,
    get_class_values,
    is_open_label,
    parse_label_value,
)


def main(label_id: int) -> int:
    with app.app_context():
        label = get_label(label_id)
        if label is None:
            print(f"label {label_id} not found")
            return 1

        entries = get_label_entries(label.id)
        raw = Counter(e.value for e in entries)
        observed = Counter(v for e in entries for v in parse_label_value(e.value))
        declared = get_class_values(label)

        print(f"label {label.id}: {label.name!r}")
        print(f"  label_type      : {label.label_type!r}")
        print(f"  open type       : {is_open_label(label.label_type)}")
        print(f"  label_settings  : {label.label_settings}")
        print(f"  declared classes: {declared}")
        print(f"  abstain values  : {sorted(get_abstain_values(label.label_type, label))}")
        print(f"  annotations     : {len(entries)}")
        print("  raw stored values:")
        for value, count in raw.most_common():
            print(f"      {count:6d}  {value!r}")
        print("  decoded classes  :")
        for value, count in observed.most_common():
            mark = "ok " if value in declared else "NOT DECLARED"
            print(f"      {count:6d}  {value!r:20s} {mark}")

        trainable = sum(
            1
            for e in entries
            if len(parse_label_value(e.value)) == 1 and parse_label_value(e.value)[0] in declared
        )
        print(f"  trainable       : {trainable}/{len(entries)}")
        if not trainable:
            print("\n  -> nothing will train. The annotated values are not the ones the")
            print("     label declares; fix the label's type or its configured options.")
        return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
