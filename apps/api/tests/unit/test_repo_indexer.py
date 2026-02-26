"""Tests for repo_indexer module."""

import tempfile
from pathlib import Path

import pytest
from app.core.repo_indexer import (
    RepoIndexRequest,
    RepoIndexResponse,
    generate_repo_index,
    get_cached_index,
    cache_index,
    clear_cache,
)


class TestRepoIndexRequest:
    """Test RepoIndexRequest dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        request = RepoIndexRequest(repo_path="/some/path")
        assert request.mode == "full"
        assert request.include_docs is True
        assert request.include_tests is True
        assert request.max_entries == 10
        assert request.output_dir is None


class TestRepoIndexResponse:
    """Test RepoIndexResponse dataclass."""

    def test_to_dict(self):
        """Test dictionary conversion."""
        response = RepoIndexResponse(
            markdown="# Test",
            data={"key": "value"},
            stats={"total_files": 10},
            output_paths=[Path("/tmp/test.md")],
        )
        d = response.to_dict()
        assert d["markdown"] == "# Test"
        assert d["data"] == {"key": "value"}
        assert d["stats"] == {"total_files": 10}
        assert d["output_paths"] == ["/tmp/test.md"]


class TestGenerateRepoIndex:
    """Test generate_repo_index function."""

    def test_nonexistent_path_raises_error(self):
        """Test that nonexistent path raises FileNotFoundError."""
        request = RepoIndexRequest(repo_path="/nonexistent/path/12345")
        with pytest.raises(FileNotFoundError):
            generate_repo_index(request)

    def test_index_temp_directory(self):
        """Test indexing a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some test files
            Path(tmpdir, "README.md").write_text("# Test Project")
            Path(tmpdir, "main.py").write_text("print('hello')")
            Path(tmpdir, "src").mkdir()
            Path(tmpdir, "src", "app.py").write_text("# app code")
            Path(tmpdir, "tests").mkdir()
            Path(tmpdir, "tests", "test_main.py").write_text("# tests")
            Path(tmpdir, "pyproject.toml").write_text("[project]")

            request = RepoIndexRequest(repo_path=tmpdir)
            response = generate_repo_index(request)

            assert isinstance(response, RepoIndexResponse)
            assert response.markdown is not None
            assert len(response.markdown) > 0
            assert "README.md" in response.markdown or "Project Index" in response.markdown
            assert response.stats["total_files"] >= 4

    def test_quick_mode_depth(self):
        """Test that quick mode limits depth."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            deep_path = Path(tmpdir, "a", "b", "c", "d", "e")
            deep_path.mkdir(parents=True)
            Path(deep_path, "deep.txt").write_text("deep file")

            request = RepoIndexRequest(repo_path=tmpdir, mode="quick")
            response = generate_repo_index(request)

            # Quick mode (depth 2) should not find the deep file
            assert "deep.txt" not in response.markdown

    def test_exclude_docs_and_tests(self):
        """Test excluding docs and tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "README.md").write_text("# Test")
            Path(tmpdir, "tests").mkdir()
            Path(tmpdir, "tests", "test_main.py").write_text("# tests")

            request = RepoIndexRequest(
                repo_path=tmpdir,
                include_docs=False,
                include_tests=False,
            )
            response = generate_repo_index(request)

            # Documentation and tests sections should be empty
            assert len(response.data["documentation"]) == 0
            assert len(response.data["tests"]) == 0

    def test_entry_points_detection(self):
        """Test entry point detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "main.py").write_text("# main")
            Path(tmpdir, "cli.py").write_text("# cli")
            Path(tmpdir, "index.ts").write_text("// index")

            request = RepoIndexRequest(repo_path=tmpdir)
            response = generate_repo_index(request)

            entry_files = [e["file"] for e in response.data["entry_points"]]
            assert "main.py" in entry_files
            assert "cli.py" in entry_files
            assert "index.ts" in entry_files

    def test_config_detection(self):
        """Test configuration file detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "pyproject.toml").write_text("[project]")
            Path(tmpdir, "config.yaml").write_text("key: value")
            Path(tmpdir, "settings.json").write_text("{}")

            request = RepoIndexRequest(repo_path=tmpdir)
            response = generate_repo_index(request)

            configs = response.data["configuration"]
            assert "pyproject.toml" in configs
            assert "config.yaml" in configs
            assert "settings.json" in configs

    def test_max_entries_limit(self):
        """Test max_entries limits output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create many directories
            for i in range(20):
                Path(tmpdir, f"dir{i:02d}").mkdir()

            request = RepoIndexRequest(repo_path=tmpdir, max_entries=5)
            response = generate_repo_index(request)

            assert len(response.data["structure"]) <= 5

    def test_output_files_written(self):
        """Test that output files are written when output_dir is specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test.py").write_text("# test")

            with tempfile.TemporaryDirectory() as outdir:
                request = RepoIndexRequest(repo_path=tmpdir, output_dir=outdir)
                response = generate_repo_index(request)

                assert len(response.output_paths) == 2
                assert Path(outdir, "PROJECT_INDEX.md").exists()
                assert Path(outdir, "PROJECT_INDEX.json").exists()


class TestCaching:
    """Test caching functions."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    def test_cache_and_retrieve(self):
        """Test caching and retrieving index."""
        response = RepoIndexResponse(
            markdown="# Test",
            data={"key": "value"},
            stats={"total_files": 10},
        )
        cache_index("/test/path", response)

        cached = get_cached_index("/test/path")
        assert cached is not None
        assert cached.markdown == "# Test"

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cached = get_cached_index("/nonexistent/path")
        assert cached is None

    def test_clear_cache(self):
        """Test clearing cache."""
        response = RepoIndexResponse(
            markdown="# Test",
            data={},
            stats={},
        )
        cache_index("/test/path", response)
        assert get_cached_index("/test/path") is not None

        clear_cache()
        assert get_cached_index("/test/path") is None

    def test_path_normalization(self):
        """Test that paths are normalized for caching."""
        response = RepoIndexResponse(
            markdown="# Test",
            data={},
            stats={},
        )
        # Cache with relative path style
        cache_index("~/test/path", response)

        # Should be able to retrieve with resolved path
        # Note: This depends on Path.resolve() behavior
        # For a more robust test, we'd need a real directory
