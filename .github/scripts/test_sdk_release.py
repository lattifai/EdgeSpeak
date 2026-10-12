from pathlib import Path
import tempfile
import unittest
from check_sdk_release import check, validate


class ReleaseGuardTests(unittest.TestCase):
    def test_single_source_configuration_and_tag_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/edgespeak").mkdir(parents=True)
            metadata = '[project]\nname = "edgespeak"\ndynamic = ["version"]\n[tool.setuptools.dynamic]\nversion = {attr = "edgespeak._version.__version__"}\n'
            (root / "pyproject.toml").write_text(metadata)
            source = root / "src/edgespeak/_version.py"
            source.write_text('__version__ = "1.2.3"\n')
            check("v1.2.3", root)
            source.write_text('__version__ = "1.2.4"\n')
            with self.assertRaises(ValueError):
                check("v1.2.3", root)
            check("v1.2.4", root)
            (root / "pyproject.toml").write_text(metadata.replace('dynamic = ["version"]', 'version = "1.2.4"'))
            with self.assertRaises(ValueError):
                check("v1.2.4", root)

    def test_stable_versions(self):
        for version in ("0.1.0", "1.2.3", "10.20.30"):
            validate(f"v{version}", version)

    def test_rejects_non_release_tags(self):
        for tag in ("v0.1.0a1", "v1.2.3-rc1", "1.2.3", "v01.2.3", "v1.2.3.4", "v1.2.3\n", "v1.2.*"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validate(tag, "1.2.3")

    def test_rejects_mismatched_version(self):
        with self.assertRaises(ValueError):
            validate("v1.2.3", "1.2.4")


if __name__ == "__main__":
    unittest.main()
