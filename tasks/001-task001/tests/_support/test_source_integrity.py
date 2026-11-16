"""Input integrity remains enforced without a private source manifest."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS / "_support"))
from case01_source_facts import SourceError, build_source_facts


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.refs = json.loads((TESTS / "refs.json").read_text())
        self.assets = TESTS.parent / "environment/assets"

    def test_sources_parse_without_private_manifest(self):
        facts = build_source_facts(self.assets, self.refs)
        self.assertEqual(facts["source_asset_count"], 18)
        self.assertEqual(len(facts["gaussian"]), 8)
        self.assertEqual(len(facts["goodvibes"]), 8)

    def test_wrong_pinned_hash_is_rejected(self):
        refs = copy.deepcopy(self.refs)
        refs["asset_hashes"]["assets/public-context.json"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(SourceError, "digest mismatch"):
            build_source_facts(self.assets, refs)

    def test_incomplete_inventory_is_rejected(self):
        self.refs["asset_hashes"].pop("assets/public-context.json")
        with self.assertRaisesRegex(SourceError, "exactly 18"):
            build_source_facts(self.assets, self.refs)

    def test_missing_and_modified_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder) / "assets"
            shutil.copytree(self.assets, assets)
            context = assets / "public-context.json"
            original = context.read_bytes()
            context.unlink()
            with self.assertRaisesRegex(SourceError, "missing/unsafe"):
                build_source_facts(assets, self.refs)
            context.write_bytes(original + b"\n")
            with self.assertRaisesRegex(SourceError, "digest mismatch"):
                build_source_facts(assets, self.refs)


if __name__ == "__main__":
    unittest.main()
