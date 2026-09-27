"""Background work so indexing and generation never block the window."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from services.chat_service import ChatService
from services.compare_service import CompareService
from services.document_service import DocumentService
from utils.errors import AppError

logger = logging.getLogger(__name__)


class IndexWorker(QThread):
    progress = Signal(str)
    batch_done = Signal(object)

    def __init__(self, service: DocumentService, jobs: list[tuple[Path, str | None]]):
        super().__init__()
        self.service = service
        self.jobs = jobs

    def run(self) -> None:
        results = []
        total = len(self.jobs)
        for index, (path, password) in enumerate(self.jobs, start=1):
            label = f"Processing document {index} of {total}…"

            def report(message: str, prefix: str = label) -> None:
                self.progress.emit(f"{prefix} {message}")

            self.progress.emit(label)
            results.append(self.service.index_file(path, password, report))
        self.batch_done.emit(results)


class ReindexWorker(QThread):
    progress = Signal(str)
    batch_done = Signal(object)

    def __init__(self, service: DocumentService):
        super().__init__()
        self.service = service

    def run(self) -> None:
        try:
            results = self.service.reindex_all(self.progress.emit)
            self.batch_done.emit(results)
        except Exception:
            logger.exception("Reindex failed")
            self.batch_done.emit([])


class AnswerWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, chat: ChatService, chat_id: str, question: str):
        super().__init__()
        self.chat = chat
        self.chat_id = chat_id
        self.question = question

    def run(self) -> None:
        try:
            self.succeeded.emit(self.chat.ask(self.chat_id, self.question))
        except AppError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Answer failed")
            self.failed.emit("Something went wrong while preparing the answer.")


class CompareWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, service: CompareService, left_id: str, right_id: str, question: str):
        super().__init__()
        self.service = service
        self.left_id = left_id
        self.right_id = right_id
        self.question = question

    def run(self) -> None:
        try:
            self.succeeded.emit(self.service.compare(self.left_id, self.right_id, self.question))
        except AppError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Compare failed")
            self.failed.emit("The comparison could not be completed.")


class EvalWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, evaluator, document_ids: list[str]):
        super().__init__()
        self.evaluator = evaluator
        self.document_ids = document_ids

    def run(self) -> None:
        try:
            self.succeeded.emit(self.evaluator.run(self.document_ids))
        except AppError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Evaluation failed")
            self.failed.emit("The evaluation could not be completed.")


class ProbeWorker(QThread):
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, settings, data_dir):
        super().__init__()
        self.settings = settings
        self.data_dir = data_dir

    def run(self) -> None:
        try:
            from llm.openai_provider import OpenAICompatibleProvider

            provider = OpenAICompatibleProvider.from_settings(self.settings, self.data_dir)
            provider.complete(
                [
                    {"role": "system", "content": "Reply with JSON only."},
                    {"role": "user", "content": 'Return {"ok": true}'},
                ]
            )
            self.succeeded.emit()
        except AppError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Connection test failed")
            self.failed.emit("Could not reach the AI service.")
