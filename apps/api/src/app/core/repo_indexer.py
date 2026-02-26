"""Repository indexing service.

Provides functionality to analyze and index repository structure,
generating summaries useful for LLM context and codebase exploration.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_IGNORE = {
    ".git",
    ".venv",
    ".idea",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".claude",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".coverage",
    "htmlcov",
    ".tox",
    "egg-info",
    ".eggs",
}


@dataclass
class RepoIndexRequest:
    """Request for repository indexing.

    Attributes:
        repo_path: Path to the repository to index
        mode: Indexing mode - "full" (deep), "update" (medium), or "quick" (shallow)
        include_docs: Whether to include documentation files
        include_tests: Whether to include test directories
        max_entries: Maximum number of top-level entries to include
        output_dir: Optional directory to write output files
    """

    repo_path: str
    mode: str = "full"  # full | update | quick
    include_docs: bool = True
    include_tests: bool = True
    max_entries: int = 10
    output_dir: Optional[str] = None


@dataclass
class RepoIndexResponse:
    """Response containing repository index data.

    Attributes:
        markdown: Human-readable markdown summary
        data: Structured data dictionary
        stats: Repository statistics
        output_paths: Paths to written output files (if any)
    """

    markdown: str
    data: Dict[str, Any]
    stats: Dict[str, Any]
    output_paths: List[Path] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "markdown": self.markdown,
            "data": self.data,
            "stats": self.stats,
            "output_paths": [str(p) for p in self.output_paths],
        }


def generate_repo_index(request: RepoIndexRequest) -> RepoIndexResponse:
    """Generate a repository index.

    Args:
        request: RepoIndexRequest specifying what to index

    Returns:
        RepoIndexResponse with markdown summary and structured data

    Raises:
        FileNotFoundError: If the repository path does not exist
    """
    root = Path(request.repo_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")

    files = _collect_files(root, request.mode)
    stats = {
        "repo": str(root),
        "total_files": len(files),
        "mode": request.mode,
    }

    categories = _summarize_categories(root, request)
    entry_points = _find_entry_points(root)
    docs = _find_docs(root) if request.include_docs else []
    tests = _find_tests(root) if request.include_tests else []
    configs = _find_configs(root)

    data = {
        "metadata": stats,
        "structure": categories,
        "entry_points": entry_points,
        "documentation": docs,
        "configuration": configs,
        "tests": tests,
    }

    markdown = _render_markdown(root.name, stats, data)
    outputs: List[Path] = []

    if request.output_dir:
        out_dir = Path(request.output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / "PROJECT_INDEX.md"
        json_path = out_dir / "PROJECT_INDEX.json"
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        outputs.extend([md_path, json_path])

    return RepoIndexResponse(
        markdown=markdown, data=data, stats=stats, output_paths=outputs
    )


def _collect_files(root: Path, mode: str) -> List[Path]:
    """Collect files from repository up to specified depth.

    Args:
        root: Repository root path
        mode: Indexing mode determining depth

    Returns:
        List of file paths
    """
    files: List[Path] = []
    max_depth = {"full": 6, "update": 4, "quick": 2}.get(mode, 6)

    for dirpath, dirnames, filenames in os.walk(root):
        depth = Path(dirpath).relative_to(root).parts
        if len(depth) > max_depth:
            dirnames[:] = []
            continue

        dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE]
        for filename in filenames:
            files.append(Path(dirpath) / filename)

    return files


def _summarize_categories(
    root: Path, request: RepoIndexRequest
) -> List[Dict[str, Any]]:
    """Summarize top-level categories in the repository.

    Args:
        root: Repository root path
        request: Request with max_entries limit

    Returns:
        List of category summaries
    """
    categories = []
    for child in sorted(root.iterdir()):
        if child.name in DEFAULT_IGNORE:
            continue
        if child.name.startswith("."):
            continue
        if child.is_dir():
            categories.append(
                {
                    "path": str(child.relative_to(root)),
                    "type": "dir",
                    "file_count": sum(1 for _ in child.rglob("*") if _.is_file()),
                }
            )
        else:
            categories.append(
                {
                    "path": str(child.relative_to(root)),
                    "type": "file",
                    "size": child.stat().st_size,
                }
            )
        if len(categories) >= request.max_entries:
            break
    return categories


def _find_entry_points(root: Path) -> List[Dict[str, str]]:
    """Find common entry point files.

    Args:
        root: Repository root path

    Returns:
        List of entry point descriptions
    """
    patterns = [
        "main.py",
        "cli.py",
        "__main__.py",
        "manage.py",
        "index.ts",
        "index.js",
        "app.py",
        "server.py",
    ]
    entries: List[Dict[str, str]] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            # Skip files in ignored directories
            if any(part in DEFAULT_IGNORE for part in path.parts):
                continue
            entries.append(
                {
                    "file": str(path.relative_to(root)),
                    "hint": _describe_entry(path),
                }
            )
    return entries


def _describe_entry(path: Path) -> str:
    """Describe an entry point file.

    Args:
        path: Path to the entry point

    Returns:
        Human-readable description
    """
    name = path.name
    if name == "main.py":
        return "Python main entry"
    if name == "cli.py":
        return "CLI entry"
    if name == "__main__.py":
        return "Package entry"
    if name == "manage.py":
        return "Django management"
    if name == "app.py":
        return "Application entry"
    if name == "server.py":
        return "Server entry"
    if name.endswith(".ts"):
        return "TypeScript entry"
    if name.endswith(".js"):
        return "JavaScript entry"
    return "Entry point candidate"


def _find_docs(root: Path) -> List[str]:
    """Find documentation files.

    Args:
        root: Repository root path

    Returns:
        List of documentation file paths
    """
    docs = []
    for name in ["README.md", "CLAUDE.md", "CONTRIBUTING.md", "CHANGELOG.md"]:
        for path in root.glob(name):
            docs.append(str(path.relative_to(root)))
    for path in root.glob("docs/**/*.md"):
        docs.append(str(path.relative_to(root)))
    return sorted(set(docs))


def _find_tests(root: Path) -> List[str]:
    """Find test directories and files.

    Args:
        root: Repository root path

    Returns:
        List of test paths
    """
    tests = []
    for path in root.rglob("tests"):
        if path.is_dir():
            # Skip tests in ignored directories
            if any(part in DEFAULT_IGNORE for part in path.parts):
                continue
            tests.append(str(path.relative_to(root)))
    for file in root.rglob("test_*.py"):
        if any(part in DEFAULT_IGNORE for part in file.parts):
            continue
        tests.append(str(file.relative_to(root)))
    return sorted(set(tests))


def _find_configs(root: Path) -> List[str]:
    """Find configuration files.

    Args:
        root: Repository root path

    Returns:
        List of configuration file paths
    """
    configs = []
    for pattern in [
        "*.toml",
        "*.yaml",
        "*.yml",
        "*.json",
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
        "Taskfile.yml",
    ]:
        for path in root.glob(pattern):
            configs.append(str(path.relative_to(root)))
    for path in root.rglob("pyproject.toml"):
        if any(part in DEFAULT_IGNORE for part in path.parts):
            continue
        configs.append(str(path.relative_to(root)))
    return sorted(set(configs))


def _render_markdown(
    repo_name: str, stats: Dict[str, Any], data: Dict[str, Any]
) -> str:
    """Render repository index as markdown.

    Args:
        repo_name: Name of the repository
        stats: Repository statistics
        data: Structured index data

    Returns:
        Markdown formatted string
    """
    lines = [
        f"# Project Index: {repo_name}",
        "",
        f"- Total files: {stats['total_files']}",
        f"- Mode: {stats['mode']}",
        "",
        "## Structure Snapshot",
    ]
    for item in data["structure"]:
        if item["type"] == "dir":
            lines.append(f"- `{item['path']}/` ({item['file_count']} files)")
        else:
            lines.append(f"- `{item['path']}` ({item['size']} bytes)")

    lines.extend(["", "## Entry Points"])
    if data["entry_points"]:
        for entry in data["entry_points"]:
            lines.append(f"- `{entry['file']}` - {entry['hint']}")
    else:
        lines.append("- No standard entry points found")

    if docs := data["documentation"]:
        lines.extend(["", "## Documentation"])
        for doc in docs[:15]:
            lines.append(f"- `{doc}`")
        if len(docs) > 15:
            lines.append(f"- ... ({len(docs) - 15} more)")

    if configs := data["configuration"]:
        lines.extend(["", "## Configuration"])
        for cfg in configs[:15]:
            lines.append(f"- `{cfg}`")
        if len(configs) > 15:
            lines.append(f"- ... ({len(configs) - 15} more)")

    if tests := data["tests"]:
        lines.extend(["", "## Tests"])
        for test in tests[:15]:
            lines.append(f"- `{test}`")
        if len(tests) > 15:
            lines.append(f"- ... ({len(tests) - 15} more)")

    lines.append("")
    return "\n".join(lines)


# Global cache for repo indexes (simple in-memory cache)
_repo_index_cache: Dict[str, RepoIndexResponse] = {}


def get_cached_index(repo_path: str) -> Optional[RepoIndexResponse]:
    """Get cached repository index if available.

    Args:
        repo_path: Repository path

    Returns:
        Cached RepoIndexResponse or None
    """
    return _repo_index_cache.get(str(Path(repo_path).resolve()))


def cache_index(repo_path: str, response: RepoIndexResponse) -> None:
    """Cache a repository index.

    Args:
        repo_path: Repository path
        response: Index response to cache
    """
    _repo_index_cache[str(Path(repo_path).resolve())] = response


def clear_cache() -> None:
    """Clear the repository index cache."""
    _repo_index_cache.clear()
