"""Immutable strategy configuration versions and approval control."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.strategy.catalog import STRATEGY_CATALOG, get_strategy_meta
from app.strategy.config_store import validate_strategy_params

if TYPE_CHECKING:
    from app.core.auth import Principal


class StrategyVersionError(ValueError):
    def __init__(
        self,
        message: str,
        code: str = "STRATEGY_VERSION_INVALID",
        status_code: int = 400,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class StrategyVersionService:
    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _meta(cls, strategy_type: str) -> dict[str, Any]:
        meta = get_strategy_meta(strategy_type)
        if not meta:
            raise StrategyVersionError(
                f"策略不存在: {strategy_type}", "STRATEGY_NOT_FOUND", 404
            )
        return meta

    @classmethod
    def catalog_hash(cls, strategy_type: str) -> str:
        meta = cls._meta(strategy_type)
        payload = {
            "type": meta["type"],
            "requirement_profile": meta["requirement_profile"],
            "required_fields": meta["required_fields"],
            "default_params": meta["default_params"],
            "param_schema": meta["param_schema"],
        }
        return hashlib.sha256(cls._canonical_json(payload).encode("utf-8")).hexdigest()

    @classmethod
    def config_hash(
        cls,
        *,
        strategy_type: str,
        enabled: bool,
        params: dict[str, Any],
        catalog_hash: str,
    ) -> str:
        payload = {
            "strategy_type": strategy_type,
            "enabled": enabled,
            "params": params,
            "catalog_hash": catalog_hash,
        }
        return hashlib.sha256(cls._canonical_json(payload).encode("utf-8")).hexdigest()

    @classmethod
    def _normalized_params(
        cls, strategy_type: str, params: Any
    ) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise StrategyVersionError(
                "策略版本参数不可用", "STRATEGY_VERSION_PARAMS_INVALID", 409
            )
        try:
            return validate_strategy_params(strategy_type, params)
        except ValueError as exc:
            raise StrategyVersionError(
                str(exc), "STRATEGY_VERSION_PARAMS_INVALID", 409
            ) from exc

    @classmethod
    def _verified_config(
        cls,
        *,
        strategy_type: str,
        enabled: Any,
        params: Any,
        catalog_hash: Any,
        config_hash: Any,
    ) -> tuple[bool, dict[str, Any]]:
        if type(enabled) is not bool:
            raise StrategyVersionError(
                "策略版本启用状态不可用", "STRATEGY_VERSION_INVALID", 409
            )
        current_catalog_hash = cls.catalog_hash(strategy_type)
        if catalog_hash != current_catalog_hash:
            raise StrategyVersionError(
                "策略目录契约已变化，当前版本不可启用",
                "STRATEGY_CATALOG_DRIFT",
                409,
            )
        normalized_params = cls._normalized_params(strategy_type, params)
        expected_config_hash = cls.config_hash(
            strategy_type=strategy_type,
            enabled=enabled,
            params=normalized_params,
            catalog_hash=current_catalog_hash,
        )
        if config_hash != expected_config_hash:
            raise StrategyVersionError(
                "策略版本 Hash 不一致", "STRATEGY_VERSION_HASH_MISMATCH", 409
            )
        return enabled, normalized_params

    @classmethod
    def _base_entry(cls, strategy_type: str) -> dict[str, Any]:
        meta = cls._meta(strategy_type)
        defaults = cls._normalized_params(strategy_type, dict(meta["default_params"]))
        return {
            "type": strategy_type,
            "name": meta["name"],
            "description": meta["description"],
            "scenario": meta["scenario"],
            "requirement_profile": meta["requirement_profile"],
            "required_fields": list(meta["required_fields"]),
            "param_schema": meta["param_schema"],
            "default_params": defaults,
        }

    @classmethod
    def _entry_from_row(
        cls, strategy_type: str, row: dict[str, Any] | None
    ) -> dict[str, Any]:
        entry = cls._base_entry(strategy_type)
        if row is None:
            return {
                **entry,
                "strategy_id": None,
                "revision": 0,
                "version": None,
                "version_id": None,
                "enabled": False,
                "params": entry["default_params"],
                "config_status": "unconfigured",
                "params_source": "catalog_default_not_active",
                "approval_status": None,
                "config_hash": None,
                "catalog_hash": None,
            }

        revision = row.get("revision")
        if type(revision) is not int or revision < 0:
            return {
                **entry,
                "strategy_id": row.get("strategy_id"),
                "revision": None,
                "version": None,
                "version_id": None,
                "enabled": False,
                "params": None,
                "config_status": "invalid",
                "params_source": "unavailable",
                "approval_status": None,
                "config_hash": None,
                "catalog_hash": None,
                "error_code": "STRATEGY_HEAD_INVALID",
            }

        active_version_id = row.get("active_version_id")
        if active_version_id is not None:
            if (
                row.get("effective_version_id") != active_version_id
                or row.get("effective_version") != revision
                or row.get("effective_approval_status") != "approved"
            ):
                return {
                    **entry,
                    "strategy_id": row.get("strategy_id"),
                    "revision": revision,
                    "version": None,
                    "version_id": None,
                    "enabled": False,
                    "params": None,
                    "config_status": "invalid",
                    "params_source": "unavailable",
                    "approval_status": row.get("effective_approval_status"),
                    "config_hash": None,
                    "catalog_hash": None,
                    "error_code": "STRATEGY_ACTIVE_VERSION_INVALID",
                }
            try:
                enabled, params = cls._verified_config(
                    strategy_type=strategy_type,
                    enabled=row.get("effective_enabled"),
                    params=row.get("effective_params"),
                    catalog_hash=row.get("effective_catalog_hash"),
                    config_hash=row.get("effective_config_hash"),
                )
            except StrategyVersionError as exc:
                return {
                    **entry,
                    "strategy_id": row.get("strategy_id"),
                    "revision": revision,
                    "version": row.get("effective_version"),
                    "version_id": active_version_id,
                    "enabled": False,
                    "params": None,
                    "config_status": "invalid",
                    "params_source": "unavailable",
                    "approval_status": "approved",
                    "config_hash": row.get("effective_config_hash"),
                    "catalog_hash": row.get("effective_catalog_hash"),
                    "error_code": exc.code,
                }
            return {
                **entry,
                "strategy_id": row.get("strategy_id"),
                "revision": revision,
                "version": row.get("effective_version"),
                "version_id": active_version_id,
                "enabled": enabled,
                "params": params,
                "config_status": "approved" if enabled else "approved_disabled",
                "params_source": "approved_version",
                "approval_status": "approved",
                "config_hash": row.get("effective_config_hash"),
                "catalog_hash": row.get("effective_catalog_hash"),
            }

        if row.get("latest_version_id") is None:
            return {
                **entry,
                "strategy_id": row.get("strategy_id"),
                "revision": revision,
                "version": None,
                "version_id": None,
                "enabled": False,
                "params": entry["default_params"],
                "config_status": "unconfigured",
                "params_source": "catalog_default_not_active",
                "approval_status": None,
                "config_hash": None,
                "catalog_hash": None,
            }

        if row.get("latest_approval_status") != "pending":
            return {
                **entry,
                "strategy_id": row.get("strategy_id"),
                "revision": revision,
                "version": row.get("latest_version"),
                "version_id": row.get("latest_version_id"),
                "enabled": False,
                "params": None,
                "config_status": "invalid",
                "params_source": "unavailable",
                "approval_status": row.get("latest_approval_status"),
                "config_hash": row.get("latest_config_hash"),
                "catalog_hash": row.get("latest_catalog_hash"),
                "error_code": "STRATEGY_HEAD_INVALID",
            }

        try:
            _enabled, params = cls._verified_config(
                strategy_type=strategy_type,
                enabled=row.get("latest_enabled"),
                params=row.get("latest_params"),
                catalog_hash=row.get("latest_catalog_hash"),
                config_hash=row.get("latest_config_hash"),
            )
        except StrategyVersionError as exc:
            return {
                **entry,
                "strategy_id": row.get("strategy_id"),
                "revision": revision,
                "version": row.get("latest_version"),
                "version_id": row.get("latest_version_id"),
                "enabled": False,
                "params": None,
                "config_status": "invalid",
                "params_source": "unavailable",
                "approval_status": "pending",
                "config_hash": row.get("latest_config_hash"),
                "catalog_hash": row.get("latest_catalog_hash"),
                "error_code": exc.code,
            }
        return {
            **entry,
            "strategy_id": row.get("strategy_id"),
            "revision": revision,
            "version": row.get("latest_version"),
            "version_id": row.get("latest_version_id"),
            "enabled": False,
            "params": params,
            "requested_enabled": row.get("latest_enabled"),
            "config_status": "pending_approval",
            "params_source": "pending_version_not_active",
            "approval_status": "pending",
            "config_hash": row.get("latest_config_hash"),
            "catalog_hash": row.get("latest_catalog_hash"),
        }

    async def list_configurations(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(
            text(
                """
                SELECT s.id AS strategy_id, s.strategy_type,
                       h.revision, h.active_version_id,
                       active.version_id AS effective_version_id,
                       active.version_number AS effective_version,
                       active.enabled AS effective_enabled,
                       active.params AS effective_params,
                       active.catalog_hash AS effective_catalog_hash,
                       active.config_hash AS effective_config_hash,
                       active_approval.status AS effective_approval_status,
                       latest.version_id AS latest_version_id,
                       latest.version_number AS latest_version,
                       latest.enabled AS latest_enabled,
                       latest.params AS latest_params,
                       latest.catalog_hash AS latest_catalog_hash,
                       latest.config_hash AS latest_config_hash,
                       latest_approval.status AS latest_approval_status
                FROM strategy.strategy_version_heads AS h
                JOIN strategy.strategies AS s ON s.id = h.strategy_id
                LEFT JOIN strategy.strategy_versions AS active
                    ON active.version_id = h.active_version_id
                    AND active.version_number = h.revision
                LEFT JOIN strategy.strategy_version_approvals AS active_approval
                    ON active_approval.version_id = active.version_id
                LEFT JOIN strategy.strategy_versions AS latest
                    ON latest.strategy_id = h.strategy_id
                    AND latest.version_number = h.revision
                LEFT JOIN strategy.strategy_version_approvals AS latest_approval
                    ON latest_approval.version_id = latest.version_id
                ORDER BY s.strategy_type, h.revision DESC, s.id
                """
            )
        )
        rows_by_type: dict[str, dict[str, Any]] = {}
        for raw_row in result.mappings().all():
            row = dict(raw_row)
            strategy_type = row.get("strategy_type")
            if strategy_type in STRATEGY_CATALOG and strategy_type not in rows_by_type:
                rows_by_type[strategy_type] = row
        return [
            self._entry_from_row(strategy_type, rows_by_type.get(strategy_type))
            for strategy_type in sorted(STRATEGY_CATALOG)
        ]

    async def get_configuration(
        self, db: AsyncSession, *, strategy_type: str
    ) -> dict[str, Any]:
        self._meta(strategy_type)
        items = await self.list_configurations(db)
        return next(item for item in items if item["type"] == strategy_type)

    async def resolve_enabled_snapshot(
        self, db: AsyncSession, *, strategy_type: str
    ) -> dict[str, Any]:
        entry = await self.get_configuration(db, strategy_type=strategy_type)
        if entry.get("config_status") != "approved" or entry.get("enabled") is not True:
            raise StrategyVersionError(
                f"策略未处于已审批启用状态: {strategy_type}",
                "STRATEGY_NOT_APPROVED_ENABLED",
                409,
            )
        return {
            "strategy_type": strategy_type,
            "strategy_id": entry["strategy_id"],
            "version_id": entry["version_id"],
            "version": entry["version"],
            "revision": entry["revision"],
            "params": entry["params"],
            "config_hash": entry["config_hash"],
            "catalog_hash": entry["catalog_hash"],
        }

    async def verify_active_snapshot(
        self, db: AsyncSession, *, snapshot: Any
    ) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            raise StrategyVersionError(
                "回测策略快照不可用", "STRATEGY_SNAPSHOT_INVALID", 409
            )
        strategy_type = snapshot.get("strategy_type")
        if not isinstance(strategy_type, str):
            raise StrategyVersionError(
                "回测策略快照缺少策略类型", "STRATEGY_SNAPSHOT_INVALID", 409
            )
        current = await self.resolve_enabled_snapshot(db, strategy_type=strategy_type)
        fields = (
            "strategy_id",
            "version_id",
            "version",
            "revision",
            "config_hash",
            "catalog_hash",
        )
        if any(snapshot.get(field) != current[field] for field in fields) or (
            self._canonical_json(snapshot.get("params"))
            != self._canonical_json(current["params"])
        ):
            raise StrategyVersionError(
                "回测策略快照已过期", "STRATEGY_SNAPSHOT_STALE", 409
            )
        return current

    @staticmethod
    def _require_submitter(principal: Principal) -> None:
        if principal.principal_type != "human" or principal.role != "strategy_admin":
            raise StrategyVersionError(
                "仅人工 strategy_admin 可提交策略版本",
                "STRATEGY_SUBMITTER_INVALID",
                403,
            )

    @staticmethod
    def _require_approver(principal: Principal) -> None:
        if principal.principal_type != "human" or principal.role != "risk_admin":
            raise StrategyVersionError(
                "仅人工 risk_admin 可审批策略版本",
                "STRATEGY_APPROVER_INVALID",
                403,
            )

    async def _load_or_create_head(
        self, db: AsyncSession, *, strategy_type: str
    ) -> dict[str, Any]:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:strategy_type))"),
            {"strategy_type": strategy_type},
        )
        subject_result = await db.execute(
            text(
                """
                SELECT id
                FROM strategy.strategies
                WHERE strategy_type = :strategy_type
                ORDER BY id
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"strategy_type": strategy_type},
        )
        subject = subject_result.mappings().first()
        if subject is None:
            meta = self._meta(strategy_type)
            inserted = await db.execute(
                text(
                    """
                    INSERT INTO strategy.strategies
                        (name, strategy_type, trade_mode, universe, config, is_active)
                    VALUES
                        (:name, :strategy_type, 'simulation', 'watchlist', '{}'::jsonb, FALSE)
                    RETURNING id
                    """
                ),
                {"name": meta["name"], "strategy_type": strategy_type},
            )
            subject = inserted.mappings().first()
        strategy_id = subject["id"]

        head_result = await db.execute(
            text(
                """
                SELECT strategy_id, revision, active_version_id
                FROM strategy.strategy_version_heads
                WHERE strategy_id = :strategy_id
                FOR UPDATE
                """
            ),
            {"strategy_id": strategy_id},
        )
        head = head_result.mappings().first()
        if head is None:
            await db.execute(
                text(
                    """
                    INSERT INTO strategy.strategy_version_heads
                        (strategy_id, revision, active_version_id)
                    VALUES (:strategy_id, 0, NULL)
                    """
                ),
                {"strategy_id": strategy_id},
            )
            return {"strategy_id": strategy_id, "revision": 0, "active_version_id": None}
        return dict(head)

    async def _load_active_version(
        self, db: AsyncSession, *, strategy_id: int, version_id: int
    ) -> dict[str, Any] | None:
        result = await db.execute(
            text(
                """
                SELECT version_id, version_number, enabled, params, catalog_hash, config_hash
                FROM strategy.strategy_versions
                WHERE strategy_id = :strategy_id AND version_id = :version_id
                """
            ),
            {"strategy_id": strategy_id, "version_id": version_id},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    async def _append_event(
        db: AsyncSession,
        *,
        version_id: int,
        event_type: str,
        actor_principal_id: str,
        payload: dict[str, Any],
    ) -> None:
        await db.execute(
            text(
                """
                INSERT INTO strategy.strategy_version_events
                    (version_id, event_type, actor_principal_id, payload)
                VALUES
                    (:version_id, :event_type, CAST(:actor_principal_id AS uuid),
                     CAST(:payload AS jsonb))
                """
            ),
            {
                "version_id": version_id,
                "event_type": event_type,
                "actor_principal_id": actor_principal_id,
                "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        )

    @staticmethod
    def _require_single_update(result: Any, code: str) -> None:
        rowcount = getattr(result, "rowcount", None)
        if rowcount is not None and rowcount != 1:
            raise StrategyVersionError(
                "策略版本状态已变化，请刷新后重试", code, 409
            )

    async def submit(
        self,
        db: AsyncSession,
        *,
        principal: Principal,
        strategy_type: str,
        expected_revision: int,
        enabled: bool | None,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self._require_submitter(principal)
        self._meta(strategy_type)
        if type(expected_revision) is not int or expected_revision < 0:
            raise StrategyVersionError(
                "expected_revision 必须是非负整数", "STRATEGY_REVISION_INVALID"
            )
        if enabled is not None and type(enabled) is not bool:
            raise StrategyVersionError("enabled 必须是布尔值")
        if params is not None and not isinstance(params, dict):
            raise StrategyVersionError("params 必须是对象")
        if enabled is None and params is None:
            raise StrategyVersionError(
                "策略更新必须包含 enabled 或 params", "STRATEGY_UPDATE_EMPTY"
            )

        head = await self._load_or_create_head(db, strategy_type=strategy_type)
        revision = head.get("revision")
        if type(revision) is not int or revision < 0:
            raise StrategyVersionError(
                "策略版本头不可用", "STRATEGY_HEAD_INVALID", 409
            )
        if expected_revision != revision:
            raise StrategyVersionError(
                "策略版本已变化，请刷新后重试", "STRATEGY_REVISION_CONFLICT", 409
            )

        stored_enabled = False
        base_params = self._base_entry(strategy_type)["default_params"]
        active_version_id = head.get("active_version_id")
        if active_version_id is not None:
            active = await self._load_active_version(
                db,
                strategy_id=head["strategy_id"],
                version_id=active_version_id,
            )
            if active is None:
                raise StrategyVersionError(
                    "当前策略版本不可用", "STRATEGY_ACTIVE_VERSION_INVALID", 409
                )
            stored_enabled, base_params = self._verified_config(
                strategy_type=strategy_type,
                enabled=active["enabled"],
                params=active["params"],
                catalog_hash=active["catalog_hash"],
                config_hash=active["config_hash"],
            )

        resolved_enabled = stored_enabled if enabled is None else enabled
        resolved_params = self._normalized_params(
            strategy_type, {**base_params, **(params or {})}
        )
        catalog_hash = self.catalog_hash(strategy_type)
        config_hash = self.config_hash(
            strategy_type=strategy_type,
            enabled=resolved_enabled,
            params=resolved_params,
            catalog_hash=catalog_hash,
        )
        version_number = revision + 1
        inserted = await db.execute(
            text(
                """
                INSERT INTO strategy.strategy_versions
                    (strategy_id, version_number, enabled, params, catalog_hash,
                     config_hash, requester_principal_id)
                VALUES
                    (:strategy_id, :version_number, :enabled, CAST(:params AS jsonb),
                     :catalog_hash, :config_hash, CAST(:principal_id AS uuid))
                RETURNING version_id
                """
            ),
            {
                "strategy_id": head["strategy_id"],
                "version_number": version_number,
                "enabled": resolved_enabled,
                "params": self._canonical_json(resolved_params),
                "catalog_hash": catalog_hash,
                "config_hash": config_hash,
                "principal_id": principal.principal_id,
            },
        )
        version_row = inserted.mappings().first()
        if version_row is None or type(version_row.get("version_id")) is not int:
            raise StrategyVersionError(
                "策略版本创建未返回有效标识", "STRATEGY_VERSION_CREATE_FAILED", 503,
                retryable=True,
            )
        version_id = version_row["version_id"]
        await db.execute(
            text(
                """
                INSERT INTO strategy.strategy_version_approvals (version_id, status)
                VALUES (:version_id, 'pending')
                """
            ),
            {"version_id": version_id},
        )
        await self._append_event(
            db,
            version_id=version_id,
            event_type="submitted",
            actor_principal_id=principal.principal_id,
            payload={
                "strategy_type": strategy_type,
                "version": version_number,
                "enabled": resolved_enabled,
                "config_hash": config_hash,
                "catalog_hash": catalog_hash,
            },
        )
        head_update = await db.execute(
            text(
                """
                UPDATE strategy.strategy_version_heads
                SET revision = :revision, active_version_id = NULL, updated_at = NOW()
                WHERE strategy_id = :strategy_id AND revision = :expected_revision
                """
            ),
            {
                "strategy_id": head["strategy_id"],
                "revision": version_number,
                "expected_revision": revision,
            },
        )
        self._require_single_update(head_update, "STRATEGY_REVISION_CONFLICT")
        return {
            **self._base_entry(strategy_type),
            "strategy_id": head["strategy_id"],
            "revision": version_number,
            "version": version_number,
            "version_id": version_id,
            "enabled": False,
            "params": resolved_params,
            "requested_enabled": resolved_enabled,
            "config_status": "pending_approval",
            "params_source": "pending_version_not_active",
            "approval_status": "pending",
            "config_hash": config_hash,
            "catalog_hash": catalog_hash,
        }

    async def approve(
        self,
        db: AsyncSession,
        *,
        principal: Principal,
        version_id: int,
    ) -> dict[str, Any]:
        self._require_approver(principal)
        result = await db.execute(
            text(
                """
                SELECT s.id AS strategy_id, s.strategy_type,
                       h.revision, h.active_version_id,
                       v.version_id, v.version_number, v.enabled, v.params,
                       v.catalog_hash, v.config_hash, v.requester_principal_id,
                       a.status AS approval_status
                FROM strategy.strategy_versions AS v
                JOIN strategy.strategy_version_heads AS h ON h.strategy_id = v.strategy_id
                JOIN strategy.strategies AS s ON s.id = v.strategy_id
                JOIN strategy.strategy_version_approvals AS a ON a.version_id = v.version_id
                WHERE v.version_id = :version_id
                FOR UPDATE
                """
            ),
            {"version_id": version_id},
        )
        row = result.mappings().first()
        if row is None:
            raise StrategyVersionError("策略版本不存在", "STRATEGY_VERSION_NOT_FOUND", 404)
        row = dict(row)
        if row.get("approval_status") != "pending":
            raise StrategyVersionError(
                "策略版本不处于待审批状态", "STRATEGY_VERSION_NOT_PENDING", 409
            )
        if str(row.get("requester_principal_id")) == principal.principal_id:
            raise StrategyVersionError(
                "提交人不能审批自己的策略版本",
                "STRATEGY_APPROVAL_SEPARATION",
                403,
            )
        if (
            row.get("revision") != row.get("version_number")
            or row.get("active_version_id") is not None
        ):
            raise StrategyVersionError(
                "策略版本已过期，不能审批", "STRATEGY_VERSION_STALE", 409
            )
        enabled, params = self._verified_config(
            strategy_type=row["strategy_type"],
            enabled=row.get("enabled"),
            params=row.get("params"),
            catalog_hash=row.get("catalog_hash"),
            config_hash=row.get("config_hash"),
        )
        approval_update = await db.execute(
            text(
                """
                UPDATE strategy.strategy_version_approvals
                SET status = 'approved', approver_principal_id = CAST(:principal_id AS uuid),
                    approved_at = NOW()
                WHERE version_id = :version_id AND status = 'pending'
                """
            ),
            {"version_id": version_id, "principal_id": principal.principal_id},
        )
        self._require_single_update(approval_update, "STRATEGY_VERSION_NOT_PENDING")
        head_update = await db.execute(
            text(
                """
                UPDATE strategy.strategy_version_heads
                SET active_version_id = :version_id, updated_at = NOW()
                WHERE strategy_id = :strategy_id AND revision = :revision
                    AND active_version_id IS NULL
                """
            ),
            {
                "version_id": version_id,
                "strategy_id": row["strategy_id"],
                "revision": row["revision"],
            },
        )
        self._require_single_update(head_update, "STRATEGY_VERSION_STALE")
        await self._append_event(
            db,
            version_id=version_id,
            event_type="approved",
            actor_principal_id=principal.principal_id,
            payload={
                "strategy_type": row["strategy_type"],
                "version": row["version_number"],
                "config_hash": row["config_hash"],
            },
        )
        return {
            **self._base_entry(row["strategy_type"]),
            "strategy_id": row["strategy_id"],
            "revision": row["revision"],
            "version": row["version_number"],
            "version_id": version_id,
            "enabled": enabled,
            "params": params,
            "config_status": "approved" if enabled else "approved_disabled",
            "params_source": "approved_version",
            "approval_status": "approved",
            "config_hash": row["config_hash"],
            "catalog_hash": row["catalog_hash"],
        }
