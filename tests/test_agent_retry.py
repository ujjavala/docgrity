"""Unit tests for run_agent retry behaviour (no network, no sleep)."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from docgrity.agents.base import run_agent


class Out(BaseModel):
    value: int


class _Result:
    def __init__(self, output):
        self.output = output


class _ProviderError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _agent(side_effects):
    agent = AsyncMock()
    agent.run = AsyncMock(side_effect=side_effects)
    return agent


@patch("docgrity.agents.base.asyncio.sleep", new_callable=AsyncMock)
async def test_retries_transient_then_succeeds(mock_sleep):
    agent = _agent([_ProviderError(503), _ProviderError(429), _Result(Out(value=7))])
    output = await run_agent(agent, "payload")
    assert output.value == 7
    assert agent.run.await_count == 3
    assert mock_sleep.await_count == 2
    # Exponential backoff: 2s then 4s.
    assert [c.args[0] for c in mock_sleep.await_args_list] == [2.0, 4.0]


@patch("docgrity.agents.base.asyncio.sleep", new_callable=AsyncMock)
async def test_gives_up_after_max_attempts(mock_sleep):
    agent = _agent(_ProviderError(503))
    with pytest.raises(_ProviderError):
        await run_agent(agent, "payload", attempts=3)
    assert agent.run.await_count == 3


@patch("docgrity.agents.base.asyncio.sleep", new_callable=AsyncMock)
async def test_non_retryable_error_raises_immediately(mock_sleep):
    agent = _agent(_ProviderError(404))
    with pytest.raises(_ProviderError):
        await run_agent(agent, "payload")
    assert agent.run.await_count == 1
    mock_sleep.assert_not_awaited()


@patch("docgrity.agents.base.asyncio.sleep", new_callable=AsyncMock)
async def test_error_without_status_code_raises_immediately(mock_sleep):
    agent = _agent(ValueError("bad output"))
    with pytest.raises(ValueError):
        await run_agent(agent, "payload")
    assert agent.run.await_count == 1
