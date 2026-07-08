from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"
    DEGRADED = "degraded"


class AgentResult(BaseModel):
    """统一 Agent 执行结果，供 Orchestrator 与日志层使用。"""

    agent_name: str
    model: str
    output: dict[str, Any]
    status: AgentStatus
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    error_msg: str | None = None

    model_config = {"use_enum_values": True}


class NeutralAgentOutput(BaseModel):
    """降级/中性输出的最小公共字段。"""

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str
    degraded: bool = Field(default=True, alias="_degraded")

    model_config = {"populate_by_name": True}