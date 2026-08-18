"""
validators.py

Validates and sanitizes Gemini-generated HTML before it gets pushed
to a public GitHub repo or deployed to Vercel.

Checks:
  1. Well-formed HTML (parses without errors)
  2. Required structural elements present
  3. External <script src> only from allowlisted CDN domains
"""

from html.parser import HTMLParser
from urllib.parse import urlparse

from common import get_logger

logger = get_logger(__name__)

# CDN domains we trust for external <script src="...">
ALLOWED_CDN_DOMAINS = frozenset({
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "unpkg.com",
    "cdn.tailwindcss.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "ajax.googleapis.com",
    "code.jquery.com",
    "stackpath.bootstrapcdn.com",
    "cdn.socket.io",
    "d3js.org",
    "cdn.plot.ly",
})


class _HTMLAuditParser(HTMLParser):
    """
    Walks the HTML tree collecting structural info and flagging issues.
    """

    def __init__(self):
        super().__init__()
        self.tags_seen: set[str] = set()
        self.issues: list[str] = []
        self.has_script_content = False
        self.has_style_content = False
        self._in_script = False
        self._in_style = False
        self.parse_errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self.tags_seen.add(tag_lower)

        if tag_lower == "script":
            self._in_script = True
            attr_dict = dict(attrs)
            src = attr_dict.get("src", "")
            if src:
                self._check_script_src(src)

        if tag_lower == "style":
            self._in_style = True

        # Check for <link> with stylesheet pointing to untrusted domains
        if tag_lower == "link":
            attr_dict = dict(attrs)
            if attr_dict.get("rel", "").lower() == "stylesheet":
                href = attr_dict.get("href", "")
                if href and href.startswith(("http://", "https://")):
                    self._check_cdn_domain(href, "stylesheet")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "script":
            self._in_script = False
        if tag_lower == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if self._in_script and stripped:
            self.has_script_content = True
        if self._in_style and stripped:
            self.has_style_content = True

    def _check_script_src(self, src: str) -> None:
        if not src.startswith(("http://", "https://")):
            return  # relative paths are fine
        self._check_cdn_domain(src, "script")

    def _check_cdn_domain(self, url: str, resource_type: str) -> None:
        try:
            parsed = urlparse(url)
            domain = parsed.hostname or ""
        except Exception:
            self.issues.append(f"Unparseable {resource_type} URL: {url}")
            return

        if domain not in ALLOWED_CDN_DOMAINS:
            self.issues.append(
                f"External {resource_type} from non-allowlisted domain: "
                f"{domain} (URL: {url})"
            )

    def error(self, message: str) -> None:
        self.parse_errors.append(message)


def validate_generated_html(html_string: str) -> tuple[bool, list[str]]:
    """
    Validate Gemini-generated HTML content.

    Returns:
        (is_valid, list_of_issues) — is_valid is True only when all
        checks pass and list_of_issues is empty.
    """
    issues: list[str] = []

    if not html_string or not html_string.strip():
        issues.append("HTML content is empty")
        return False, issues

    # Check minimum length (a real app should be at least a few hundred chars)
    if len(html_string.strip()) < 100:
        issues.append(
            f"HTML content suspiciously short ({len(html_string.strip())} chars)"
        )

    # Parse
    parser = _HTMLAuditParser()
    try:
        parser.feed(html_string)
    except Exception as e:
        issues.append(f"HTML parsing failed: {e}")
        return False, issues

    issues.extend(parser.parse_errors)
    issues.extend(parser.issues)

    # Structural checks — we accept either full HTML5 structure
    # OR a minimal fragment with at least <style> + visible content
    has_full_structure = (
        "html" in parser.tags_seen
        and "head" in parser.tags_seen
        and "body" in parser.tags_seen
    )
    has_minimal_structure = (
        parser.has_style_content or parser.has_script_content
    )

    if not has_full_structure and not has_minimal_structure:
        issues.append(
            "Missing structural elements: expected <html>/<head>/<body> "
            "or at minimum inline <style>/<script> content"
        )

    is_valid = len(issues) == 0
    if not is_valid:
        logger.warning(
            "HTML validation failed with %d issue(s): %s",
            len(issues),
            "; ".join(issues),
        )
    return is_valid, issues
