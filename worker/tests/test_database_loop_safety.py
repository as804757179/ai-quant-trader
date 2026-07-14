from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from services import maintenance_ops, portfolio_sync, stock_pool, strategy_pool


@pytest.mark.parametrize(
    "module",
    [maintenance_ops, portfolio_sync, stock_pool, strategy_pool],
)
def test_worker_database_engines_do_not_reuse_cross_loop_connections(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/test",
    )
    module._engine = None
    module._session_factory = None
    try:
        module._get_session_factory()
        assert isinstance(module._engine.pool, NullPool)
    finally:
        module._engine = None
        module._session_factory = None
