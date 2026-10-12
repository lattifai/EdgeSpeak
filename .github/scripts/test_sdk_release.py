import unittest
from check_sdk_release import validate


class ReleaseGuardTests(unittest.TestCase):
    def test_stable_versions(self):
        for version in ("0.1.0", "1.2.3", "10.20.30"):
            validate(f"v{version}", version, version, f"edgespeak-python/{version}")

    def test_rejects_non_release_tags(self):
        for tag in ("v0.1.0a1", "v1.2.3-rc1", "1.2.3", "v01.2.3", "v1.2.3.4", "v1.2.3\n", "v1.2.*"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validate(tag, "1.2.3", "1.2.3", "edgespeak-python/1.2.3")

    def test_each_version_must_match(self):
        expected = ["1.2.3", "1.2.3", "edgespeak-python/1.2.3"]
        for index in range(3):
            values = expected.copy()
            values[index] = "0.1.0a1"
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate("v1.2.3", *values)


if __name__ == "__main__":
    unittest.main()
