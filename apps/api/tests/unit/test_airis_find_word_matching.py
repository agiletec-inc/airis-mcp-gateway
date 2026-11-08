"""airis-find: multi-word queries match word by word.

Before this, a query only matched when the WHOLE query was a substring of a
tool's name, description or server, so "hyprland settings config" or
"breaking changes home assistant" missed tools whose descriptions contain
every one of those words.
"""

from app.core.dynamic_mcp import DynamicMCP, ToolInfo


def _dmcp(*tools: tuple[str, str, str]) -> DynamicMCP:
    dmcp = DynamicMCP()
    for name, server, description in tools:
        dmcp._tools[name] = ToolInfo(
            name=name,
            server=server,
            description=description,
            input_schema={},
            source="process",
        )
        dmcp._tool_to_server[name] = server
    return dmcp


def _names(results: dict) -> list[str]:
    # Skip TOOL_CATALOG fallback rows; they are not what this file tests.
    return [
        t["name"]
        for t in results["tools"]
        if not t["description"].startswith("[catalog]")
    ]


DOCS = (
    "search_docs",
    "docs-kb",
    "Search the Hyprland wiki: window rules, keybindings and monitor config.",
)
BREAKING = (
    "check_breaking_changes",
    "hass-kb",
    "Check Home Assistant breaking changes between releases.",
)


def test_every_word_present_matches_in_any_order():
    dmcp = _dmcp(DOCS, BREAKING)
    assert _names(dmcp.find(query="hyprland monitor config")) == ["search_docs"]
    assert _names(dmcp.find(query="breaking changes home assistant")) == [
        "check_breaking_changes"
    ]


def test_words_may_come_from_name_description_or_server():
    dmcp = _dmcp(BREAKING)
    assert _names(dmcp.find(query="hass releases check")) == ["check_breaking_changes"]


def test_a_missing_word_does_not_match():
    dmcp = _dmcp(DOCS, BREAKING)
    assert _names(dmcp.find(query="hyprland wallpaper")) == []


def test_stopwords_are_ignored():
    dmcp = _dmcp(DOCS)
    assert _names(dmcp.find(query="where is the monitor config in hyprland")) == [
        "search_docs"
    ]


def test_a_word_matches_through_its_synonyms():
    # "find" is a synonym of "search" in tool_suggester.KEYWORD_SYNONYMS.
    dmcp = _dmcp(DOCS)
    assert _names(dmcp.find(query="find hyprland keybindings")) == ["search_docs"]


def test_single_word_queries_are_unchanged():
    # A lone word keeps plain substring matching: no synonym widening.
    dmcp = _dmcp(DOCS)
    assert _names(dmcp.find(query="find")) == []
    assert _names(dmcp.find(query="hyprland")) == ["search_docs"]


def test_phrase_matches_rank_before_word_matches_and_survive_the_limit():
    word_only = [
        (f"tool_{i}", "other", "monitor tooling for hyprland setups") for i in range(5)
    ]
    phrase = ("monitor_hyprland", "wm", "Hyprland monitor setup")
    dmcp = _dmcp(*word_only, phrase)
    names = _names(dmcp.find(query="hyprland monitor", limit=3))
    assert names[0] == "monitor_hyprland"
    assert len(names) == 3
