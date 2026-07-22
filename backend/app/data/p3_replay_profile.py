"""Draft-only P3 replay input profile contract."""

PROFILE_NAME = "P3_REPLAY_DUAL_MA_RAW_OHLCV_V1"
POLICY_VERSION = "p3-replay-dual-ma-input-v1"
PURPOSE = "p3_shadow_replay"
STATUS = "draft"
REQUIRED_FIELDS = ("trading_date", "open", "high", "low", "close", "volume", "amount", "adjustment", "trading_calendar", "corporate_action_status", "available_at", "dataset_hash", "batch_hash", "row_hash", "input_snapshot_hash")
OPTIONAL_FIELDS = ("turnover_rate", "provider_time", "fetched_at", "received_at", "evidence_ref")
FORBIDDEN_FIELDS = ("qfq", "hfq", "estimated_available_at", "realtime")

CONTRACT = {"purpose": PURPOSE, "status": STATUS, "raw_only": True, "required_fields": REQUIRED_FIELDS, "optional_fields": OPTIONAL_FIELDS, "forbidden_fields": FORBIDDEN_FIELDS, "pit": "available_at <= information_cutoff", "trading_calendar": "confirmed", "corporate_action": "verified", "hashes": ("dataset_hash", "batch_hash", "row_hash", "input_snapshot_hash"), "fail_closed": ("P3_INPUT_LINEAGE_UNVERIFIED", "P3_INPUT_AVAILABLE_AT_MISSING", "P3_INPUT_HASH_MISSING", "P3_INPUT_CALENDAR_UNVERIFIED", "P3_INPUT_CORPORATE_ACTION_UNVERIFIED")}


def is_runner_usable() -> bool:
    return False
