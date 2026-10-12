"""Fail closed unless a stable SDK tag matches all package version surfaces."""
import ast
from pathlib import Path
import re
import sys
import tomllib


def validate(tag: str, package_version: str, runtime_version: str, user_agent: str) -> None:
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise ValueError("Release tag must be vX.Y.Z (stable numeric version)")
    version = tag[1:]
    if (package_version, runtime_version, user_agent) != (
        version, version, f"edgespeak-python/{version}"
    ):
        raise ValueError("Tag, pyproject.toml, __version__, and User-Agent must agree")


def check(tag: str, root: Path) -> None:
    package = tomllib.loads((root / "pyproject.toml").read_text())
    init = ast.parse((root / "src/edgespeak/__init__.py").read_text())
    versions = [ast.literal_eval(node.value) for node in init.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)]
    client = ast.parse((root / "src/edgespeak/_client.py").read_text())
    agents = [node.value for node in ast.walk(client)
              if isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node.value.startswith("edgespeak-python/")]
    if package["project"]["name"] != "edgespeak" or len(versions) != 1 or len(agents) != 1:
        raise ValueError("Unexpected SDK package metadata or version declarations")
    validate(tag, package["project"]["version"], versions[0], agents[0])


if __name__ == "__main__":
    check(sys.argv[1], Path(__file__).resolve().parents[2] / "sdk/python")
    print(f"SDK release metadata verified: {sys.argv[1]}")
