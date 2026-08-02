"""
Tests for mirror_page.py

Run with: pytest tests/test_mirror_page.py -v
"""

import pytest
from pathlib import Path

from mirror_page import (
    MirrorError,
    _safe_filename,
    _safe_path,
    create_session,
    validate_url,
    extract_resources,
    extract_css_dependencies,
    download_resource,
    mirror_page,
    parse_args,
    write_resource,
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

    def test_single_page_keeps_dependencies(self):
        """Single-page mode should keep scripts, styles, and images."""
        html = (
            '<link rel="stylesheet" href="style.css">'
            '<script src="app.js"></script><img src="img.png">'
        )
        resources = extract_resources(
            html, "http://example.com/", single_page=True
        )
        assert "http://example.com/style.css" in resources
        assert "http://example.com/app.js" in resources
        assert "http://example.com/img.png" in resources

    def test_single_page_skips_linked_html(self):
        """Single-page mode should drop links to other web pages."""
        html = '<a href="page2.html">Page 2</a><a href="/about">About</a>'
        resources = extract_resources(
            html, "http://example.com/", single_page=True
        )
        assert resources == []

    def test_single_page_keeps_iframe_includes(self):
        """Single-page mode should keep embedded HTML includes."""
        html = '<iframe src="frame.html"></iframe>'
        resources = extract_resources(
            html, "http://example.com/", single_page=True
        )
        assert "http://example.com/frame.html" in resources

    def test_single_page_skips_extensionless_links(self):
        """Single-page mode should treat extensionless paths as pages."""
        html = '<a href="/products">Product</a><link href="/team/">Team</a>'
        resources = extract_resources(
            html, "http://example.com/", single_page=True
        )
        assert resources == []


class TestExtractCssDependencies:
    """Test CSS url(...) and @import extraction."""

    def test_url_background_image(self):
        """Should extract url(...) references."""
        css = ".bg { background-image: url(images/bg.png); }"
        deps = extract_css_dependencies(css, "http://example.com/css/style.css")
        assert deps == ["http://example.com/css/images/bg.png"]

    def test_quoted_and_unquoted_urls(self):
        """Should handle both quoted and unquoted url() values."""
        css = """
        .a { background: url('a.png'); }
        .b { background: url(b.png); }
        """
        deps = extract_css_dependencies(css, "http://example.com/")
        assert "http://example.com/a.png" in deps
        assert "http://example.com/b.png" in deps

    def test_skips_data_uris(self):
        """Should skip data: URIs."""
        css = ".x { background: url(data:image/png;base64,AAAA); }"
        deps = extract_css_dependencies(css, "http://example.com/")
        assert deps == []

    def test_import_nested_stylesheet(self):
        """Should extract @import stylesheets."""
        css = "@import url(other.css);"
        deps = extract_css_dependencies(css, "http://example.com/css/main.css")
        assert deps == ["http://example.com/css/other.css"]


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

    def test_verify_true_by_default(self):
        """Should verify TLS certificates by default."""
        session = create_session()
        assert session.verify is True

    def test_verify_false_disables_verification(self):
        """Should disable TLS verification when verify=False."""
        session = create_session(verify=False)
        assert session.verify is False


class TestParseArgs:
    """Test command-line argument parsing."""

    def test_verify_default_true(self):
        """Should default to verifying TLS certificates."""
        args = parse_args(["https://example.com", "./out"])
        assert args.verify is True

    def test_no_verify_flag(self):
        """Should honour the --no-verify flag."""
        args = parse_args(["https://example.com", "./out", "--no-verify"])
        assert args.verify is False

    def test_referer_and_depth_preserved(self):
        """Should not disturb existing options."""
        args = parse_args(
            ["https://example.com", "./out", "-r", "http://ref", "-d", "3"]
        )
        assert args.referer == "http://ref"
        assert args.depth == 3

    def test_single_page_default_false(self):
        """Should default single_page to False."""
        args = parse_args(["https://example.com", "./out"])
        assert args.single_page is False

    def test_single_page_flag(self):
        """Should honour the --single-page flag."""
        args = parse_args(["https://example.com", "./out", "--single-page"])
        assert args.single_page is True


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

    def test_mirror_http_connection_error_exits_gracefully(self, tmp_path):
        """Should exit cleanly with an error message on connection failure."""
        output_dir = tmp_path / "output"
        # Port 1 is closed in all practical environments, so connection is refused.
        with pytest.raises(SystemExit):
            mirror_page("http://127.0.0.1:1/page.html", str(output_dir), depth=1)

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

        # The main page itself is now saved into the output directory.
        assert (output_dir / "main.html").exists()
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

    def test_mirror_single_page_skips_linked_html(self, tmp_path):
        """Single-page mode should skip linked pages but keep assets."""
        # Main page links a second page and an image.
        main = tmp_path / "main.html"
        main.write_text(
            '<html><a href="page2.html">P2</a><img src="image.png">'
            '<script src="app.js"></script></html>'
        )
        (tmp_path / "page2.html").write_text("<html></html>")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "app.js").write_text("console.log('hi')")

        output_dir = tmp_path / "mirror_output"
        mirror_page(
            f"file://{main}",
            str(output_dir),
            depth=1,
            single_page=True,
        )

        # The linked HTML page is not downloaded.
        assert (output_dir / "main.html").exists()
        assert (output_dir / "image.png").exists()
        assert (output_dir / "app.js").exists()
        assert not (output_dir / "page2.html").exists()

    def test_mirror_single_page_downloads_css_assets(self, tmp_path):
        """Single-page mode should download images referenced from CSS."""
        # Main page links only a stylesheet; the stylesheet references images.
        main = tmp_path / "main.html"
        main.write_text('<html><link rel="stylesheet" href="style.css"></html>')
        (tmp_path / "style.css").write_text(
            '.bg { background-image: url(images/bg.png); }'
            '@import url(extra.css);'
        )
        (tmp_path / "extra.css").write_text(
            '.x { background: url(img/icon.gif); }'
        )
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "bg.png").write_bytes(b"\x89PNG")
        nested_img = tmp_path / "img"
        nested_img.mkdir()
        (nested_img / "icon.gif").write_bytes(b"GIF")

        output_dir = tmp_path / "mirror_output"
        mirror_page(
            f"file://{main}",
            str(output_dir),
            depth=1,
            single_page=True,
        )

        assert (output_dir / "main.html").exists()
        assert (output_dir / "style.css").exists()
        assert (output_dir / "extra.css").exists()
        assert (output_dir / "bg.png").exists()
        assert (output_dir / "icon.gif").exists()


