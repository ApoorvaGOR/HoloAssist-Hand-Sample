"""Checks that run using only files committed in this repository."""
import json
from pathlib import Path
import unittest
import numpy as np
from extract_hand_clip import load_hand, JOINTS
import diagnose_hand_signals as diagnostic

ROOT=Path(__file__).resolve().parents[1]


class PublicSampleChecks(unittest.TestCase):
    def test_sample_shape_and_timestamp_text(self):
        data=json.loads((ROOT/"sample/hand_data.json").read_text())
        self.assertEqual(len(JOINTS),26)
        for side in ["Left","Right"]:
            table=data[side]
            self.assertEqual(len(table["header"]),554)
            self.assertEqual(len(table["rows"]),240)
            self.assertTrue(all(isinstance(row[1],str) and len(row[1])==18 for row in table["rows"]))
            raw=load_hand(ROOT/"sample/raw/Hands"/f"{side}_sync.txt")
            self.assertEqual(raw["matrix"].shape,(240,26,4,4))
            self.assertEqual([str(x) for x in raw["ticks"]],[row[1] for row in table["rows"]])

    def test_excerpt_camera_transform_retains_known_anomaly(self):
        _,signals,separation,info=diagnostic.load()
        self.assertEqual(info["Right"]["behind_camera_tracked_wrist_samples"],2)
        self.assertEqual(info["Left"]["behind_camera_tracked_wrist_samples"],0)
        np.testing.assert_allclose(diagnostic.AXIS.T@diagnostic.AXIS,np.eye(3))
        expected=np.linalg.norm(signals["Left"]["camera_xyz"][:,1]-signals["Right"]["camera_xyz"][:,1],axis=1)*100
        finite=np.isfinite(separation)
        # Original camera rotations are recorded with finite precision and are
        # not perfectly orthogonal. Allow micrometre-scale distance differences.
        np.testing.assert_allclose(expected[finite],separation[finite],rtol=1e-5,atol=1e-4)


if __name__=="__main__":unittest.main()
