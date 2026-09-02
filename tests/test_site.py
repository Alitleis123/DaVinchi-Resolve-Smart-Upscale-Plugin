"""The public site under docs/.

It is served straight from the repo by GitHub Pages, so nothing rebuilds it and
nothing catches it drifting. It described the removed Detect, Sequence, Regroup
and Upscale workflow for as long as that workflow had been gone.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

PAGES = ["index.html", "help.html", "download.html", "contact.html"]

# Tags that never carry a closing tag.
VOID = {"br", "img", "meta", "link", "input", "hr", "area", "base", "col",
        "embed", "source", "track", "wbr",
        # inline svg shapes used across the site
        "path", "circle", "line", "polyline", "rect", "ellipse", "polygon", "use"}


class Structure(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.mismatched: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            self.mismatched.append(tag)
            self.stack.remove(tag)


def page(repo_root: Path, name: str) -> str:
    return (repo_root / "docs" / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", PAGES)
def test_pages_are_well_formed(repo_root, name):
    parser = Structure()
    parser.feed(page(repo_root, name))
    assert not parser.stack, f"{name} leaves {parser.stack} unclosed"
    assert not parser.mismatched, f"{name} closes {parser.mismatched} out of order"


@pytest.mark.parametrize("name", PAGES)
def test_internal_links_point_at_pages_that_exist(repo_root, name):
    for href in re.findall(r'href="([^"#:]+\.html)"', page(repo_root, name)):
        assert (repo_root / "docs" / href).exists(), f"{name} links to missing {href}"


@pytest.mark.parametrize("name", PAGES)
def test_assets_referenced_exist(repo_root, name):
    for src in re.findall(r'(?:src|href)="((?:assets|css)/[^"]+)"', page(repo_root, name)):
        assert (repo_root / "docs" / src).exists(), f"{name} references missing {src}"


@pytest.mark.parametrize("name", PAGES)
def test_pages_have_no_byte_order_mark(repo_root, name):
    assert (repo_root / "docs" / name).read_bytes()[:3] != b"\xef\xbb\xbf"


# --------------------------------------------------------------------------
# the site has to describe the plugin that exists
# --------------------------------------------------------------------------

REMOVED = ["[DSU]", "Regroup", "Upscale + Interpolate", "sensitivity slider"]


@pytest.mark.parametrize("name", PAGES)
def test_the_site_does_not_document_removed_features(repo_root, name):
    text = page(repo_root, name)
    for gone in REMOVED:
        assert gone not in text, (
            f"{name} still documents {gone!r}, which the plugin no longer has"
        )


def test_the_help_page_names_the_buttons_the_panel_actually_has(repo_root):
    lua = (repo_root / "Installer" / "Eternal2x.lua").read_text(encoding="utf-8")
    help_text = page(repo_root, "help.html").lower()

    for _bid, raw in re.findall(
            r'ui:Button\{\s*ID\s*=\s*"(\w+)"\s*,\s*Text\s*=\s*"([^"]+)"', lua):
        label = re.sub(r'\\x[0-9A-Fa-f]{2}', "", raw).strip().lower()
        if not label or label == "reset":
            continue
        assert label in help_text, f"help.html never mentions the {label!r} button"


def test_the_help_page_covers_the_current_failure_messages(repo_root):
    """Every message the panel can show a user should be findable in the help."""
    help_text = page(repo_root, "help.html").lower()
    for message in ("plugin folder not configured", "could not reach resolve",
                    "nothing to do", "refresh progress"):
        assert message in help_text, f"help.html does not cover {message!r}"


def test_the_site_states_the_studio_requirement(repo_root):
    combined = " ".join(page(repo_root, n) for n in PAGES)
    assert "Studio" in combined


def test_the_download_page_reads_releases_from_the_right_repo(repo_root):
    from Installer.build_release import REPO
    assert f"'{REPO}'" in page(repo_root, "download.html"), (
        "the download page points at a different repository than releases are cut from"
    )
