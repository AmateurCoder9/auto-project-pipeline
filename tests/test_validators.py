"""
test_validators.py - Unit tests for HTML validator module
"""

from validators import validate_generated_html


def test_valid_html_passes():
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Test Tool</title>
    <style>body { background: #000; color: #fff; }</style>
    <script src="https://cdn.jsdelivr.net/npm/vue@2"></script>
</head>
<body>
    <div id="app">Hello World</div>
    <script>console.log("ready");</script>
</body>
</html>"""
    is_valid, issues = validate_generated_html(html)
    assert is_valid is True
    assert len(issues) == 0

def test_empty_html_rejected():
    is_valid, issues = validate_generated_html("")
    assert is_valid is False
    assert "HTML content is empty" in issues[0]

def test_short_html_rejected():
    is_valid, issues = validate_generated_html("<html>Hi</html>")
    assert is_valid is False
    assert any("suspiciously short" in issue for issue in issues)

def test_unallowlisted_cdn_script_rejected():
    html = """<!DOCTYPE html>
<html>
<head>
    <style>body { font-family: sans-serif; }</style>
    <script src="https://malicious-cdn.evil.com/payload.js"></script>
</head>
<body>
    <div>App Content</div>
    <script>console.log("test");</script>
</body>
</html>"""
    is_valid, issues = validate_generated_html(html)
    assert is_valid is False
    assert any("malicious-cdn.evil.com" in issue for issue in issues)

def test_missing_structure_rejected():
    html = "<div>Plain div content</div>" * 5
    is_valid, issues = validate_generated_html(html)
    assert is_valid is False
    assert any("Missing structural elements" in issue for issue in issues)
