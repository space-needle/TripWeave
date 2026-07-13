import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BACKEND_ROOT / "src"
CORE_PACKAGES = (
    SRC_ROOT / "tripweave" / "domain",
    SRC_ROOT / "tripweave" / "application",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "tripweave.adapters",
    "boto3",
    "botocore",
    "google.cloud",
    "oci",
    "azure",
)
FORBIDDEN_LOCK_TEXT = (
    "boto3",
    "botocore",
    "google-cloud",
    "oci",
    "azure-storage",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_and_application_do_not_import_adapters_or_cloud_sdks() -> None:
    violations: list[str] = []
    for package in CORE_PACKAGES:
        for path in package.rglob("*.py"):
            for module in imported_modules(path):
                if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(f"{path.relative_to(BACKEND_ROOT)} imports {module}")

    assert violations == []


def test_no_cloud_sdk_dependency_appears_in_project_files() -> None:
    checked_files = [
        BACKEND_ROOT / "pyproject.toml",
        BACKEND_ROOT / "uv.lock",
        BACKEND_ROOT.parents[1] / "apps" / "web" / "package.json",
        BACKEND_ROOT.parents[1] / "apps" / "web" / "pnpm-lock.yaml",
    ]
    violations: list[str] = []
    for path in checked_files:
        if path.exists():
            content = path.read_text(encoding="utf-8").lower()
            violations.extend(
                f"{path.relative_to(BACKEND_ROOT.parents[1])} contains {needle}"
                for needle in FORBIDDEN_LOCK_TEXT
                if needle in content
            )

    assert violations == []
