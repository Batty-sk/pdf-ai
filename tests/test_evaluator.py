from database.models import EvalCase, RagAnswer, Source
from evaluation.evaluator import score_case, summarize, token_f1
from rag.rag_pipeline import NOT_FOUND


def test_token_overlap_and_refusal_metrics():
    source = Source(
        chunk_id="c1",
        document_id="d1",
        filename="Policy.pdf",
        stored_path="",
        page=2,
        text="20 days of annual leave",
        score=0.8,
        semantic_score=0.8,
    )
    answered = EvalCase("1", "How much leave?", "20 days of annual leave", "Policy.pdf", 2, False)
    unsupported = EvalCase("2", "What is the bonus?", "", "Policy.pdf", None, True)
    good = RagAnswer("Employees receive 20 days of annual leave.", [source], [source], False, None, True)
    refused = RagAnswer(NOT_FOUND, [], [], True, None, False)
    summary = summarize(
        [
            score_case(answered, good, 12),
            score_case(unsupported, refused, 4),
        ]
    )
    assert summary.retrieval_accuracy == 1
    assert summary.citation_accuracy == 1
    assert summary.unsupported_detection == 1
    assert summary.answer_accuracy is not None and summary.answer_accuracy > 0.5
    assert token_f1("alpha beta", "gamma") == 0
