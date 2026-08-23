#!/usr/bin/env python3
"""
Mirror a web page and all its resources to a local directory.

This script downloads an HTML page and extracts all linked resources
(scripts, stylesheets, images, etc.), saving them to a local directory
with preserved relative paths.

Usage:
    python mirror_clone.py <url> <output_dir>

Examples:
    python mirror_clone.py https://example.com ./mirror
    python mirror_clone.py http://test.org/page.html ./output --referer http://test.org
"""

import argparse
import os
import re
import sys
import time
import warnings
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import unquote, urljoin, urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 30


class MirrorError(Exception):
    """Custom exception for mirror_clone errors."""

    pass


def create_session(
    referer: Optional[str] = None, verify: bool = True
) -> requests.Session:
    """
    Create a requests.Session with connection pooling and retry logic.

    Args:
        referer: Optional referer header to include in requests.
        verify: Whether to verify TLS certificates. Set to False to disable
            certificate verification (e.g. for self-signed certs).

    Returns:
        Configured requests.Session instance.
    """
    session = requests.Session()

    # Certificate verification applies to all HTTPS requests on this session.
    session.verify = verify
    if not verify:
        warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

    # Configure retry strategy for transient failures
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Set default headers
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    if referer:
        session.headers["Referer"] = referer

    return session


def validate_url(url: str) -> str:
    """
    Validate and normalize the target URL.

    Args:
        url: The URL to validate.

    Returns:
        Normalized URL string.

    Raises:
        MirrorError: If URL is malformed or invalid.
    """
    if not url:
        raise MirrorError("URL cannot be empty")

    url = url.strip()

    # Strip protocol if missing
    if not urlparse(url).scheme:
        url = "https://" + url

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "file"):
        raise MirrorError(
            "Invalid URL format: {}. Expected http://, https://, or file://".format(url)
        )

    # A valid URL must have a host (or a path for file:// URLs)
    if not parsed.netloc and not (parsed.scheme == "file" and parsed.path):
        raise MirrorError("Invalid URL format: missing host: {}".format(url))

    return url


def _safe_path(url: str) -> Path:
    """
    Derive a safe relative path that preserves the URL's subdirectory layout.

    Query strings and URL-encoded characters are stripped/decoded and each
    path component is sanitized so resources are written to a mirrored
    directory tree rather than collapsed into a single flat folder.

    Args:
        url: The resource URL.

    Returns:
        A filesystem-safe relative :class:`Path`.
    """
    parsed = urlparse(url)
    path = unquote(parsed.path)

    # For file:// URLs the path is an absolute local filesystem path, so there
    # is no server-relative hierarchy to reproduce; keep just the basename.
    if parsed.scheme == "file":
        name = path.rsplit("/", 1)[-1] if path else ""
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        return Path(name or "resource")

    if not path or path == "/":
        return Path("index")

    raw_parts = path.strip("/").split("/")
    parts = [
        re.sub(r"[^A-Za-z0-9._-]", "_", part) or "resource"
        for part in raw_parts
        if part and part != "."
    ]
    if not parts:
        return Path("index")

    # A trailing slash denotes a directory-style URL; give it an index page.
    if path.endswith("/"):
        parts.append("index")

    return Path(*parts)


def _safe_filename(url: str) -> str:
    """
    Derive a safe, collision-resistant basename from a resource URL.

    Query strings and URL-encoded characters are stripped and decoded so
    that resources in different directories keep distinct names.

    Args:
        url: The resource URL.

    Returns:
        A filesystem-safe basename.
    """
    return _safe_path(url).name


def write_resource(output_dir: Path, url: str, filename: str, content: bytes) -> bool:
    """
    Write downloaded bytes to disk, avoiding filename collisions.

    If a file with the target name already exists, a numeric suffix is
    appended so resources from different directories are not lost.

    Args:
        output_dir: Directory in which to save the file.
        url: Origin URL (used for logging and collision messaging).
        filename: Proposed filename, possibly a relative Path with subdirectories.
        content: Raw bytes to write.

    Returns:
        True if the file was written, False if it already existed and was skipped.
    """
    output_dir = Path(output_dir)
    filename = Path(filename)
    filepath = output_dir / filename

    if filepath.exists():
        # Avoid overwriting: derive a unique name within the same subdirectory.
        stem, dot, ext = filename.name.rpartition(".")
        suffix = 1
        while filepath.exists():
            if dot:
                candidate = filepath.parent / "{}_{}{}{}".format(stem, suffix, dot, ext)
            else:
                candidate = filepath.parent / "{}_{}".format(filename.name, suffix)
            filepath = candidate
            suffix += 1
        print("Name collision, saving as {}: {}".format(filepath.name, url))

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(content)
    return True