class TestSafeFilename:
    """Test safe filename derivation."""

    def test_plain_filename(self):
        """Should keep a simple filename."""
        assert _safe_filename("http://example.com/style.css") == "style.css"

    def test_subdirectory_filename(self):
        """Should keep the basename when resource is nested."""
        assert _safe_filename("http://example.com/assets/css/style.css") == "style.css"

    def test_query_string_stripped(self):
        """Should strip query strings from filenames."""
        assert _safe_filename("http://example.com/image.png?v=2") == "image.png"

    def test_url_encoded_characters(self):
        """Should URL-decode the resource path before sanitizing."""
        # Spaces are decoded then replaced with underscores for safety.
        assert _safe_filename("http://example.com/my%20file.txt") == "my_file.txt"

    def test_no_path_uses_index(self):
        """Should fall back to a sane name when there is no path."""
        assert _safe_filename("http://example.com") == "index"


class TestSafePath:
    """Test subdirectory-preserving relative path derivation."""

    def test_flat_path(self):
        """Should keep a simple single-file path."""
        assert _safe_path("http://example.com/style.css") == Path("style.css")

    def test_preserves_subdirectories(self):
        """Should reproduce the URL's subdirectory layout."""
        assert _safe_path("http://example.com/assets/css/style.css") == Path(
            "assets/css/style.css"
        )

    def test_file_url_uses_basename(self):
        """Should collapse file:// absolute paths to a basename."""
        assert _safe_path("file:///tmp/site/css/style.css") == Path("style.css")

    def test_directory_url_gets_index(self):
        """Should append an index page for directory-style URLs."""
        assert _safe_path("http://example.com/foo/bar/") == Path("foo/bar/index")

    def test_query_string_stripped(self):
        """Should strip query strings from the path."""
        assert _safe_path("http://example.com/img/banner.png?v=2") == Path(
            "img/banner.png"
        )


class TestWriteResource:
    """Test collision-safe writing."""

    def test_writes_content(self, tmp_path):
        """Should write bytes to the output directory."""
        result = write_resource(tmp_path, "http://example.com/a.txt", "a.txt", b"hello")
        assert result is True
        assert (tmp_path / "a.txt").read_bytes() == b"hello"

    def test_name_collision_suffix(self, tmp_path):
        """Should append a numeric suffix on name collisions."""
        (tmp_path / "a.txt").write_bytes(b"original")
        result = write_resource(tmp_path, "http://example.com/b/a.txt", "a.txt", b"new")
        assert result is True
        # Both files are preserved.
        assert (tmp_path / "a.txt").read_bytes() == b"original"
        assert (tmp_path / "a_1.txt").read_bytes() == b"new"
