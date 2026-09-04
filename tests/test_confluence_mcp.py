"""Tests for the Confluence MCP server tool surface."""

from docgrity.mcp.confluence import server


async def test_all_documented_tools_registered():
    tools = {tool.name for tool in await server.mcp.list_tools()}
    expected = {
        "search",
        "get_page",
        "get_children",
        "get_history",
        "get_comments",
        "get_owner",
        "add_comment",
        "update_page",
        "archive_page",
        "capabilities",
    }
    assert expected <= tools


def test_capabilities_declaration():
    caps = server.capabilities()
    assert "SEARCH" in caps["read"]
    # Write tools are enabled but only reachable via human-approved dashboard actions.
    assert caps["write"]["UPDATE_PAGE"] is True
    assert caps["write"]["ARCHIVE_PAGE"] is True
