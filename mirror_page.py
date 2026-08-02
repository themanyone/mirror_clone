#!/usr/bin/env python3
"""
Mirror a web page and all its resources to a local directory.

This script downloads an HTML page and extracts all linked resources
(scripts, stylesheets, images, etc.), saving them to a local directory
with preserved relative paths.

Usage:
    python mirror_page.py <url> <output_dir>

Examples:
    python mirror_page.py https://example.com ./mirror
    python mirror_page.py http://test.org/page.html ./output --referer http://test.org
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class MirrorError(Exception):
    """Custom exception for mirror_page errors."""

    pass


def create_session(referer: str | None = None) -> requests.Session:
    """
    Create a requests.Session with connection pooling and retry logic.

    Args:
        referer: Optional referer header to include in requests.

    Returns:
        Configured requests.Session instance.
    """
    session = requests.Session()

    # Configure retry strategy for transient failures
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504, 429],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # File URLs don't need retries
    file_adapter = HTTPAdapter(max_retries=0)
    session.mount("file://", file_adapter)

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

    # Strip protocol if missing
    if not urlparse(url).scheme:
        url = "https://" + url

    # Basic pattern validation
    pattern = r"^(https?|file)://[a-zA-Z0-9.\-/:_@?&=%#]+$"
    if not re.match(pattern, url):
        raise MirrorError(
            f"Invalid URL format: {url}. Expected http://, https://, or file://"
        )

    return url


def extract_resources(html: str, base_url: str) -> list[str]:
    """
    Extract all resource URLs from HTML content.

    Args:
        html: The HTML content to parse.
        base_url: The base URL for resolving relative URLs.

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
            resources.add(resolved)

    return list(resources)


