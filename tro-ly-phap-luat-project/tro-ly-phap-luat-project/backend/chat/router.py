from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import require_role
from chat import repository as repo
from chat.llm import generate_reply

router = APIRouter(prefix="/chats", tags=["chat"])

# Hiện chỉ có 1 role "user" nên require_role("user") ~ giống get_current_user,
# nhưng viết vậy để sau này thêm role khác (vd "admin") vẫn tái dùng được luôn.
CurrentUser = Depends(require_role("user"))


@router.get("")
def list_chats(current_user: dict = CurrentUser):
    return repo.list_chats(current_user["sub"])


@router.post("", status_code=201)
def create_chat(payload: dict, current_user: dict = CurrentUser):
    return repo.create_chat(current_user["sub"], payload.get("title"))


@router.get("/{chat_id}")
def get_chat(chat_id: str, current_user: dict = CurrentUser):
    chat = repo.get_chat(current_user["sub"], chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")
    return chat


@router.delete("/{chat_id}", status_code=204)
def delete_chat(chat_id: str, current_user: dict = CurrentUser):
    repo.delete_chat(current_user["sub"], chat_id)


@router.post("/{chat_id}/messages")
async def send_message(chat_id: str, payload: dict, current_user: dict = CurrentUser):
    user_id = current_user["sub"]
    text = (payload.get("content") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nội dung tin nhắn trống.")
    if not repo.chat_belongs_to_user(user_id, chat_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ.")

    repo.add_message(chat_id, "user", text)
    repo.rename_chat_if_default(user_id, chat_id, text)

    history = repo.list_messages(chat_id)
    reply_text = await generate_reply(history)
    repo.add_message(chat_id, "assistant", reply_text)

    return repo.get_chat(user_id, chat_id)
