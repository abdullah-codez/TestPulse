"""
TestPulse — Unit Tests for Milestone 3: Pipeline Agents & LLM Router
Verifies:
1. ContextGatherer.select_targets across "unit", "integration", and "regression" strategies.
2. ContextGatherer.build_bundle verifying clean separation of focal code, dependencies,
   descriptive context (including README.md 50% discount rule), and strategy mock policies.
3. LLMRouter model failover on 429 RateLimitError, 503, and timeouts with code-fence cleanup.
4. TestPlanner.generate_plan returning valid BehaviorMatrix for unit, integration, and regression.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from litellm.exceptions import RateLimitError, ServiceUnavailableError, Timeout

from testpulse.graph.graph_builder import build_graph
from testpulse.llm.router import LLMRouter, clean_json_code_fences
from testpulse.models.schemas import BehaviorMatrix, ContextBundle
from testpulse.pipeline.context_gatherer import ContextGatherer, find_conftest_fixtures
from testpulse.pipeline.planner import TestPlanner
from testpulse.rag.chunker import chunk_repository
from testpulse.rag.indexer import index_chunks

FIXTURE_PATH = Path("tests/fixtures/sample_fastapi").resolve()


def _mock_embedder(texts: list[str]) -> list[list[float]]:
    """Deterministic embedding vector for testing retrieval."""
    vectors: list[list[float]] = []
    for text in texts:
        t = text.lower()
        vec = [0.0] * 8
        if "discount" in t or "50%" in t:
            vec[0] = 1.0
            vec[1] = 0.5
        elif "order" in t or "customer" in t:
            vec[2] = 1.0
            vec[3] = 0.5
        else:
            digest = hashlib.md5(t.encode("utf-8")).digest()
            for idx in range(8):
                vec[idx] = float(digest[idx]) / 255.0

        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        vectors.append(vec)
    return vectors


def _single_mock_embedder(text: str) -> list[float]:
    return _mock_embedder([text])[0]


# ---------------------------------------------------------------------------
# 1. Target Queue Prioritization Tests
# ---------------------------------------------------------------------------

def test_select_targets_unit_strategy() -> None:
    """Verifies that unit strategy selects non-trivial business logic and filters trivial getters."""
    G, _ = build_graph(FIXTURE_PATH)
    targets = ContextGatherer.select_targets(G, strategy="unit", max_targets=10)

    assert len(targets) > 0
    # Must contain complex calculate_discount
    assert any("calculate_discount" in t for t in targets)

    # Must NOT contain trivial getters (cyclomatic_complexity <= 1 and < 6 lines)
    assert not any("get_service_name" in t for t in targets)
    assert not any("get_base_tax_rate" in t for t in targets)


def test_select_targets_integration_strategy() -> None:
    """Verifies that integration strategy selects FastAPI route entry points (top-down)."""
    G, _ = build_graph(FIXTURE_PATH)
    targets = ContextGatherer.select_targets(G, strategy="integration", max_targets=10)

    assert len(targets) > 0
    # Entry points create_order and get_order_by_id must be prioritized
    assert any("create_order" in t for t in targets)
    assert any("get_order_by_id" in t for t in targets)

    # Unit business logic service function should NOT be in integration entry point targets
    assert not any("calculate_discount" in t for t in targets)


def test_select_targets_regression_strategy() -> None:
    """Verifies that regression strategy computes blast radius around modified symbols."""
    G, _ = build_graph(FIXTURE_PATH)
    labels = {d.get("label"): n for n, d in G.nodes(data=True)}
    calc_nid = labels["calculate_discount"]
    create_order_nid = labels["create_order"]

    targets = ContextGatherer.select_targets(
        G,
        strategy="regression",
        modified_nodes=[calc_nid],
        max_targets=10,
    )

    # Modified node must be prioritized first
    assert targets[0] == calc_nid
    # Caller within blast radius must be included
    assert create_order_nid in targets


def test_select_targets_regression_requires_modified_nodes() -> None:
    """Verifies that regression strategy without modified_nodes raises ValueError."""
    G, _ = build_graph(FIXTURE_PATH)
    with pytest.raises(ValueError, match="modified_nodes must be provided"):
        ContextGatherer.select_targets(G, strategy="regression", modified_nodes=None)

    with pytest.raises(ValueError, match="modified_nodes must be provided"):
        ContextGatherer.select_targets(G, strategy="regression", modified_nodes=[])


# ---------------------------------------------------------------------------
# 2. Context Bundle Assembly Tests
# ---------------------------------------------------------------------------

def test_build_bundle_unit_with_clean_separation(tmp_path: Path) -> None:
    """
    Verifies build_bundle cleanly separates:
    - focal_code (target AST chunk)
    - dependency_code (Pipeline A callers/callees/classes)
    - descriptive_context (Pipeline B semantic sweeper, including README.md 50% discount rule)
    - mock_policy (unit isolation, forbidding target mocks)
    """
    G, _ = build_graph(FIXTURE_PATH)
    chunks = chunk_repository(G, workspace_path=FIXTURE_PATH)

    qdrant_dir = tmp_path / "qdrant_unit"
    index_chunks(
        chunks=chunks,
        collection_name="testpulse_codebase",
        client_path=qdrant_dir,
        embedder_fn=_mock_embedder,
    )

    gatherer = ContextGatherer(workspace_path=FIXTURE_PATH, qdrant_path=qdrant_dir)
    target_nid = "services/discount_service.py::DiscountService::calculate_discount"

    bundle = gatherer.build_bundle(
        G=G,
        target_node_id=target_nid,
        strategy="unit",
        client_path=qdrant_dir,
        embedder_fn=_single_mock_embedder,
    )

    assert isinstance(bundle, ContextBundle)
    assert bundle.strategy == "unit"
    assert bundle.target_symbol == "calculate_discount"
    assert bundle.source_file == "services/discount_service.py"
    assert bundle.line_span[0] > 0 and bundle.line_span[1] >= bundle.line_span[0]
    assert bundle.cyclomatic_complexity >= 3

    # 1. Focal code check
    assert "def calculate_discount" in bundle.focal_code
    assert "# [TestPulse cAST Chunk]" in bundle.focal_code

    # 2. Pipeline A Dependency code check
    assert len(bundle.dependency_code) > 0
    dep_text = "\n".join(bundle.dependency_code)
    # create_order or DiscountService class should be in Pipeline A dependencies
    assert "DiscountService" in dep_text or "create_order" in dep_text

    # 3. Pipeline B Descriptive context check (must include README.md 50% discount rule)
    assert len(bundle.descriptive_context) > 0
    desc_text = "\n".join(bundle.descriptive_context)
    assert "Discounts cannot exceed 50%" in desc_text or "50%" in desc_text
    assert "# [TestPulse Descriptive Chunk]" in desc_text

    # 4. Mock policy checks
    assert "mock external DB" in bundle.mock_policy.get("isolation", "")
    assert "calculate_discount" in bundle.mock_policy.get("forbid_mock", "")


def test_build_bundle_integration_strategy(tmp_path: Path) -> None:
    """Verifies build_bundle for integration strategy (hop_depth=2, forbidding internal mocks)."""
    G, _ = build_graph(FIXTURE_PATH)
    chunks = chunk_repository(G, workspace_path=FIXTURE_PATH)

    qdrant_dir = tmp_path / "qdrant_integration"
    index_chunks(
        chunks=chunks,
        collection_name="testpulse_codebase",
        client_path=qdrant_dir,
        embedder_fn=_mock_embedder,
    )

    bundle = ContextGatherer.build_bundle(
        G=G,
        target_node_id="routes/orders.py::create_order",
        strategy="integration",
        workspace_path=FIXTURE_PATH,
        client_path=qdrant_dir,
        embedder_fn=_single_mock_embedder,
    )

    assert bundle.strategy == "integration"
    assert bundle.target_symbol == "create_order"
    assert "create_order" in bundle.focal_code
    assert "SQLite" in bundle.mock_policy.get("isolation", "")
    assert "Do not mock internal services" in bundle.mock_policy.get("forbid_mock", "")


def test_build_bundle_regression_strategy(tmp_path: Path) -> None:
    """Verifies build_bundle for regression strategy includes Fail-to-Pass requirement."""
    G, _ = build_graph(FIXTURE_PATH)
    bundle = ContextGatherer.build_bundle(
        G=G,
        target_node_id="services/discount_service.py::DiscountService::calculate_discount",
        strategy="regression",
        workspace_path=FIXTURE_PATH,
        client_path=tmp_path / "qdrant_empty",
        embedder_fn=_single_mock_embedder,
    )

    assert bundle.strategy == "regression"
    assert "Fail-to-Pass" in bundle.mock_policy.get("fail_to_pass", "")
    assert "Fail-to-Pass" in bundle.mock_policy.get("isolation", "")


def test_find_conftest_fixtures(tmp_path: Path) -> None:
    """Verifies automatic discovery of pytest fixtures in conftest.py."""
    conftest_content = (
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def sample_db():\n"
        "    return 'mock_db'\n\n"
        "@pytest.fixture()\n"
        "def order_client(sample_db):\n"
        "    return sample_db\n"
    )
    conftest_file = tmp_path / "conftest.py"
    conftest_file.write_text(conftest_content, encoding="utf-8")

    fixtures = find_conftest_fixtures(tmp_path)
    assert "sample_db()" in fixtures
    assert "order_client(sample_db)" in fixtures


# ---------------------------------------------------------------------------
# 3. Resilient LLM Router Tests
# ---------------------------------------------------------------------------

def test_clean_json_code_fences() -> None:
    """Verifies stripping of markdown code fences and extraction of inner JSON."""
    # Standard markdown fence
    fenced = "```json\n{\"key\": \"value\"}\n```"
    assert clean_json_code_fences(fenced) == '{"key": "value"}'

    # Fenced without language tag
    fenced_raw = "```\n{\"key\": \"value\"}\n```"
    assert clean_json_code_fences(fenced_raw) == '{"key": "value"}'

    # Conversational text wrapping JSON
    wrapped = "Here is the plan:\n```json\n{\"key\": 123}\n```\nHope this helps!"
    assert clean_json_code_fences(wrapped) == '{"key": 123}'

    # Raw JSON without fences
    raw = '{"key": "value"}'
    assert clean_json_code_fences(raw) == '{"key": "value"}'


def test_router_model_failover_on_429() -> None:
    """Verifies that LLMRouter catches HTTP 429 RateLimitError and fails over to the next model."""
    mock_response_success = MagicMock()
    mock_response_success.choices = [
        MagicMock(message=MagicMock(content='{"status": "ok"}'))
    ]

    mock_rate_limit = RateLimitError(
        message="429 Rate limit exceeded",
        llm_provider="openrouter",
        model="openrouter/nvidia/primary:free",
        response=MagicMock(status_code=429),
    )

    router = LLMRouter(
        tier1_models=["openrouter/nvidia/primary:free", "openrouter/meta-llama/fallback:free"],
        wait_seconds=0.01,  # Fast failover in unit tests
    )

    with patch("litellm.completion", side_effect=[mock_rate_limit, mock_response_success]) as mock_comp:
        response = router.complete(messages=[{"role": "user", "content": "test"}])

        assert response == mock_response_success
        assert mock_comp.call_count == 2
        # First call used primary model
        assert mock_comp.call_args_list[0].kwargs["model"] == "openrouter/nvidia/primary:free"
        # Second call used fallback model
        assert mock_comp.call_args_list[1].kwargs["model"] == "openrouter/meta-llama/fallback:free"


def test_router_model_failover_on_503_and_timeout() -> None:
    """Verifies that LLMRouter fails over on 503 ServiceUnavailableError and Timeout."""
    mock_response_success = MagicMock()
    mock_response_success.choices = [
        MagicMock(message=MagicMock(content='{"status": "success"}'))
    ]

    router = LLMRouter(
        tier1_models=["model1", "model2", "model3"],
        wait_seconds=0.01,
    )

    exc1 = ServiceUnavailableError(
        message="503 Service Unavailable",
        llm_provider="openrouter",
        model="model1",
        response=MagicMock(status_code=503),
    )
    exc2 = Timeout(
        message="Request timed out",
        model="model2",
        llm_provider="openrouter",
    )

    with patch("litellm.completion", side_effect=[exc1, exc2, mock_response_success]) as mock_comp:
        response = router.complete(messages=[{"role": "user", "content": "ping"}])

        assert response == mock_response_success
        assert mock_comp.call_count == 3


def test_router_exhausted_failover_raises() -> None:
    """Verifies that exhausting all models in tier raises RuntimeError."""
    router = LLMRouter(tier1_models=["model-a", "model-b"], wait_seconds=0.01)

    with (
        patch(
            "litellm.completion",
            side_effect=RateLimitError(
                message="429 Too Many Requests",
                llm_provider="openrouter",
                model="model-a",
                response=MagicMock(status_code=429),
            ),
        ),
        pytest.raises(RuntimeError, match="All LLM models in tier failed"),
    ):
        router.complete(messages=[{"role": "user", "content": "hello"}])




# ---------------------------------------------------------------------------
# 4. Test Planning Agent Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_behavior_matrix_json() -> str:
    """Returns valid JSON response representation of a BehaviorMatrix."""
    data = {
        "strategy": "unit",
        "target_node_id": "services/discount_service.py::DiscountService::calculate_discount",
        "target_symbol": "calculate_discount",
        "cases": [
            {
                "id": "CASE-1",
                "category": "happy",
                "description": "Standard tier order over $100 receives 5% discount",
                "inputs": {"subtotal": 120.0, "customer_tier": "standard"},
                "expected_outcome": "6.0",
            },
            {
                "id": "CASE-2",
                "category": "boundary",
                "description": "Discount exceeds 50% cap, must be clamped to 50%",
                "inputs": {"subtotal": 100.0, "customer_tier": "vip", "coupon_percent": 60},
                "expected_outcome": "50.0",
            },
            {
                "id": "CASE-3",
                "category": "negative",
                "description": "Negative subtotal raises ValueError",
                "inputs": {"subtotal": -20.0, "customer_tier": "standard"},
                "expected_outcome": "Raises ValueError",
            },
        ],
        "mock_constraints": ["Never mock calculate_discount itself"],
        "uncovered_lines": [],
    }
    return json.dumps(data)


def test_test_planner_generate_plan_unit(sample_behavior_matrix_json: str) -> None:
    """Verifies TestPlanner synthesizes a valid unit BehaviorMatrix from ContextBundle."""
    bundle = ContextBundle(
        strategy="unit",
        target_node_id="services/discount_service.py::DiscountService::calculate_discount",
        target_symbol="calculate_discount",
        source_file="services/discount_service.py",
        line_span=(17, 59),
        cyclomatic_complexity=4,
        focal_code="def calculate_discount(self, subtotal, customer_tier):\n    ...",
        dependency_code=[],
        descriptive_context=["Discounts cannot exceed 50% of the total order amount."],
        mock_policy={"isolation": "Isolate in memory", "forbid_mock": "Never mock calculate_discount"},
        existing_fixtures=[],
    )

    mock_resp = MagicMock()
    # Simulate LLM wrapping in markdown fence
    mock_resp.choices = [
        MagicMock(message=MagicMock(content=f"```json\n{sample_behavior_matrix_json}\n```"))
    ]

    planner = TestPlanner()
    with patch("litellm.completion", return_value=mock_resp) as mock_comp:
        matrix = planner.generate_plan(bundle)

        assert isinstance(matrix, BehaviorMatrix)
        assert matrix.strategy == "unit"
        assert matrix.target_symbol == "calculate_discount"
        assert len(matrix.cases) == 3

        # Check case categories
        categories = {c.category for c in matrix.cases}
        assert "happy" in categories
        assert "boundary" in categories
        assert "negative" in categories

        # Verify prompt had unit-specific requirements and focal code
        sent_messages = mock_comp.call_args.kwargs["messages"]
        sys_msg = next(m["content"] for m in sent_messages if m["role"] == "system")
        user_msg = next(m["content"] for m in sent_messages if m["role"] == "user")

        assert "STRATEGY: UNIT TESTING" in sys_msg
        assert "branch coverage" in sys_msg
        assert "calculate_discount" in user_msg


def test_test_planner_integration_prompt_and_plan() -> None:
    """Verifies TestPlanner integration prompt demands HTTP status codes and DB verification."""
    bundle = ContextBundle(
        strategy="integration",
        target_node_id="routes/orders.py::create_order",
        target_symbol="create_order",
        source_file="routes/orders.py",
        line_span=(10, 35),
        cyclomatic_complexity=2,
        focal_code="@router.post('/orders')\ndef create_order(): ...",
        dependency_code=["class Order: ..."],
        descriptive_context=[],
        mock_policy={"isolation": "Exercise FastAPI TestClient -> SQLite"},
        existing_fixtures=[],
    )

    integration_matrix_json = json.dumps({
        "strategy": "integration",
        "target_node_id": "routes/orders.py::create_order",
        "target_symbol": "create_order",
        "cases": [
            {
                "id": "CASE-1",
                "category": "happy",
                "description": "POST valid order returns 201 and persists order in SQLite",
                "inputs": {"items": [{"name": "item1", "price": 50.0}]},
                "expected_outcome": "HTTP 201 Created with order ID",
            },
            {
                "id": "CASE-2",
                "category": "negative",
                "description": "POST invalid payload returns 422 Unprocessable Entity",
                "inputs": {"items": "invalid_format"},
                "expected_outcome": "HTTP 422 Validation Error",
            },
        ],
        "mock_constraints": ["Do not mock database"],
        "uncovered_lines": [],
    })

    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(message=MagicMock(content=integration_matrix_json))
    ]

    with patch("litellm.completion", return_value=mock_resp) as mock_comp:
        matrix = TestPlanner.generate_plan(bundle)

        assert matrix.strategy == "integration"
        assert len(matrix.cases) == 2
        assert any("201" in c.expected_outcome for c in matrix.cases)

        sys_msg = next(m["content"] for m in mock_comp.call_args.kwargs["messages"] if m["role"] == "system")
        assert "STRATEGY: INTEGRATION TESTING" in sys_msg
        assert "HTTP status code verification" in sys_msg


def test_test_planner_regression_prompt_and_plan() -> None:
    """Verifies TestPlanner regression prompt demands Fail-to-Pass reproducer case."""
    bundle = ContextBundle(
        strategy="regression",
        target_node_id="services/discount_service.py::DiscountService::calculate_discount",
        target_symbol="calculate_discount",
        source_file="services/discount_service.py",
        line_span=(17, 59),
        cyclomatic_complexity=4,
        focal_code="def calculate_discount(...): ...",
        dependency_code=[],
        descriptive_context=[],
        mock_policy={"isolation": "Require Fail-to-Pass reproduction"},
        existing_fixtures=[],
    )

    regression_matrix_json = json.dumps({
        "strategy": "regression",
        "target_node_id": "services/discount_service.py::DiscountService::calculate_discount",
        "target_symbol": "calculate_discount",
        "cases": [
            {
                "id": "CASE-F2P",
                "category": "boundary",
                "description": "Fail-to-Pass reproducer: 60% discount must be clamped to 50%",
                "inputs": {"subtotal": 100.0, "coupon_percent": 60},
                "expected_outcome": "50.0 (fails on buggy code returning 60.0)",
            }
        ],
        "mock_constraints": ["No mocks"],
        "uncovered_lines": [],
    })

    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(message=MagicMock(content=regression_matrix_json))
    ]

    with patch("litellm.completion", return_value=mock_resp) as mock_comp:
        matrix = TestPlanner.generate_plan(bundle)

        assert matrix.strategy == "regression"
        assert matrix.cases[0].id == "CASE-F2P"

        sys_msg = next(m["content"] for m in mock_comp.call_args.kwargs["messages"] if m["role"] == "system")
        assert "STRATEGY: REGRESSION TESTING" in sys_msg
        assert "Fail-to-Pass" in sys_msg
