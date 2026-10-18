"""Fail closed unless a stable SDK tag matches its single version source."""
import ast
from pathlib import Path
import re
import sys
import tomllib


def validate(tag: str, version: str) -> None:
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise ValueError("Release tag must be vX.Y.Z (stable numeric version)")
    if tag[1:] != version:
        raise ValueError("Tag must match edgespeak._version.__version__")


def check(tag: str, root: Path) -> None:
    package = tomllib.loads((root / "pyproject.toml").read_text())
    if (package["project"]["name"] != "edgespeak"
            or "version" in package["project"]
            or "version" not in package["project"].get("dynamic", [])
            or package["tool"]["setuptools"].get("dynamic", {}).get("version")
            != {"attr": "edgespeak._version.__version__"}):
        raise ValueError("Package must use the single SDK version source")
    tree = ast.parse((root / "src/edgespeak/_version.py").read_text())
    versions = [ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)]
    if len(versions) != 1:
        raise ValueError("Expected one SDK version declaration")
    validate(tag, versions[0])


if __name__ == "__main__":
    check(sys.argv[1], Path(__file__).resolve().parents[2] / "sdk/python")
    print(f"SDK release metadata verified: {sys.argv[1]}")
