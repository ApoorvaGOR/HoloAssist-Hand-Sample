"""Read the saved Excel file and compare every exported value to its intermediate.

Uses openpyxl for read-only validation, never spreadsheet authoring.
"""
import itertools
import json
import math
from pathlib import Path
import sys
import openpyxl


def same(actual, expected):
    if isinstance(expected, (float, int)):
        return isinstance(actual, (float, int)) and math.isclose(actual, expected, abs_tol=1e-14, rel_tol=1e-14)
    return actual == expected


def main():
    folder = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent/"sample"
    tables = json.loads((folder / "hand_data.json").read_text())
    report = json.loads((folder / "validation.json").read_text())
    # Independently map Excel inputs back to the original tab-separated fields.
    raw_checked = 0
    for side, table in tables.items():
        wanted = {row[0]: row for row in table["rows"]}
        source_path = folder/"raw/Hands"/f"{side}_sync.txt"
        with source_path.open() as source:
            for line in source:
                fields = line.split()
                if not fields or float(fields[0]) not in wanted:
                    continue
                row = wanted.pop(float(fields[0]))
                assert fields[1] == row[1] and int(fields[2]) == row[7]
                for j in range(26):
                    raw = [float(x) for x in fields[3 + 16*j:3 + 16*(j+1)]]
                    expected = [x if math.isfinite(x) else None for x in raw]
                    expected += [expected[3], expected[7], expected[11]]
                    expected += [int(fields[419+j]), int(fields[445+j])]
                    assert all(same(a, b) for a, b in zip(row[8 + 21*j:8 + 21*(j+1)], expected))
                    raw_checked += 21
        assert not wanted, f"{side}: source rows missing"
    book = openpyxl.load_workbook(folder / "hand_tracking.xlsx", read_only=True, data_only=False)
    checked = 0
    for side, table in tables.items():
        expected = [table["header"], *table["rows"]]
        actual = book[f"{side}_hand"].iter_rows(values_only=True)
        for i, pair in enumerate(itertools.zip_longest(actual, expected), 1):
            row, truth = pair
            assert row is not None and truth is not None, (side, "row count")
            assert len(row) == len(truth), (side, i, "column count")
            for j, (a, b) in enumerate(zip(row, truth)):
                assert same(a, b), (side, i, j, a, b)
                checked += 1
    rows = book["Matrix_rows"].iter_rows(values_only=True)
    next(rows)
    count = 0
    for side in ["Left", "Right"]:
        table = tables[side]
        for source in table["rows"]:
            for j in range(26):
                off = 8 + 21*j
                joint = table["header"][off].removesuffix("_M00")
                for r in range(4):
                    expected = [side, source[0], source[1], source[3], joint, r,
                                *source[off + 4*r:off + 4*r + 4], source[7], source[off+19], source[off+20]]
                    actual = next(rows)
                    assert all(same(a, b) for a, b in zip(actual, expected)), (side, j, r)
                    count += 1
                    checked += len(expected)
    assert next(rows, None) is None, "Extra matrix rows"
    book.close()
    result = dict(saved_workbook_values_checked=checked, original_source_values_checked=raw_checked,
                  matrix_rows_checked=count,
                  source_rows_per_hand={side: len(t["rows"]) for side, t in tables.items()},
                  timestamp_text_preserved=True, tolerance="1e-14 absolute/relative for numeric Excel roundtrip")
    (folder / "excel_validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