# Extensions identifying assets that are dependencies of one page rather than
# standalone linked web pages. In single-page mode these are downloaded,
# user-clickable HTML links are not.
STYLE_SUFFIXES = (".css", ".js", ".mjs", ".map")
IMAGE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".avif", ".tiff", ".jfif",
)
FONT_SUFFIXES = (".woff", ".woff2", ".ttf", ".otf", ".eot")
DOCUMENT_SUFFIXES = (".html", ".htm")
RESOURCE_SUFFIXES = STYLE_SUFFIXES + IMAGE_SUFFIXES + FONT_SUFFIXES

# Local JS modules pulled in via one page's own scripts (single-page mode).
JS_SUFFIXES = (".js", ".mjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")


def _is_page_dependency(path: str) -> bool:
    """
    Return True if a URL path is an asset needed to render one page.

    Extension-based check: styles, scripts, images, and fonts are dependencies;
    HTML pages and documents without a known suffix are not.

    Args:
        path: The URL path string (may include a query string).

    Returns:
        True if the path suffix names a renderable page dependency.
    """
    lower = path.lower()
    return lower.endswith(RESOURCE_SUFFIXES)


def _resource_tag(html: str, pos: int) -> str:
    """
    Return the lowercase tag name that contains the attribute at ``pos``.

    Args:
        html: The raw HTML content being parsed.
        pos: Index of the matched attribute value inside ``html``.

    Returns:
        The tag name (e.g. ``a``, ``iframe``, ``link``), or ``""`` if none.
    """
    tag_start = html.rfind("<", 0, pos)
    if tag_start == -1:
        return ""
    tag = html[tag_start:pos].lstrip("<").strip()
    return re.split(r"\s+", tag, maxsplit=1)[0].lower()


# Tags that embed another document inline rather than linking to a separate page.
_EMBED_TAGS = ("iframe", "embed", "object", "frame")


def extract_resources(
    html: str, base_url: str, single_page: bool = False
) -> List[str]:
    """
    Extract all resource URLs from HTML content.

    Args:
        html: The HTML content to parse.
        base_url: The base URL for resolving relative URLs.
        single_page: If True, only keep resources required to render this one
            page (scripts, stylesheets, images, fonts, and embedded HTML
            includes), skipping links to other standalone web pages.

    Returns:
        List of unique resource URLs to download.
    """
    # Match href/src attributes (scripts, styles, links, images, etc.)
    pattern = r'href=["\']([^"\'>]+)["\']|src=["\']([^"\'>]+)["\']'
    matches = re.findall(pattern, html)

    resources = set()
    for groups in matches:
        link = groups[0] or groups[1]
        if link:
            resolved = urljoin(base_url, link.strip())
            # Ignore fragments/anchor-only links (no fetchable resource).
            parsed = urlparse(resolved)
            if parsed.scheme in ("http", "https", "file") and (
                parsed.path or parsed.query
            ):
                if single_page:
                    pos = html.rfind(link)
                    tag_name = _resource_tag(html, pos)
                    # Embedded includes are dependencies of this page.
                    is_embed = tag_name in _EMBED_TAGS
                    # User-facing anchors and <link> tags to HTML pages are not
                    # needed to render this page.
                    is_linked_page = tag_name in ("a", "link") and _is_html_doc(
                        urljoin(base_url, link.strip())
                    )
                    if is_linked_page:
                        continue
                    if not is_embed and not _is_page_dependency(parsed.path):
                        continue
                resources.add(resolved)

    return list(resources)


