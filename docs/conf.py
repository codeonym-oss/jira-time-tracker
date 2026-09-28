"""Sphinx configuration: MyST pages, Shibuya theme."""

from importlib.metadata import version as _version

project = "jira-time-tracker"
author = "codeonym-oss"
copyright = "codeonym-oss — MIT License"
release = _version("jira-time-tracker")
version = ".".join(release.split(".")[:2])

extensions = ["myst_parser"]
# tapes/ holds the VHS sources of the GIFs, not pages.
exclude_patterns = ["_build", "tapes"]

# Pages: Markdown, with ```{directive} blocks and `#heading` anchors for links.
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

html_theme = "shibuya"
html_title = "jira-time-tracker"
html_baseurl = "https://docs.codeonym.work/projects/jira-time-tracker/"
html_context = {
    "source_type": "github",
    "source_user": "codeonym-oss",
    "source_repo": "jira-time-tracker",
    "source_version": "main",
    "source_docs_path": "/docs/",
}
html_theme_options = {
    "accent_color": "indigo",
    "github_url": "https://github.com/codeonym-oss/jira-time-tracker",
    "nav_links": [
        {"title": "Guide", "url": "guide/getting-started"},
        {"title": "Commands", "url": "commands/index"},
        {"title": "PyPI", "url": "https://pypi.org/project/jira-time-tracker/", "external": True},
    ],
}
