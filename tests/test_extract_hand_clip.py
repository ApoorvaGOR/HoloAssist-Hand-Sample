"""Focused checks for timestamp precision, matrix orientation, and missing poses."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import extract_hand_clip as e


class ExportChecks(unittest.TestCase):
    def test_real_layout_precision_and_interval(self):
        # Differences of single 100-ns ticks must survive parsing and subtraction.
        origin = 637932482246358268
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Left_sync.txt"
            lines = []
            for i, delta in enumerate([0, 1, 10_000_000]):
                matrix = np.tile(np.eye(4), (26, 1, 1))
                matrix[:, :3, 3] = [0.25, -0.5, 1.5]
                if i == 1:
                    matrix[2] = np.nan
                lines.append("\t".join([str(i / 30), str(origin + delta), "1"] +
                                        [str(x) for x in matrix.flat] + ["1"] * 52))
            path.write_text("\n".join(lines))
            data = e.load_hand(path)
            self.assertEqual(int(data["ticks"][1]) - origin, 1)
            self.assertFalse(e.usable(data)[1, 2])
            e.validate_matrices(data)
            tables = e.export_payload({"Left": data, "Right": data}, origin, 0, 1,
                                      [(0, 0.), (1, 1 / 30), (2, 1.)], Path(directory))
            header, rows = tables["Left"]["header"], tables["Left"]["rows"]
            self.assertEqual(len(rows), 2)  # End time is exclusive.
            self.assertEqual(rows[1][1], str(origin + 1))
            self.assertEqual(rows[1][2], 1e-7)
            for name, expected in [("Palm_x_m", .25), ("Palm_y_m", -.5), ("Palm_z_m", 1.5),
                                   ("Palm_M03", .25), ("Palm_M13", -.5), ("Palm_M23", 1.5)]:
                self.assertEqual(rows[0][header.index(name)], expected)
            self.assertIsNone(rows[1][header.index("ThumbMetacarpal_M00")])
            self.assertEqual(rows[1][0], 1 / 30)
            json.loads((Path(directory) / "hand_data.json").read_text())

    def test_reject_wrong_width(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.txt"
            path.write_text("0 637932482246358268 1 0\n")
            with self.assertRaisesRegex(ValueError, "471"):
                e.load_hand(path)


if __name__ == "__main__":
    unittest.main()
