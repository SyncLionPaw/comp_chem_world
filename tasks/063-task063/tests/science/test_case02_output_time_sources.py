import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

TESTS = Path(__file__).parent
APP = TESTS.parent.parent
sys.path.insert(0, str(TESTS))
from mvp_numeric import CandidateError, _candidate_output_row_key, _candidate_time_matches
from numeric_evidence import _case02_output_time_errors


class Case02OutputTimeSourceTests(unittest.TestCase):
    def setUp(self):
        self.synthetic_allowed = {"140": (2800.0, 2800.000133)}

    def test_descriptor_time_is_allowed(self):
        self.assertTrue(_candidate_time_matches("140", 2800.0, self.synthetic_allowed))

    def test_joined_native_time_is_allowed(self):
        self.assertTrue(_candidate_time_matches("140", 2800.000133, self.synthetic_allowed))

    def test_between_sources_is_rejected(self):
        self.assertFalse(_candidate_time_matches("140", 2800.0000665, self.synthetic_allowed))

    def test_arbitrary_time_inside_join_window_is_rejected(self):
        self.assertFalse(_candidate_time_matches("140", 2800.000002, self.synthetic_allowed))

    def test_time_outside_source_tolerance_is_rejected(self):
        self.assertFalse(_candidate_time_matches("140", 2800.001, self.synthetic_allowed))

    def test_duplicate_row_key_is_rejected(self):
        expected = {("140", "a", "node0")}
        seen = set()
        row = {"frame_index": "140", "model_id": "a", "native_column": "node0"}
        _candidate_output_row_key(row, seen, expected)
        with self.assertRaises(CandidateError):
            _candidate_output_row_key(row, seen, expected)

    def test_unknown_source_frame_is_rejected(self):
        with self.assertRaises(CandidateError):
            _candidate_time_matches("141", 2800.0, self.synthetic_allowed)
        with self.assertRaises(CandidateError):
            _candidate_output_row_key({"frame_index": "141", "model_id": "a", "native_column": "node0"}, set(), {("140", "a", "node0")})

    def _write_candidate_rows(self, app, change=None, append_duplicate=False):
        with (app / "environment/assets/g4-descriptors.csv").open(newline="", encoding="utf-8") as stream:
            descriptors = list(csv.DictReader(stream))
        with np.load(app / "environment/assets/g4-native-traces.npz", allow_pickle=False) as archive:
            trace_times = np.asarray(archive["time_ps"], dtype=float)
        descriptor_times = np.asarray([float(row["time_ps"]) for row in descriptors])
        nearest = np.searchsorted(trace_times, descriptor_times)
        nearest = np.clip(nearest, 0, len(trace_times) - 1)
        left = np.maximum(nearest - 1, 0)
        nearest = np.where(np.abs(trace_times[left] - descriptor_times) < np.abs(trace_times[nearest] - descriptor_times), left, nearest)
        native_times = trace_times[nearest]
        header = ["frame_index", "time_ps", "model_id", "native_column"]
        rows = []
        columns = ["node0", "node1", "node2", "sw", "swb", "swc"]
        for i, source in enumerate(descriptors):
            frame = source["frame_index"]
            for mi, model in enumerate(("a", "b", "c")):
                for column in columns:
                    source_time = float(source["time_ps"]) if (i + mi) % 2 == 0 else float(native_times[i])
                    rows.append({"frame_index": frame, "time_ps": f"{source_time:.12f}", "model_id": model, "native_column": column})
        if change:
            change(rows, descriptors, native_times)
        if append_duplicate:
            rows.append(rows[0].copy())
        temp = tempfile.TemporaryDirectory()
        payload = Path(temp.name)
        with (payload / "model-output-audit.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)
        return temp, payload

    def test_numeric_evidence_accepts_both_source_times(self):
        temp, payload = self._write_candidate_rows(APP)
        with temp:
            checked = _case02_output_time_errors(APP, payload)
        self.assertEqual(checked["errors"], [])

    def test_numeric_evidence_rejects_intermediate_time(self):
        def change(rows, descriptors, native_times):
            index = next(i for i, row in enumerate(rows) if row["frame_index"] == "140" and row["model_id"] == "a" and row["native_column"] == "node0")
            descriptor_index = next(i for i, row in enumerate(descriptors) if row["frame_index"] == "140")
            rows[index]["time_ps"] = f"{(float(descriptors[descriptor_index]['time_ps']) + float(native_times[descriptor_index])) / 2:.12f}"
        temp, payload = self._write_candidate_rows(APP, change=change)
        with temp:
            checked = _case02_output_time_errors(APP, payload)
        self.assertTrue(any(error.get("field") == "time_ps" for error in checked["errors"]))

    def test_numeric_evidence_rejects_duplicate_row(self):
        temp, payload = self._write_candidate_rows(APP, append_duplicate=True)
        with temp:
            checked = _case02_output_time_errors(APP, payload)
        self.assertTrue(any(error.get("field") == "duplicate_key" for error in checked["errors"]))

    def test_numeric_evidence_rejects_unknown_source_frame(self):
        def change(rows, descriptors, native_times):
            rows[0]["frame_index"] = "999999"
        temp, payload = self._write_candidate_rows(APP, change=change)
        with temp:
            checked = _case02_output_time_errors(APP, payload)
        self.assertTrue(any(error.get("field") == "unknown_source_row" for error in checked["errors"]))


if __name__ == "__main__":
    unittest.main()
