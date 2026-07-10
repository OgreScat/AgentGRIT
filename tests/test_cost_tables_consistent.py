"""Cost-table consistency -- router.MODEL_COSTS and planner.MODEL_COST_PER_1K
must agree on the models they share, so a workflow plan's dollars and a routing
alternative's dollars are the same unit. Both are blended $/1k estimates; drift
between them is a Zeroth-Law inconsistency this test exists to prevent.
"""

from src.execution.router import MODEL_COSTS
from src.workflow.planner import MODEL_COST_PER_1K, StageModel

# Which router key corresponds to which planner StageModel.
_SHARED = {
    "ollama": StageModel.OLLAMA,
    "perplexity": StageModel.PERPLEXITY,
    "claude-haiku": StageModel.HAIKU,
    "claude-sonnet": StageModel.SONNET,
    "claude-opus": StageModel.OPUS,
}


def test_shared_model_costs_match():
    mismatches = []
    for router_key, stage in _SHARED.items():
        r = MODEL_COSTS.get(router_key)
        p = MODEL_COST_PER_1K.get(stage)
        if r is None or p is None or abs(r - p) > 1e-9:
            mismatches.append(f"{router_key}: router={r} planner={p}")
    assert not mismatches, "cost tables drifted: " + "; ".join(mismatches)


def test_all_shared_keys_present_both_sides():
    for router_key, stage in _SHARED.items():
        assert router_key in MODEL_COSTS, f"{router_key} missing from MODEL_COSTS"
        assert stage in MODEL_COST_PER_1K, f"{stage} missing from MODEL_COST_PER_1K"
