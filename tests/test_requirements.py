import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class RequirementsTest(unittest.TestCase):
    def test_requirements_is_ascii(self):
        # Windows の pip は requirements.txt を cp932 で読むので、日本語があると止まる
        self.assertTrue((ROOT / "requirements.txt").read_bytes().isascii())


if __name__ == "__main__":
    unittest.main()
