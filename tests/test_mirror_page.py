"""
Tests for mirror_page.py

Run with: pytest tests/test_mirror_page.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mirror_page import (
    MirrorError,
    create_session,
    validate_url,
    extract_resources,
    download_resource,
    mirror_page,
)


class TestValidateUrl:
    """Test URL validation logic."""

    def test_valid_http_url(self):
        """Should accept valid HTTP URLs."""
        assert validate_url("https://example.com") == "https://example.com"
        assert validate_url("http://test.org/page.html") == "http://test.org/page.html"

    def test_valid_file_url(self):
        """Should accept valid file:// URLs."""
        assert validate_url("file:///tmp/test.html") == "file:///tmp/test.html"

    def test_missing_protocol(self):
        """Should add https:// when protocol is missing."""
        assert validate_url("example.com") == "https://example.com"

    def test_empty_url(self):
        """Should raise error for empty URL."""
        with pytest.raises(MirrorError, match="cannot be empty"):
            validate_url("")

    def test_invalid_format(self):
        """Should raise error for malformed URLs."""
        # Test with unsupported protocol
        with pytest.raises(MirrorError, match="Invalid URL format"):
            validate_url("ftp://example.com")

    def test_http_url(self):
        """Should accept valid HTTP URLs."""
        assert validate_url("http://example.com") == "http://example.com"


class TestExtractResources:
    """Test resource extraction from HTML."""

    def test_extract_href(self):
        """Should extract href attributes."""
        html = '<a href="page2.html">Link</a>'
        resources = extract_resources(html, "http://example.com/")
        assert "http://example.com/page2.html" in resources

    def test_extract_src(self):
        """Should extract src attributes."""
        html = '<img src="image.png">'
        resources = extract_resources(html, "http://example.com/")
        assert "http://example.com/image.png" in resources

    def test_relative_urls(self):
        """Should resolve relative URLs."""
        html = '<a href="../page.html">Up</a>'
        resources = extract_resources(html, "http://example.com/dir/")
        assert "http://example.com/page.html" in resources

    def test_duplicate_handling(self):
        """Should return unique resources only."""
        html = '<a href="page.html"><a href="page.html">'
        resources = extract_resources(html, "http://example.com/")
        assert len(resources) == 1


class TestCreateSession:
    """Test session creation."""

    def test_session_created(self):
        """Should return a valid requests.Session."""
        session = create_session()
        assert session is not None
        assert hasattr(session, "headers")

    def test_referer_included(self):
        """Should include referer in session headers."""
        session = create_session("http://example.com")
        assert "Referer" in session.headers
        assert session.headers["Referer"] == "http://example.com"

    def test_default_user_agent(self):
        """Should set a default User-Agent."""
        session = create_session()
        assert "User-Agent" in session.headers


class TestDownloadResource:
    """Test resource download logic."""

    @pytest.fixture
    def setup_test_files(self, tmp_path):
        """Create test files for download testing."""
        # Create source file
        source_file = tmp_path / "source.html"
        source_file.write_text("<html><a href='link.html'>Test</a></html>")

        # Create linked file
        link_file = tmp_path / "link.html"
        link_file.write_text("<html></html>")

        return tmp_path

    def test_download_exists(self, setup_test_files):
        """Should download file that exists."""
        tmp_path = setup_test_files
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Use file:// URL for local file
        file_url = f"file://{tmp_path / 'source.html'}"
        seen = set()
        result = download_resource(
            None,
            file_url,
            output_dir,
            seen,
            depth=1,
            max_depth=1,
        )

        assert result is True
        assert (output_dir / "source.html").exists()

    def test_skip_existing(self, setup_test_files):
        """Should skip files that already exist."""
        tmp_path = setup_test_files
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Pre-create the file
        (output_dir / "source.html").write_text("<html></html>")

        seen = set()
        result = download_resource(
            None,
            str(tmp_path / "source.html"),
            output_dir,
            seen,
            depth=1,
            max_depth=1,
        )

        assert result is False

    def test_depth_limit(self, setup_test_files):
        """Should skip resources beyond max depth."""
        tmp_path = setup_test_files
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        seen = set()
        result = download_resource(
            None,
            str(tmp_path / "source.html"),
            output_dir,
            seen,
            depth=2,  # Exceeds max_depth
            max_depth=1,
        )

        assert result is False


class TestMirrorPage:
    """Test the main mirror_page function."""

    @pytest.fixture
    def setup_test_page(self, tmp_path):
        """Create a test HTML page with linked resources."""
        # Main page
        main_page = tmp_path / "main.html"
        main_page.write_text(
            '<html><a href="page2.html">Page 2</a><img src="image.png"></html>'
        )

        # Linked page
        page2 = tmp_path / "page2.html"
        page2.write_text("<html></html>")

        # Image file
        image = tmp_path / "image.png"
        image.write_bytes(b"\x89PNG")  # Minimal PNG header

        return tmp_path

    def test_mirror_file_url(self, setup_test_page):
        """Should mirror a local file and its resources."""
        tmp_path = setup_test_page
        output_dir = tmp_path / "mirror_output"

        # Use file:// URL
        file_url = f"file://{tmp_path / 'main.html'}"
        mirror_page(
            file_url,
            str(output_dir),
            depth=1,
        )

        # Main page is the source, not a resource to download
        assert (output_dir / "page2.html").exists()
        assert (output_dir / "image.png").exists()

    def test_mirror_handles_errors(self, tmp_path):
        """Should handle invalid URLs gracefully."""
        output_dir = tmp_path / "output"

        # Test with a non-existent file URL
        with pytest.raises(SystemExit):
            mirror_page(
                f"file://{tmp_path / 'nonexistent.html'}",
                str(output_dir),
                depth=1,
            )
