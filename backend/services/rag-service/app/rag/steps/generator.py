"""
B6 - LLM Generation (Groq).

Input: câu hỏi gốc + context_blocks từ B5 + lịch sử hội thoại.
Output: câu trả lời tự nhiên có trích dẫn.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.prompts.generator import SYSTEM_ANSWER_GENERATION


NO_CONTEXT_MSG = (
    "Xin lỗi, tôi không tìm thấy thông tin pháp luật liên quan để trả lời câu hỏi này. "
    "Bạn có thể diễn đạt lại bằng các thuật ngữ pháp lý cụ thể hơn không?"
)

# Giới hạn số ký tự context để tránh hết context window của LLM.
MAX_CONTEXT_CHARS = 6000
# Giới hạn history (tối đa 3 cặp user/assistant)
MAX_HISTORY_PAIRS = 3


def step_generate_answer(
    llm,
    question: str,
    context_text: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    B6: đưa context + history cho LLM (Groq) và lấy câu trả lời.

    Args:
        llm:          ChatGroq instance (engine.get_llm()).
        question:     câu hỏi gốc của user.
        context_text: output của B5 (build_context_for_llm).
        history:      danh sách {role, content} gần đây (tối đa 3 cặp = 6 msg).
                      Dùng để duy trì multi-turn conversation mà không hết context.
    """
    if not context_text.strip():
        return NO_CONTEXT_MSG

    if llm is None:
        raise RuntimeError("LLM chưa được khởi tạo.")

    # ── Cắt context nếu quá dài ──────────────────────────────────────────
    if len(context_text) > MAX_CONTEXT_CHARS:
        context_text = context_text[:MAX_CONTEXT_CHARS] + "\n[...còn tiếp...]"

    # ── Build history string (chỉ giữ 3 cặp gần nhất) ───────────────────
    history_text = ""
    if history:
        pairs: list[dict[str, str]] = []
        # Tách thành từng cặp user/assistant
        pair_buffer: list[dict[str, str]] = []
        for msg in history[-MAX_HISTORY_PAIRS * 2:]:  # chỉ lấy 3 cặp cuối
            pair_buffer.append(msg)
            if len(pair_buffer) == 2:
                pairs.insert(0, pair_buffer[0])  # insert 0 để giữ thứ tự
                pairs.insert(1, pair_buffer[1])
                pair_buffer = []

        for msg in pairs:
            role_label = "Người dùng" if msg.get("role") == "user" else "Trợ lý pháp lý"
            history_text += f"{role_label}: {msg.get('content', '')}\n"

    # ── Build user prompt ──────────────────────────────────────────────────
    if history_text:
        user_prompt = (
            f"Lịch sử hội thoại gần đây:\n{history_text}\n"
            f"Câu hỏi hiện tại: {question}\n\n"
            f"Các điều luật liên quan:\n{context_text}"
        )
    else:
        user_prompt = (
            f"Câu hỏi: {question}\n\n"
            f"Các điều luật liên quan:\n{context_text}"
        )

    try:
        resp = llm.invoke([
            SystemMessage(content=SYSTEM_ANSWER_GENERATION),
            HumanMessage(content=user_prompt),
        ])
        return resp.content or NO_CONTEXT_MSG
    except Exception:
        return NO_CONTEXT_MSG
