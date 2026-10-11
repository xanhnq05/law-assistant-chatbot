"""Test E2E: B1 (Orchestrator) → B2 (Cleaner) → B3 (Embedding) → B4 (Retrieval) → B5 (Context Builder).

Sau khi B5 chạy xong, in ra `LegalContext` (Pydantic contract) — đây chính là
đầu vào chính thức cho B6 (Generator) và B7 (Verifier).

Cách dùng:
    cd backend/services/rag-service
    python -m pytest tests/b2-b5-test/test_pipeline_to_b5.py -v -s
    # Hoặc:
    python tests/b2-b5-test/test_pipeline_to_b5.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Đảm bảo import được app.* khi chạy từ folder tests/
SERVICE_ROOT = Path(__file__).resolve().parents[2]  # backend/services/rag-service
BACKEND_ROOT = SERVICE_ROOT.parents[1]  # backend
TESTS_ROOT = Path(__file__).resolve().parents[1]  # backend/services/rag-service/tests
for p in (str(BACKEND_ROOT), str(SERVICE_ROOT), str(TESTS_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

from app.rag.engine import RagEngine  # noqa: E402
from app.rag.orchestrator import PipelineState, run_pipeline  # noqa: E402
from app.rag.schemas.legal_context import LegalContext  # noqa: E402
from app.rag.steps.cleaner import step_clean_query  # noqa: E402
from app.rag.steps.embedding import step_embed_cleaned_query  # noqa: E402
from app.rag.steps.retrieval import step_retrieve_hybrid  # noqa: E402
from app.rag.steps.context_builder import build_legal_context  # noqa: E402

from tests.b2_b5_test.test_inputs import TEST_CASES, TestCase  # noqa: E402


# ============================================================
# Helper: in ra LegalContext dạng JSON đẹp
# ============================================================
def _legal_context_to_dict(lc: LegalContext) -> dict:
    """Convert LegalContext (Pydantic) → dict để in/serialize."""
    return lc.model_dump(mode="json", exclude_none=False)


def _print_legal_context(lc: LegalContext, *, max_evidence: int = 5) -> None:
    """In ra LegalContext dạng human-readable."""
    print("\n" + "=" * 80)
    print(f"[LegalContext] intent={lc.request.intent!r}, "
          f"history_dependent={lc.request.history_dependent}")
    print(f"  resolved_query      = {lc.request.resolved_query!r}")
    print(f"  retrieval_policy    = {json.dumps(lc.request.retrieval_policy, ensure_ascii=False)}")
    print(f"  missing_facts       = {lc.stats.get('retrieval_policy', {}).get('missing_facts')}")
    print(f"  evidence_count      = {len(lc.evidence)}")
    print(f"  citation_count      = {len(lc.citations)}")
    print(f"  hierarchy_docs      = {len(lc.hierarchy.documents)}")
    print(f"  formatted_context   = {len(lc.formatted_context)} chars")

    # In stats.expansion_executed nếu có
    if "expansion_executed" in lc.stats:
        print(f"  expansion_executed  = {lc.stats['expansion_executed']}")

    # In top N evidence
    print(f"\n  --- Top {min(max_evidence, len(lc.evidence))} evidence ---")
    for i, ev in enumerate(lc.evidence[:max_evidence], start=1):
        print(f"  [{i}] {ev.evidence_id} | {ev.node_type} | "
              f"active={ev.is_active} | kind={ev.expansion_kind}")
        print(f"      citation: {ev.hierarchy_path}")
        if ev.amendments:
            print(f"      amendments: {ev.amendments}")
        # In content (rút gọn)
        content_preview = (ev.content or ev.context_block)[:200].replace("\n", " ")
        print(f"      content: {content_preview}...")

    # In hierarchy summary
    if lc.hierarchy.expanded:
        print(f"\n  hierarchy.expanded=True, summary={lc.hierarchy.expansion_summary!r}")
    print("=" * 80)


# ============================================================
# Fixture: engine thật (cần ENV đầy đủ)
# ============================================================
@pytest.fixture(scope="module")
def real_engine():
    """Khởi tạo RagEngine thật - cần GROQ/PINECONE/NEO4J trong ENV.

    Nếu thiếu ENV → skip toàn bộ test (không fail).
    """
    required = ("GROQ_API_KEY", "PINECONE_API_KEY", "NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Thiếu ENV: {missing}. Test cần RagEngine thật để chạy B1→B5.")

    eng = RagEngine()
    eng.init()
    yield eng
    eng.close()


# ============================================================
# TEST 1: Chạy full B1→B5 cho 1 testcase
# ============================================================
@pytest.mark.parametrize("case", TEST_CASES, ids=[c.id for c in TEST_CASES])
def test_pipeline_to_b5(real_engine, case: TestCase):
    """Chạy pipeline B1→B5, in ra LegalContext, assert các field chính.

    NOTE: B6/B7 KHÔNG chạy (dùng verify=False để skip B7, dùng custom runner
    để skip B6). Ta dùng `run_pipeline` với `verify=False` rồi dừng ở B5.
    Tuy nhiên `run_pipeline` hiện tại luôn chạy đủ B6. Để test riêng B1→B5,
    ta gọi trực tiếp các step trong orchestrator.
    """
    # B1: Build PipelineState
    from app.rag.orchestrator import PipelineState
    from app.rag.steps.cleaner import step_clean_query
    from app.rag.steps.embedding import step_embed_cleaned_query
    from app.rag.steps.retrieval import step_retrieve_hybrid
    from app.rag.steps.context_builder import build_legal_context

    state = PipelineState(question=case.question)

    # B2 - Cleaner
    state.cleaned = step_clean_query(real_engine.get_llm(), case.question, history=case.history)
    print(f"\n[B2] cleaned_query={state.cleaned['cleaned_query']!r}, "
          f"intent={state.cleaned['intent']!r}")
    print(f"     policy={json.dumps(state.cleaned.get('retrieval_policy', {}), ensure_ascii=False)}")

    # B3 - Embedding
    state.query_vector = step_embed_cleaned_query(real_engine, state.cleaned)
    print(f"[B3] vector dim={len(state.query_vector)}")

    # B4 - Retrieval
    state.retrieved_blocks = step_retrieve_hybrid(
        engine=real_engine,
        cleaned=state.cleaned,
        query_vector=state.query_vector,
        top_k=case.top_k,
        query_text=case.question,
    )
    print(f"[B4] retrieved_blocks={len(state.retrieved_blocks)} "
          f"(anchor={sum(1 for b in state.retrieved_blocks if b.get('expansion_kind') == 'anchor')}, "
          f"expanded={sum(1 for b in state.retrieved_blocks if b.get('expansion_kind') != 'anchor')})")

    # B5 - Build LegalContext
    retrieval_query = state.cleaned.get("cleaned_query") or case.question
    terms = state.cleaned.get("key_legal_terms") or []
    if terms:
        retrieval_query = f"{retrieval_query}\nThuật ngữ: {' '.join(terms[:5])}"

    state.legal_context = build_legal_context(
        question=case.question,
        cleaned=state.cleaned,
        retrieved_blocks=state.retrieved_blocks,
        retrieval_query=retrieval_query,
        max_evidence=10,
    )

    # ===== ASSERTIONS (dựa trên expected trong testcase) =====
    lc = state.legal_context
    exp = case.expected

    # In LegalContext
    _print_legal_context(lc, max_evidence=3)

    # 1. Intent
    if exp.intent:
        assert lc.request.intent == exp.intent, (
            f"intent mismatch: got {lc.request.intent!r}, expected {exp.intent!r}"
        )

    # 2. Resolved query (sau khi resolve history)
    if exp.resolved_query_contains:
        for needle in exp.resolved_query_contains:
            assert needle.lower() in lc.request.resolved_query.lower(), (
                f"resolved_query={lc.request.resolved_query!r} không chứa {needle!r}"
            )

    # 3. Retrieval policy
    if exp.policy_intensity:
        assert lc.request.retrieval_policy.get("intensity") == exp.policy_intensity
    if exp.policy_expansion:
        assert lc.request.retrieval_policy.get("expansion") == exp.policy_expansion
    if exp.policy_require_active is not None:
        assert lc.request.retrieval_policy.get("filters", {}).get("require_active") == exp.policy_require_active

    # 4. Evidence có ít nhất N block
    if exp.min_evidence is not None:
        assert len(lc.evidence) >= exp.min_evidence, (
            f"evidence count {len(lc.evidence)} < {exp.min_evidence}"
        )

    # 5. Evidence phải chứa citation nào đó (vd: "Điều 6")
    if exp.must_contain_citation:
        all_citations = " ".join(c.short for c in lc.citations)
        for needle in exp.must_contain_citation:
            assert needle in all_citations, (
                f"Không tìm thấy citation {needle!r} trong {all_citations!r}"
            )

    # 6. Expansion kind diversity
    if exp.expansion_kinds_seen:
        kinds = {ev.expansion_kind for ev in lc.evidence}
        for kind in exp.expansion_kinds_seen:
            assert kind in kinds, f"Thiếu expansion_kind={kind!r}, got {kinds}"

    # 7. Status filter (nếu policy.require_active=True, tất cả evidence phải active)
    if exp.policy_require_active is True:
        inactive = [ev for ev in lc.evidence if not ev.is_active]
        assert not inactive, f"require_active=True nhưng có {len(inactive)} evidence inactive"

    # 8. Hierarchy expanded flag
    if exp.hierarchy_expanded is not None:
        assert lc.hierarchy.expanded == exp.hierarchy_expanded

    print(f"\n[PASS] {case.id} - assertions OK\n")


# ============================================================
# TEST 2: In ra full LegalContext JSON để debug
# ============================================================
def test_print_legal_context_json(real_engine):
    """In ra JSON của LegalContext cho 1 testcase đầu tiên.

    Hữu ích khi cần xem cấu trúc contract B5 thực tế.
    """
    case = TEST_CASES[0]
    from app.rag.orchestrator import PipelineState
    from app.rag.steps.cleaner import step_clean_query
    from app.rag.steps.embedding import step_embed_cleaned_query
    from app.rag.steps.retrieval import step_retrieve_hybrid
    from app.rag.steps.context_builder import build_legal_context

    state = PipelineState(question=case.question)
    state.cleaned = step_clean_query(real_engine.get_llm(), case.question, history=case.history)
    state.query_vector = step_embed_cleaned_query(real_engine, state.cleaned)
    state.retrieved_blocks = step_retrieve_hybrid(
        engine=real_engine, cleaned=state.cleaned,
        query_vector=state.query_vector, top_k=5, query_text=case.question,
    )
    retrieval_query = state.cleaned.get("cleaned_query") or case.question
    terms = state.cleaned.get("key_legal_terms") or []
    if terms:
        retrieval_query = f"{retrieval_query}\nThuật ngữ: {' '.join(terms[:5])}"
    state.legal_context = build_legal_context(
        question=case.question, cleaned=state.cleaned,
        retrieved_blocks=state.retrieved_blocks, retrieval_query=retrieval_query,
    )

    # In full JSON
    lc_dict = _legal_context_to_dict(state.legal_context)
    print("\n" + "=" * 80)
    print("FULL LegalContext JSON:")
    print("=" * 80)
    print(json.dumps(lc_dict, ensure_ascii=False, indent=2)[:5000])  # cap 5KB
    print("=" * 80)
    assert state.legal_context is not None


# ============================================================
# TEST 3: Validate contract schema (Pydantic)
# ============================================================
def test_legal_context_schema_validates(real_engine):
    """Chạy 3 testcase đầu, assert LegalContext là Pydantic hợp lệ."""
    from app.rag.orchestrator import PipelineState
    from app.rag.steps.cleaner import step_clean_query
    from app.rag.steps.embedding import step_embed_cleaned_query
    from app.rag.steps.retrieval import step_retrieve_hybrid
    from app.rag.steps.context_builder import build_legal_context

    for case in TEST_CASES[:3]:
        state = PipelineState(question=case.question)
        state.cleaned = step_clean_query(real_engine.get_llm(), case.question, history=case.history)
        state.query_vector = step_embed_cleaned_query(real_engine, state.cleaned)
        state.retrieved_blocks = step_retrieve_hybrid(
            engine=real_engine, cleaned=state.cleaned,
            query_vector=state.query_vector, top_k=3, query_text=case.question,
        )
        retrieval_query = state.cleaned.get("cleaned_query") or case.question
        terms = state.cleaned.get("key_legal_terms") or []
        if terms:
            retrieval_query = f"{retrieval_query}\nThuật ngữ: {' '.join(terms[:5])}"
        state.legal_context = build_legal_context(
            question=case.question, cleaned=state.cleaned,
            retrieved_blocks=state.retrieved_blocks, retrieval_query=retrieval_query,
        )

        lc = state.legal_context
        assert isinstance(lc, LegalContext)
        # Round-trip JSON
        j = lc.model_dump_json()
        lc2 = LegalContext.model_validate_json(j)
        assert lc2.evidence[0].evidence_id == lc.evidence[0].evidence_id if lc.evidence else True
        print(f"[OK] {case.id} → LegalContext với {len(lc.evidence)} evidence, "
              f"{len(lc.citations)} citations")


# ============================================================
# Cho phép chạy trực tiếp: python tests/b2-b5-test/test_pipeline_to_b5.py
# ============================================================
if __name__ == "__main__":
    """Chạy nhanh 3 testcase đầu tiên mà không cần pytest, in ra LegalContext."""
    print("=" * 80)
    print("Chạy nhanh pipeline B1→B5 cho 3 testcase đầu tiên (không cần pytest)")
    print("=" * 80)

    if not os.getenv("GROQ_API_KEY"):
        print("ERROR: Thiếu GROQ_API_KEY. Copy backend/.env sang service trước.")
        sys.exit(1)

    eng = RagEngine()
    eng.init()

    try:
        for case in TEST_CASES[:3]:
            print(f"\n>>> {case.id}: {case.question!r}")
            state = PipelineState(question=case.question)
            state.cleaned = step_clean_query(eng.get_llm(), case.question, history=case.history)
            state.query_vector = step_embed_cleaned_query(eng, state.cleaned)
            state.retrieved_blocks = step_retrieve_hybrid(
                engine=eng, cleaned=state.cleaned,
                query_vector=state.query_vector, top_k=case.top_k,
                query_text=case.question,
            )
            rq = state.cleaned.get("cleaned_query") or case.question
            terms = state.cleaned.get("key_legal_terms") or []
            if terms:
                rq = f"{rq}\nThuật ngữ: {' '.join(terms[:5])}"
            state.legal_context = build_legal_context(
                question=case.question, cleaned=state.cleaned,
                retrieved_blocks=state.retrieved_blocks, retrieval_query=rq,
            )
            _print_legal_context(state.legal_context, max_evidence=3)
    finally:
        eng.close()