def _is_html_doc(url: str) -> bool:
    """
    Return True if ``url`` likely resolves to a standalone HTML document.

    Detects explicit ``.html``/``.htm`` suffixes and extensionless paths such
    as ``/about`` or ``/products/``.

    Args:
        url: The fully resolved URL.

    Returns:
        True if the URL names an HTML-style document.
    """
    path = urlparse(url).path
    if not path:
        return False
    lower = path.lower().rstrip("/")
    if lower.endswith(DOCUMENT_SUFFIXES):
        return True
    return path.split("/")[-1].find(".") == -1


# A CSS url(...) token: url("...") with optional surrounding whitespace.
_CSS_URL_PATTERN = re.compile(
    r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)", re.IGNORECASE
)
_CSS_IMPORT_PATTERN = re.compile(
    r"@import\s+(?:url\(([^)]+)\)|['\"]([^'\"]+)['\"])", re.IGNORECASE
)


def extract_css_dependencies(css: str, base_url: str) -> List[str]:
    """
    Extract image, font, and stylesheet URLs referenced from CSS content.

    Handles both ``url(...)`` references (background images, fonts, etc.) and
    ``@import`` statements (nested stylesheets).

    Args:
        css: The CSS text to parse.
        base_url: The base URL of the stylesheet, used to resolve relative URLs.

    Returns:
        List of unique resource URLs referenced by the CSS.
    """
    deps = set()

    for match in _CSS_URL_PATTERN.finditer(css):
        value = match.group(2).strip().strip("'\"")
        # Skip data: URIs.
        if value.startswith(("data:", "#", "about:")):
            continue
        resolved = urljoin(base_url, value)
        parsed = urlparse(resolved)
        if parsed.scheme in ("http", "https", "file"):
            deps.add(resolved)

    for match in _CSS_IMPORT_PATTERN.finditer(css):
        value = (match.group(1) or match.group(2) or "").strip().strip("'\"")
        if not value:
            continue
        resolved = urljoin(base_url, value)
        parsed = urlparse(resolved)
        if parsed.scheme in ("http", "https", "file"):
            deps.add(resolved)

    return list(deps)


# A JS module import token. Matches the quoted specifier in a static
# ``import ... from "..."``, side-effect ``import "..."``, re-export
# ``export ... from "..."``, and dynamic ``import("...")``.
_JS_IMPORT_PATTERN = re.compile(
    r"""(?:import\s*\(|(?:import|export)\b[^;"')]*?\bfrom\s*|import\s+)(['"])"""
    r"""([^'"]+)\1""",
    re.IGNORECASE,
)


def extract_js_dependencies(js: str, base_url: str) -> List[str]:
    """
    Extract local module and asset URLs referenced by JavaScript content.

    In addition to ES module imports, JavaScript frequently injects CSS values
    such as ``background-image:url("...")`` pointing at local images. Those are
    resolved relative to the script's own directory and returned too.

    Recognized forms:

    - ``import ... from "..."``, ``export ... from "..."``, ``import("...")``
    - ``import "..."`` side-effect imports
    - ``url("path/to/image.webp")`` inline-URL references inside strings

    Args:
        js: The JavaScript text to parse.
        base_url: The base URL of the script, used to resolve relative imports.

    Returns:
        List of unique local module and asset URLs referenced by the script.
    """
    # Strip comments so specifiers inside comments/URLs are ignored.
    stripped = re.sub(r"//[^\n]*|/\*.*?\*/", "", js, flags=re.DOTALL)
    deps: Set[str] = set()

    # ES module imports (relative/local script files only).
    for match in _JS_IMPORT_PATTERN.finditer(stripped):
        specifier = match.group(2).strip()
        if not specifier or specifier.startswith(("data:", "#", "http:", "https:")):
            continue
        resolved = urljoin(base_url, specifier)
        parsed = urlparse(resolved)
        if parsed.scheme != "file" and not specifier.startswith((".", "/")):
            # Bare package/module name (e.g. "react"): not a local file.
            continue
        if filename_suffix(parsed.path) in JS_SUFFIXES:
            deps.add(resolved)

    # Inline url(...) references to local images/fonts (JS-injected CSS).
    for match in _JS_INLINE_URL_PATTERN.finditer(stripped):
        href = _sanitize_js_url(match.group(1))
        if not href or href.startswith(("data:", "#", "http:", "https:")):
            continue
        suffix = filename_suffix(href)
        if not suffix:
            continue
        if suffix in IMAGE_SUFFIXES or suffix in FONT_SUFFIXES:
            resolved = urljoin(base_url, href)
            deps.add(resolved)

    return list(deps)


