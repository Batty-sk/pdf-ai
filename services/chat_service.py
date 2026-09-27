"""Chat history and the ask flow. Each chat remembers its own documents."""

from __future__ import annotations

from database.database import Database
from database.models import RagAnswer, Source
from rag.rag_pipeline import RagPipeline
from utils.errors import LlmError

NO_DOCUMENTS = "Add a PDF to this chat before asking a question."


class ChatService:
    def __init__(self, db: Database, pipeline: RagPipeline):
        self.db = db
        self.pipeline = pipeline

    def create_chat(self, document_ids: list[str], title: str = "New chat") -> str:
        chat = self.db.create_chat(title, document_ids)
        return chat.id

    def rename(self, chat_id: str, title: str) -> None:
        cleaned = " ".join(title.split()).strip()
        if cleaned:
            self.db.rename_chat(chat_id, cleaned[:80])

    def delete(self, chat_id: str) -> None:
        self.db.delete_chat(chat_id)

    def clear(self, chat_id: str) -> None:
        self.db.clear_messages(chat_id)

    def set_documents(self, chat_id: str, document_ids: list[str]) -> None:
        self.db.set_chat_documents(chat_id, document_ids)

    def ask(self, chat_id: str, question: str) -> RagAnswer:
        question = question.strip()
        document_ids = [
            document_id
            for document_id in self.db.chat_document_ids(chat_id)
            if _is_ready(self.db, document_id)
        ]
        history = self.db.list_messages(chat_id)
        self.db.add_message(chat_id, "user", question, None, None)
        self._retitle(chat_id, question)
        if not document_ids:
            result = RagAnswer(NO_DOCUMENTS, [], [], True, None, False)
            self._save_assistant(chat_id, result)
            return result
        try:
            result = self.pipeline.answer(question, history, document_ids)
        except LlmError as exc:
            self.db.add_message(chat_id, "assistant", str(exc), None, "error")
            raise
        self._save_assistant(chat_id, result)
        return result

    def export_text(self, chat_id: str) -> str:
        chat = self.db.get_chat(chat_id)
        title = chat.title if chat else "Chat"
        lines = [title, ""]
        for message in self.db.list_messages(chat_id):
            speaker = "You" if message.role == "user" else "PDF AI Assistant"
            lines.append(f"{speaker}:")
            lines.append(message.content)
            if message.sources and message.warning != "error":
                lines.append("Sources:")
                for source in message.sources:
                    filename = source.get("filename", "PDF")
                    page = source.get("page", "?")
                    lines.append(f"- {filename}, page {page}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _retitle(self, chat_id: str, question: str) -> None:
        chat = self.db.get_chat(chat_id)
        if chat and chat.title == "New chat":
            first_line = question.strip().splitlines()[0]
            self.db.rename_chat(chat_id, first_line[:48])

    def _save_assistant(self, chat_id: str, result: RagAnswer) -> None:
        payload = [source.to_dict() for source in result.sources]
        self.db.add_message(chat_id, "assistant", result.answer, payload, result.warning)


def sources_from_message(payload: list[dict]) -> list[Source]:
    return [Source.from_dict(item) for item in payload if isinstance(item, dict)]


def _is_ready(db: Database, document_id: str) -> bool:
    document = db.get_document(document_id)
    return document is not None and document.status == "ready"
