"""
B6 - LLM Generation (Groq).

Input: câu hỏi gốc + context_blocks từ B5.
Output: câu trả lời tự nhiên có trích dẫn.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.prompts.generator import SYSTEM_ANSWER_GENERATION


NO_CONTEXT_MSG = (
    "Xin lỗi, tôi không tìm thấy thông tin pháp luật liên quan để trả lời câu hỏi này. "
    "Bạn có thể diễn đạt lại bằng các thuật ngữ pháp lý cụ thể hơn không?"
)


def step_generate_answer(llm, question: str, context_text: str) -> str:
    """
    B6: đưa context cho LLM (Groq) và lấy câu trả lời.

    Args:
        llm:          ChatGroq instance (engine.get_llm()).
        question:     câu hỏi gốc của user.
        context_text: output của B5 (build_context_for_llm).

    Returns:
        Câu trả lời dạng text (đã có trích dẫn nếu LLM tuân thủ prompt).
    """
    if not context_text.strip():
        return NO_CONTEXT_MSG

    if llm is None:
        raise RuntimeError("LLM chưa được khởi tạo.")

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