# ``url(...)`` inside JS (possibly wrapped in another quoted string). The
# content is captured for disambiguation to handle both ``url(img.png)`` and
# JS that builds the value, e.g. ``url("'+path+'img.webp")``.
_JS_INLINE_URL_PATTERN = re.compile(r"""url\(([^)]*)\)""", re.IGNORECASE)


def _sanitize_js_url(value: str) -> str:
    """
    Reconstruct a plausible resource path from a JS url(...) value fragment.

    JS often concatenates a runtime base path with a literal string, e.g.
    ``url("'+path+'New-Social-Media-Icons.webp")``. When the value uses ``+``
    string concatenation we keep the trailing quoted literal (the actual file
    name) and discard the runtime variable part, so the resource can be
    resolved relative to the script. Simple values pass through unchanged.

    Args:
        value: The raw content from inside ``url(...)``.

    Returns:
        A cleaned-up relative path to attempt to download.
    """
    cleaned = value.strip()

    if "+" in cleaned:
        # Keep the trailing quoted literal that names a real resource file.
        parts = re.split(r"""['"]""", cleaned)
        candidates = [p.strip() for p in parts if p.strip()]
        for candidate in reversed(candidates):
            seg = candidate.split("/")[-1].strip()
            if filename_suffix(seg) in IMAGE_SUFFIXES or filename_suffix(seg) in FONT_SUFFIXES:
                cleaned = candidate
                break

    cleaned = cleaned.replace("\\/", "/").strip()

    # Take the trailing slash-segment that ends in a known resource; this
    # discards leading runtime tokens when concatenation survived.
    segments = [s for s in cleaned.split("/") if s and s != "."]
    for i in range(len(segments) - 1, -1, -1):
        seg = segments[i]
        if filename_suffix(seg) in IMAGE_SUFFIXES or filename_suffix(seg) in FONT_SUFFIXES:
            return "/".join(segments[i:])
    return cleaned


def filename_suffix(pathname: str) -> str:
    """
    Return the lowercase file extension of a path, or ``""`` if none.

    Handles query strings by operating on the path portion only.

    Args:
        pathname: A URL path or filename.

    Returns:
        The leading-dot lowercase extension (e.g. ``".js"``), or ``""``.
    """
    parsed = urlparse(pathname)
    name = parsed.path if parsed.scheme else pathname
    _, dot, ext = name.rpartition(".")
    if not dot:
        return ""
    return ("." + ext).lower()


def download_resource(
    session: Optional[requests.Session],
    url: str,
    output_dir: Path,
    seen: Set[str],
    referer: Optional[str] = None,
    depth: int = 0,
    max_depth: int = 1,
) -> bool:
    """
    Download a single resource with error handling.

    Args:
        session: Requests session to use (None for file:// URLs).
        url: Resource URL to download.
        output_dir: Directory to save the file.
        seen: Set of already-processed URLs.
        referer: Optional referer header.
        depth: Current recursion depth.
        max_depth: Maximum allowed depth.

    Returns:
        True if download succeeded, False otherwise.
    """
    if url in seen:
        return False

    seen.add(url)

    # Enforce depth limit
    if depth > max_depth:
        print("Skipping (depth exceeded): {}".format(url))
        return False

    output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir

    filename = _safe_path(url)

    try:
        # Handle file:// URLs specially
        if url.startswith("file://"):
            local_path = urlparse(url).path
            if not os.path.exists(local_path):
                print("File not found: {}".format(local_path))
                return False
            with open(local_path, "rb") as src:
                content = src.read()
            return write_resource(output_dir, url, filename, content)

        if session is None:
            print("No session available for: {}".format(url))
            return False

        # Add referer header for this request.
        headers = {"Referer": referer} if referer else None

        response = session.get(
            url,
            timeout=DEFAULT_TIMEOUT,
            headers=headers,
            stream=True,
        )

        # Validate response
        if response.status_code != 200:
            print("Failed ({}): {}".format(response.status_code, url))
            return False

        # Read the raw bytes; stream is used only to avoid holding unrelated
        # large chunks in memory, which requests already streams internally.
        content = response.content

        return write_resource(output_dir, url, filename, content)

    except requests.exceptions.Timeout:
        print("Timeout: {}".format(url))
        return False
    except requests.exceptions.ConnectionError as e:
        print("Connection error: {} - {}".format(url, e))
        return False
    except requests.exceptions.HTTPError as e:
        print("HTTP error: {} - {}".format(url, e))
        return False
    except Exception as e:
        print("Unexpected error downloading {}: {}".format(url, e))
        return False


