"""Tool registration: prediction records and their calibration (3 tools).

A prediction is written open by `predict`, settled by `resolve_prediction`
against evidence the caller supplies, and scored by `calibration`
(issue #597, ADR-1076).

source: ADR-1076"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import calibration, predict, resolve_prediction
from mcp_server.handlers._tool_meta import tool_kwargs
from mcp_server.tool_error_handler import safe_handler


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "predict": predict.schema,
    "resolve_prediction": resolve_prediction.schema,
    "calibration": calibration.schema,
}


def register(mcp: MCPServer) -> None:
    """Register the prediction tools."""
    _register_predict(mcp)
    _register_resolve_prediction(mcp)
    _register_calibration(mcp)


def _register_predict(mcp: MCPServer) -> None:
    @mcp.tool(name="predict", **tool_kwargs(predict.schema))
    async def tool_predict(
        claim: str,
        prediction: str,
        test: str,
        confidence: float,
        domain: str | None = None,
        directory: str | None = None,
        memory_id: int | None = None,
    ) -> dict[str, Any]:
        """Record a falsifiable prediction before its outcome is known."""
        return await safe_handler(
            predict.handler,
            {
                "claim": claim,
                "prediction": prediction,
                "test": test,
                "confidence": confidence,
                "domain": domain,
                "directory": directory,
                "memory_id": memory_id,
            },
            tool_name="predict",
        )


def _register_resolve_prediction(mcp: MCPServer) -> None:
    @mcp.tool(name="resolve_prediction", **tool_kwargs(resolve_prediction.schema))
    async def tool_resolve_prediction(
        prediction_id: int,
        verdict: str,
        observed: str,
        source_kind: str,
        source_ref: str,
    ) -> dict[str, Any]:
        """Settle an open prediction against the evidence that decided it."""
        return await safe_handler(
            resolve_prediction.handler,
            {
                "prediction_id": prediction_id,
                "verdict": verdict,
                "observed": observed,
                "source_kind": source_kind,
                "source_ref": source_ref,
            },
            tool_name="resolve_prediction",
        )


def _register_calibration(mcp: MCPServer) -> None:
    @mcp.tool(name="calibration", **tool_kwargs(calibration.schema))
    async def tool_calibration(domain: str | None = None) -> dict[str, Any]:
        """Score resolved predictions: Brier score and reliability bands."""
        return await safe_handler(
            calibration.handler,
            {"domain": domain},
            tool_name="calibration",
        )
