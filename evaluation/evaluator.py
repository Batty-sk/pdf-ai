"""Score a labelled set of questions against the live RAG pipeline.

Answer accuracy is token overlap with the expected answer. It is a research
signal, not a second human rating. Unsupported questions are scored only on
whether the system refused to answer.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from database.database import Database
from database.models import CaseScore, EvalCase, EvalSummary, RagAnswer, Source
from rag.rag_pipeline import NOT_FOUND, RagPipeline

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "what", "how", "when", "your", "you", "about", "into", "have", "has",
}


class Evaluator:
    def __init__(self, db: Database, pipeline: RagPipeline):
        self.db = db
        self.pipeline = pipeline

    def add_case(
        self,
        question: str,
        expected_answer: str,
        expected_filename: str,
        expected_page: int | None,
        expect_unsupported: bool,
    ) -> None:
        self.db.add_eval_case(
            EvalCase(
                id=str(uuid.uuid4()),
                question=question.strip(),
                expected_answer=expected_answer.strip(),
                expected_filename=expected_filename.strip(),
                expected_page=expected_page,
                expect_unsupported=expect_unsupported,
            )
        )

    def delete_case(self, case_id: str) -> None:
        self.db.delete_eval_case(case_id)

    def cases(self) -> list[EvalCase]:
        return self.db.list_eval_cases()

    def import_json(self, path: Path) -> int:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("The file must contain a list of questions.")
        cases: list[EvalCase] = []
        for item in payload:
            if not isinstance(item, dict) or not str(item.get("question", "")).strip():
                continue
            page = item.get("expected_page")
            try:
                parsed_page = int(page) if page not in (None, "", 0) else None
            except (TypeError, ValueError):
                parsed_page = None
            cases.append(
                EvalCase(
                    id=str(uuid.uuid4()),
                    question=str(item["question"]).strip(),
                    expected_answer=str(item.get("expected_answer", "")).strip(),
                    expected_filename=str(item.get("expected_filename", "")).strip(),
                    expected_page=parsed_page,
                    expect_unsupported=bool(item.get("expect_unsupported", False)),
                )
            )
        self.db.replace_eval_cases(cases)
        return len(cases)

    def export_json(self, path: Path) -> None:
        import json

        payload = [
            {
                "question": case.question,
                "expected_answer": case.expected_answer,
                "expected_filename": case.expected_filename,
                "expected_page": case.expected_page,
                "expect_unsupported": case.expect_unsupported,
            }
            for case in self.cases()
        ]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def run(self, document_ids: list[str]) -> EvalSummary:
        scores: list[CaseScore] = []
        for case in self.cases():
            started = time.perf_counter()
            answer = self.pipeline.answer(case.question, [], document_ids)
            latency = int((time.perf_counter() - started) * 1000)
            scores.append(score_case(case, answer, latency))
        summary = summarize(scores)
        self.db.save_eval_run(
            {
                "retrieval_accuracy": summary.retrieval_accuracy,
                "citation_accuracy": summary.citation_accuracy,
                "answer_accuracy": summary.answer_accuracy,
                "unsupported_detection": summary.unsupported_detection,
                "mean_latency_ms": summary.mean_latency_ms,
            },
            [
                {
                    "case_id": item.case_id,
                    "question": item.question,
                    "answer": item.answer,
                    "retrieval_hit": item.retrieval_hit,
                    "citation_hit": item.citation_hit,
                    "answer_score": item.answer_score,
                    "unsupported_correct": item.unsupported_correct,
                    "latency_ms": item.latency_ms,
                }
                for item in scores
            ],
        )
        return summary


def score_case(case: EvalCase, answer: RagAnswer, latency_ms: int) -> CaseScore:
    refused = answer.refused or answer.answer.strip() == NOT_FOUND
    if case.expect_unsupported:
        return CaseScore(
            case_id=case.id,
            question=case.question,
            answer=answer.answer,
            retrieval_hit=None,
            citation_hit=None,
            answer_score=None,
            unsupported_correct=refused,
            latency_ms=latency_ms,
        )
    retrieval_hit = _matches(case, answer.retrieved) if case.expected_filename else None
    citation_hit = None if not case.expected_filename else (False if refused else _matches(case, answer.sources))
    return CaseScore(
        case_id=case.id,
        question=case.question,
        answer=answer.answer,
        retrieval_hit=retrieval_hit,
        citation_hit=citation_hit,
        answer_score=token_f1(case.expected_answer, answer.answer),
        unsupported_correct=None,
        latency_ms=latency_ms,
    )


def summarize(scores: list[CaseScore]) -> EvalSummary:
    retrieval = [item.retrieval_hit for item in scores if item.retrieval_hit is not None]
    citation = [item.citation_hit for item in scores if item.citation_hit is not None]
    answers = [item.answer_score for item in scores if item.answer_score is not None]
    unsupported = [item.unsupported_correct for item in scores if item.unsupported_correct is not None]
    latency = [item.latency_ms for item in scores]
    return EvalSummary(
        retrieval_accuracy=_rate(retrieval),
        citation_accuracy=_rate(citation),
        answer_accuracy=(sum(answers) / len(answers)) if answers else None,
        unsupported_detection=_rate(unsupported),
        mean_latency_ms=(sum(latency) / len(latency)) if latency else 0.0,
        results=scores,
    )


def token_f1(expected: str, actual: str) -> float:
    expected_tokens = set(_tokens(expected))
    actual_tokens = set(_tokens(actual))
    if not expected_tokens or not actual_tokens:
        return 0.0
    overlap = len(expected_tokens & actual_tokens)
    if overlap == 0:
        return 0.0
    precision = overlap / len(actual_tokens)
    recall = overlap / len(expected_tokens)
    return 2 * precision * recall / (precision + recall)


def _tokens(text: str) -> list[str]:
    import re

    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOP and len(token) > 1
    ]


def _matches(case: EvalCase, sources: list[Source]) -> bool:
    expected_name = Path(case.expected_filename).name.lower()
    for source in sources:
        if Path(source.filename).name.lower() != expected_name:
            continue
        if case.expected_page is None or source.page == case.expected_page:
            return True
    return False


def _rate(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)