def _save_page(
    session: Optional[requests.Session],
    url: str,
    output_dir: Path,
    referer: Optional[str],
) -> Optional[str]:
    """
    Fetch and save a page's own content.

    Returns the raw page text, or None on failure.

    Args:
        session: Requests session (None for file:// URLs).
        url: The page URL.
        output_dir: Directory to save the mirrored page.
        referer: Optional referer header.

    Returns:
        The page text on success, None otherwise.
    """
    filename = _safe_path(url)

    if url.startswith("file://"):
        local_path = urlparse(url).path
        if not os.path.exists(local_path):
            print("File not found: {}".format(local_path), file=sys.stderr)
            return None
        with open(local_path, "rb") as f:
            content = f.read()
        write_resource(output_dir, url, filename, content)
        return content.decode("utf-8", errors="replace")

    if session is None:
        return None

    headers = {"Referer": referer} if referer else None
    try:
        response = session.get(url, timeout=DEFAULT_TIMEOUT, headers=headers)
    except requests.exceptions.RequestException as e:
        print("Failed to fetch page: {} - {}".format(url, e), file=sys.stderr)
        return None

    if response.status_code != 200:
        print(
            "Failed to fetch page (HTTP {}): {}".format(response.status_code, url),
            file=sys.stderr,
        )
        return None

    content = response.content
    write_resource(output_dir, url, filename, content)
    return content.decode("utf-8", errors="replace")


def _download_page_resources(
    session: Optional[requests.Session],
    resources: List[str],
    output_dir: Path,
    referer: Optional[str],
    max_depth: int,
    single_page: bool,
) -> int:
    """
    Download an initial set of resources, recursing into CSS dependencies.

    In single-page mode the content of downloaded stylesheets is scanned for
    ``url(...)`` and ``@import`` references (background images, fonts, nested
    stylesheets) which are downloaded as well so that the page's CSS renders
    with its assets intact.

    Args:
        session: Requests session (None for file:// URLs).
        resources: Initial resource URLs to download.
        output_dir: Directory to save files.
        referer: Optional referer header.
        max_depth: Maximum allowed recursion depth.
        single_page: Whether to follow CSS-referenced assets.

    Returns:
        A tuple of ``(success_count, total_count)`` for downloaded resources.
    """
    seen: Set[str] = set()
    queue = list(resources)
    success_count = 0
    total_count = 0

    while queue:
        resource = queue.pop(0)
        time.sleep(0.1)
        total_count += 1
        saved = download_resource(
            session, resource, output_dir, seen, referer, depth=1, max_depth=max_depth
        )
        if not saved:
            continue
        success_count += 1

        # Recurse into nested dependencies (CSS assets and JS module imports)
        # only in single-page mode.
        if single_page:
            if _looks_like_css(resource):
                css = _read_original(session, resource)
                if css is not None:
                    base = resource.rstrip("/")
                    for dep in extract_css_dependencies(css, base):
                        if dep not in seen:
                            queue.append(dep)
            elif _looks_like_js_module(resource):
                js = _read_original(session, resource)
                if js is not None:
                    base = resource.rstrip("/")
                    for dep in extract_js_dependencies(js, base):
                        if dep not in seen:
                            queue.append(dep)

    return (success_count, total_count)


def _looks_like_css(url: str) -> bool:
    """
    Return True if a URL likely points at a stylesheet worth scanning.

    Args:
        url: The resource URL.

    Returns:
        True if the path ends with a CSS-style extension.
    """
    path = urlparse(url).path.lower()
    return path.endswith((".css", ".mcss", ".scss", ".less"))


def _looks_like_js_module(url: str) -> bool:
    """
    Return True if a URL likely points at a JS module worth scanning.

    Args:
        url: The resource URL.

    Returns:
        True if the path ends with a JS-style extension.
    """
    path = urlparse(url).path.lower()
    return path.endswith((".js", ".mjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"))
