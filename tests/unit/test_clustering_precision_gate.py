"""
Unit tests for Cross-Language Story Clustering & Precision Gate (Workstream B2).
Evaluates entity resolution, number normalization, 20 hand-labeled pairs (precision gate >= 0.90),
and false positive rejection on negative distractors.
"""

from datetime import UTC, datetime, timedelta

from ai_security_monitor.application.services.cross_language_clustering import (
    EVALUATION_NEGATIVE_PAIRS,
    EVALUATION_POSITIVE_PAIRS,
    CrossLanguageClusteringService,
    cross_language_clustering_service,
)

POSITIVE_PAIRS = EVALUATION_POSITIVE_PAIRS
NEGATIVE_PAIRS = EVALUATION_NEGATIVE_PAIRS


def test_chinese_number_normalization():
    svc = CrossLanguageClusteringService()
    assert svc.normalize_numbers("720亿参数模型发布") == "72b参数模型发布"
    assert svc.normalize_numbers("80亿小模型") == "8b小模型"
    assert svc.normalize_numbers("140亿参数") == "14b参数"
    assert svc.normalize_numbers("100万长上下文") == "1000k长上下文"
    assert svc.normalize_numbers("1万亿全模态") == "1t全模态"


def test_lab_alias_resolution_and_cluster_key():
    svc = CrossLanguageClusteringService()

    ent_deepseek = svc.extract_entities("深度求索推出DeepSeek-R1大模型")
    assert ent_deepseek.lab == "deepseek"
    assert ent_deepseek.model_family == "deepseek-r1"
    assert ent_deepseek.cluster_key == "deepseek:deepseek-r1"
    assert ent_deepseek.language == "zh"

    ent_qwen = svc.extract_entities("Alibaba releases Qwen-2.5-Coder-72B open-weights")
    assert ent_qwen.lab == "qwen"
    assert ent_qwen.model_family == "qwen-2.5-coder"
    assert ent_qwen.version == "72b"
    assert ent_qwen.cluster_key == "qwen:qwen-2.5-coder:72b"
    assert ent_qwen.language == "en"

    ent_kimi = svc.extract_entities("月之暗面发布Kimi-k1.5多模态推理模型")
    assert ent_kimi.lab == "moonshot"
    assert ent_kimi.model_family == "kimi-k1.5"
    assert ent_kimi.cluster_key == "moonshot:kimi-k1.5"


def test_20_pair_precision_gate():
    """
    Precision Gate: evaluates 20 hand-labeled pairs (10 positive, 10 negative).
    Guarantees Precision >= 0.90 (hard requirement) and Recall >= 0.85 before feeding ranking/graph.
    """
    now = datetime.now(UTC)

    # 1. Evaluate 10 Positive Pairs
    true_positives = 0
    false_negatives = 0
    for cn_text, en_text, pair_label in POSITIVE_PAIRS:
        matched = cross_language_clustering_service.are_same_story(
            cn_text,
            en_text,
            published_a=now,
            published_b=now + timedelta(hours=2),
            max_delta_hours=72.0,
        )
        if matched:
            true_positives += 1
        else:
            false_negatives += 1

    # 2. Evaluate 10 Negative Same-Org Pairs
    false_positives = 0
    true_negatives = 0
    for text_a, text_b, pair_label in NEGATIVE_PAIRS:
        matched = cross_language_clustering_service.are_same_story(
            text_a,
            text_b,
            published_a=now,
            published_b=now + timedelta(hours=2),
            max_delta_hours=72.0,
        )
        if matched:
            false_positives += 1
        else:
            true_negatives += 1

    total_predicted_positive = true_positives + false_positives
    precision = (
        true_positives / total_predicted_positive
        if total_predicted_positive > 0
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0.0
    )

    # Precision Gate Assertion
    assert precision >= 0.90, (
        f"Precision {precision:.2f} failed threshold 0.90! "
        f"FP: {false_positives}, TP: {true_positives}"
    )
    assert recall >= 0.85, (
        f"Recall {recall:.2f} failed threshold 0.85! "
        f"FN: {false_negatives}, TP: {true_positives}"
    )
    assert false_positives == 0, (
        f"Detected {false_positives} false mergers in same-org negative pairs!"
    )