def download_resource(
    session: requests.Session,
    url: str,
    output_dir: Path,
    seen: set[str],
    referer: str | None = None,
    depth: int = 0,
    max_depth: int = 1,
) -> bool:
    """
    Download a single resource with error handling.

    Args:
        session: Requests session to use.
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
        print(f"Skipping (depth exceeded): {url}")
        return False
    output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir

    filename = os.path.basename(urlparse(url).path)
    filepath = output_dir / filename

    # Skip if file already exists and is not a directory
    if filepath.exists() and not filepath.is_dir():
        print(f"Skipping (exists): {url}")
        return False

    try:
        # Handle file:// URLs specially
        if url.startswith("file://"):
            local_path = urlparse(url).path
            if os.path.exists(local_path):
                with open(local_path, "rb") as src:
                    content = src.read()
                with open(filepath, "wb") as dst:
                    dst.write(content)
                return True
            else:
                print(f"File not found: {local_path}")
                return False

        # For HTTP/HTTPS URLs, use requests
        # Add referer header for this request
        headers = dict(session.headers) if session else {}
        if referer:
            headers["Referer"] = referer

        response = session.get(
            url,
            timeout=30,
            headers=headers,
            stream=True,
        )

        # Validate response
        if response.status_code != 200:
            print(f"Failed ({response.status_code}): {url}")
            return False

        # Parse content type to handle encoding
        content_type = response.headers.get("Content-Type", "").lower()
        is_text = "text/" in content_type or "application/json" in content_type

        if is_text:
            # Try UTF-8 first, then fallback to response encoding
            try:
                text = response.text
            except UnicodeDecodeError:
                text = response.content.decode(
                    response.encoding or "utf-8", errors="replace"
                )
        else:
            text = response.content

        # Write file
        with open(filepath, "wb") as f:
            f.write(text if not is_text else response.content)

        return True

    except requests.exceptions.Timeout:
        print(f"Timeout: {url}")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"Connection error: {url} - {e}")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error: {url} - {e}")
        return False
    except Exception as e:
        print(f"Unexpected error downloading {url}: {e}")
        return False


def mirror_page(
    url: str,
    output_dir: str,
    referer: str | None = None,
    depth: int = 1,
) -> None:
    """
    Mirror a web page and all its resources to a local directory.

    Args:
        url: The URL of the page to mirror.
        output_dir: Directory to save the mirrored content.
        referer: Optional referer URL for requests.
        depth: Maximum recursive depth for downloading linked resources.
            Default is 1 (only direct links from the main page).
    """
    # Validate inputs
    try:
        normalized_url = validate_url(url)
    except MirrorError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Handle file:// URLs separately (requests doesn't support them)
    if normalized_url.startswith("file://"):
        local_path = urlparse(normalized_url).path
        if not os.path.exists(local_path):
            print(f"Error: File not found: {local_path}", file=sys.stderr)
            sys.exit(1)

        # Initialize counters
        resources: list[str] = []
        success_count = 0

        # Create output directory
        output_path = Path(output_dir).resolve()
        try:
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"Error: Cannot create output directory '{output_dir}': {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Mirroring {normalized_url} to {output_path}")
        print("-" * 60)

        try:
            with open(local_path, "r", encoding="utf-8") as f:
                html = f.read()
            base_url = normalized_url
            session = None  # No session needed for file:// URLs
        except Exception as e:
            print(f"Error: Failed to read file: {e}", file=sys.stderr)
            sys.exit(1)

        # Extract resources
        resources = extract_resources(html, base_url)

        # Download resources
        seen: set[str] = set()
        for resource in resources:
            time.sleep(0.1)
            if download_resource(session, resource, output_path, seen, referer, depth=1, max_depth=depth):
                success_count += 1

    else:
        # Initialize counters
        resources: list[str] = []
        success_count = 0

        # Create output directory
        output_path = Path(output_dir).resolve()
        try:
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"Error: Cannot create output directory '{output_dir}': {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Mirroring {normalized_url} to {output_path}")
        print("-" * 60)

        # Create session with pooling and retry logic
        session = create_session(referer)

        try:
            # Fetch the main page
            try:
                response = session.get(normalized_url, timeout=30)
            except requests.exceptions.RequestException as e:
                print(f"Error: Failed to fetch {normalized_url}: {e}", file=sys.stderr)
                sys.exit(1)

            # Validate response
            if response.status_code != 200:
                print(
                    f"Error: Failed to fetch page (HTTP {response.status_code}): {normalized_url}"
                )
                sys.exit(1)

            # Parse HTML and extract resources
            html = response.text
            base_url = normalized_url.rstrip("/")

            # Extract resources
            resources = extract_resources(html, base_url)

            # Download resources
            seen: set[str] = set()
            for resource in resources:
                time.sleep(0.1)
                if download_resource(session, resource, output_path, seen, referer, depth=1, max_depth=depth):
                    success_count += 1

        finally:
            # Close session and release connection pool (if created)
            if session is not None:
                session.close()

    # Print summary
    print("-" * 60)
    print(f"Complete: {success_count}/{len(resources)} resources downloaded")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
  python mirror_page.py https://example.com ./mirror
  python mirror_page.py http://test.org/page.html ./output --referer http://test.org
  python mirror_page.py https://example.com ./mirror -r "http://example.com"
        """
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
        help="Referer header to include in requests (useful for sites that check origin)",
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=1,
        metavar="N",
        help="Maximum recursive depth for downloading linked resources (default: 1)",
    )

    return parser.parse_args(argv)


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Validate required arguments
    if not args.url:
        print("Error: URL is required", file=sys.stderr)
        parser = argparse.ArgumentParser(add_help=False)
        parser.print_help()
        sys.exit(1)

    if not args.output_dir:
        print("Error: Output directory is required", file=sys.stderr)
        parser = argparse.ArgumentParser(add_help=False)
        parser.print_help()
        sys.exit(1)

    # Execute mirror operation
    try:
        mirror_page(args.url, args.output_dir, args.referer, args.depth)
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