def _read_original(session: Optional[requests.Session], url: str) -> Optional[str]:
    """
    Read the raw content of a resource fetched from its origin.

    Used to scan stylesheet bodies for nested dependency references.

    Args:
        session: Requests session (None for file:// URLs).
        url: The resource URL to read.

    Returns:
        Decoded text content, or None if it could not be fetched.
    """
    if url.startswith("file://"):
        local_path = urlparse(url).path
        if not os.path.exists(local_path):
            return None
        with open(local_path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")

    if session is None:
        return None
    try:
        response = session.get(url, timeout=DEFAULT_TIMEOUT)
        if response.status_code != 200:
            return None
        return response.content.decode("utf-8", errors="replace")
    except requests.exceptions.RequestException:
        return None


def mirror_clone(
    url: str,
    output_dir: str,
    referer: Optional[str] = None,
    depth: int = 1,
    verify: bool = True,
    single_page: bool = False,
) -> None:
    """
    Mirror a web page and all its resources to a local directory.

    Args:
        url: The URL of the page to mirror.
        output_dir: Directory to save the mirrored content.
        referer: Optional referer URL for requests.
        depth: Maximum recursive depth for downloading linked resources.
            Default is 1 (only direct links from the main page).
        verify: Whether to verify TLS certificates during downloads.
            Set to False to allow self-signed or invalid certificates.
        single_page: If True, mirror only the assets this one page needs to
            render (scripts, stylesheets, images, fonts, and embedded includes)
            and skip links to other standalone web pages.
    """
    # Validate inputs
    try:
        normalized_url = validate_url(url)
    except MirrorError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)

    # Create output directory
    output_path = Path(output_dir).resolve()
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(
            "Error: Cannot create output directory '{}': {}".format(output_dir, e),
            file=sys.stderr,
        )
        sys.exit(1)

    print("Mirroring {} to {}".format(normalized_url, output_path))
    print("-" * 60)

    session: Optional[requests.Session] = None
    success_count = 0
    total_count = 0

    try:
        # No HTTP session needed for file:// URLs.
        if not normalized_url.startswith("file://"):
            session = create_session(referer, verify)

        # Fetch and save the page itself.
        html = _save_page(session, normalized_url, output_path, referer)
        if html is None:
            sys.exit(1)

        base_url = normalized_url.rstrip("/")
        resources = extract_resources(html, base_url, single_page=single_page)

        # Download resources, following CSS dependencies in single-page mode.
        success_count, total_count = _download_page_resources(
            session, resources, output_path, referer, depth, single_page
        )

    finally:
        # Close session and release connection pool (if created)
        if session is not None:
            session.close()

    # Print summary
    print("-" * 60)
    print(
        "Complete: {}/{} resources downloaded".format(success_count, total_count)
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Mirror a web page and all its resources to a local directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mirror_clone.py https://example.com ./mirror
  python mirror_clone.py http://test.org/page.html ./output --referer http://test.org
  python mirror_clone.py https://example.com ./mirror -r "http://example.com"
  python mirror_clone.py https://example.com ./mirror --single-page
        """,
    )

    parser.add_argument(
        "url",
        metavar="URL",
        help="The URL of the page to mirror (http:// or https:// required)",
    )
    parser.add_argument(
        "output_dir",
        metavar="OUTPUT_DIR",
        help="Directory to save the mirrored content",
    )
    parser.add_argument(
        "-r",
        "--referer",
        metavar="URL",
        help=("Referer header to include in requests "
              "(useful for sites that check origin)"),
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=1,
        metavar="N",
        help="Maximum recursive depth for downloading linked resources (default: 1)",
    )
    parser.add_argument(
        "--single-page",
        dest="single_page",
        action="store_true",
        help=(
            "Mirror only the resources this one page needs to render "
            "(scripts, styles, images, fonts, and embedded includes); "
            "do not download links to other web pages"
        ),
    )
    parser.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="Disable TLS certificate verification (e.g. for self-signed certs)",
    )

    return parser.parse_args(argv)


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Execute mirror operation
    try:
        mirror_clone(
            args.url,
            args.output_dir,
            args.referer,
            args.depth,
            args.verify,
            args.single_page,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
