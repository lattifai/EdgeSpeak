"""Run all SDK tests by default, or an explicit CI unit/integration suite."""
import argparse
from pathlib import Path
import sys
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "unit", "integration"), default="all")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    sys.path.insert(0, str(directory))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path in sorted(directory.glob("test_*.py")):
        integration = path.stem.endswith("_integration")
        if args.suite == "unit" and integration or args.suite == "integration" and not integration:
            continue
        suite.addTests(loader.loadTestsFromName(path.stem))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
