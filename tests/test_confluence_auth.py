"""Tests for the Confluence client auth modes (Marketplace: no basic auth in prod)."""

import pytest

from docgrity.core.config import Settings
from docgrity.mcp.confluence.client import ConfluenceClient


def test_bearer_auth_preferred_over_basic():
    settings = Settings(
        confluence_base_url="https://api.atlassian.com/ex/confluence/cloud-1",
        confluence_email="dev@example.com",
        confluence_api_token="token",
        confluence_access_token="oauth-token",
    )
    client = ConfluenceClient.from_settings(settings)
    assert client._client.headers["Authorization"] == "Bearer oauth-token"
    assert client._client.auth is None


def test_basic_auth_fallback_for_dev():
    settings = Settings(
        confluence_base_url="https://example.atlassian.net",
        confluence_email="dev@example.com",
        confluence_api_token="token",
        confluence_access_token="",
    )
    client = ConfluenceClient.from_settings(settings)
    assert "Authorization" not in client._client.headers
    assert client._client.auth is not None


def test_no_credentials_raises():
    with pytest.raises(ValueError):
        ConfluenceClient(base_url="https://example.atlassian.net")
