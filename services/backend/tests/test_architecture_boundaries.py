import ast
import re
import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]
SRC_ROOT = BACKEND_ROOT / "src"
CORE_PACKAGES = (
    SRC_ROOT / "tripweave" / "domain",
    SRC_ROOT / "tripweave" / "application",
)
PROVIDER_ALLOWED_ROOTS = (
    SRC_ROOT / "tripweave" / "adapters",
    SRC_ROOT / "tripweave" / "entrypoints",
    BACKEND_ROOT.parent.parent / "deploy",
    BACKEND_ROOT.parent.parent / "infra",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "tripweave.adapters",
    "boto3",
    "botocore",
    "google.cloud",
    "oci",
    "azure",
)
FORBIDDEN_CLOUD_IMPORT_PREFIXES = (
    "boto3",
    "botocore",
    "google.cloud",
    "google_cloud",
    "oci",
    "azure",
    "aws",
)
FORBIDDEN_LOCK_PATTERNS = (
    re.compile(r"(?m)^name = \"(?:boto3|botocore|azure-storage[^\" ]*)\"$"),
    re.compile(r"(?m)^name = \"google-cloud[^\" ]*\"$"),
    re.compile(r"/(?:@aws-sdk|aws-sdk|google-cloud|azure-storage)[/@:]"),
    re.compile(r"^\s{2,}(?:@aws-sdk/|aws-sdk:|google-cloud|azure-storage)", re.MULTILINE),
)
PROVIDER_CONTRACT_TERMS = (
    "bucket",
    "namespace",
    "presigned",
    "signed_url",
    "signedUrl",
    "parUrl",
    "par_url",
    "oci",
    "s3",
    "gcs",
    "aws",
    "google_cloud",
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


def test_no_unapproved_cloud_sdk_dependency_appears_in_project_files() -> None:
    checked_files = [
        BACKEND_ROOT / "pyproject.toml",
        BACKEND_ROOT / "uv.lock",
        REPO_ROOT / "apps" / "web" / "package.json",
        REPO_ROOT / "pnpm-lock.yaml",
    ]
    violations: list[str] = []
    for path in checked_files:
        if path.exists():
            content = path.read_text(encoding="utf-8").lower()
            violations.extend(
                f"{path.relative_to(REPO_ROOT)} matches {pattern.pattern}"
                for pattern in FORBIDDEN_LOCK_PATTERNS
                if pattern.search(content)
            )

    assert violations == []


def test_oci_sdk_is_confined_to_backend_adapter_dependency_group() -> None:
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_groups = pyproject.get("dependency-groups", {})
    default_dependencies = pyproject.get("project", {}).get("dependencies", [])

    assert not any(str(item).startswith("oci==") for item in default_dependencies)
    assert any(str(item).startswith("oci==") for item in dependency_groups.get("oci", []))


def test_cloud_sdk_imports_are_confined_to_adapter_or_composition_roots() -> None:
    violations: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        is_allowed_root = any(path.is_relative_to(root) for root in PROVIDER_ALLOWED_ROOTS)
        for module in imported_modules(path):
            if module.startswith(FORBIDDEN_CLOUD_IMPORT_PREFIXES) and not is_allowed_root:
                violations.append(f"{path.relative_to(BACKEND_ROOT)} imports {module}")

    assert violations == []


def test_api_schemas_do_not_expose_provider_specific_storage_fields() -> None:
    schema_file = SRC_ROOT / "tripweave" / "entrypoints" / "api" / "schemas.py"
    content = schema_file.read_text(encoding="utf-8")
    violations = [term for term in PROVIDER_CONTRACT_TERMS if term in content]

    assert violations == []


def test_migrations_persist_only_provider_neutral_blob_identity() -> None:
    violations: list[str] = []
    for path in (BACKEND_ROOT / "alembic" / "versions").glob("*.py"):
        content = path.read_text(encoding="utf-8").lower()
        for term in PROVIDER_CONTRACT_TERMS:
            if term.lower() in content:
                violations.append(f"{path.relative_to(BACKEND_ROOT)} contains {term}")

    assert violations == []


def test_publication_manifest_builder_does_not_emit_durable_urls() -> None:
    publication_file = SRC_ROOT / "tripweave" / "adapters" / "publication.py"
    tree = ast.parse(publication_file.read_text(encoding="utf-8"), filename=str(publication_file))
    emitted_url_keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    lowered = key.value.lower()
                    if "url" in lowered:
                        emitted_url_keys.append(key.value)

    assert emitted_url_keys == []
