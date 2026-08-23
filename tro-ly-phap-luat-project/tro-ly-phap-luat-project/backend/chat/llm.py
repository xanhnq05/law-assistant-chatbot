"""
Nơi gọi mô hình để sinh câu trả lời. Đây CHỈ là stub tạm — trong `env` bạn gửi
đã có sẵn GROQ_API_KEY, LANGSMITH_*, NEO4J_*, PINECONE_*, nghĩa là bạn đang có
(hoặc sẽ có) một pipeline LangChain/RAG riêng để trả lời câu hỏi pháp luật.

Hãy thay nội dung hàm generate_reply() bên dưới bằng lệnh gọi tới chain đó,
ví dụ:

    from my_rag_chain import law_assistant_chain

    async def generate_reply(history: list[dict]) -> str:
        result = await law_assistant_chain.ainvoke({"history": history})
        return result["answer"]

Giữ nguyên chữ ký hàm (nhận list [{"role": "user"/"assistant", "content": str}],
trả về str) thì chat/router.py không cần sửa gì thêm.
"""
from __future__ import annotations


async def generate_reply(history: list[dict]) -> str:
    # TODO: nối vào chain LangChain/Groq/Neo4j/Pinecone thật của bạn.
    return (
        "Đây là câu trả lời tạm thời (llm.py chưa được nối vào pipeline thật). "
        "Thông tin chỉ mang tính tham khảo, không thay thế tư vấn pháp lý chính thức."
    )
