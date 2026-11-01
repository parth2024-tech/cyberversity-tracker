"""
Unit tests for Canonical AI Entity Taxonomy and Multilingual Alias Registry.
"""

from ai_security_monitor.config.entity_taxonomy import (
    CANONICAL_ENTITIES_SEED,
    build_alias_index,
)


def test_seed_taxonomy_labs_and_models():
    assert len(CANONICAL_ENTITIES_SEED) >= 15

    # Check key labs exist
    canonical_ids = {e.canonical_id for e in CANONICAL_ENTITIES_SEED}
    assert "lab:deepseek" in canonical_ids
    assert "lab:qwen" in canonical_ids
    assert "lab:zhipu" in canonical_ids
    assert "lab:moonshot" in canonical_ids
    assert "lab:shanghai_ai_lab" in canonical_ids
    assert "model:deepseek_v3" in canonical_ids
    assert "model:qwen_2_5" in canonical_ids


def test_alias_index_lookup():
    alias_index = build_alias_index()

    # English aliases
    assert alias_index["deepseek"] == "lab:deepseek"
    assert alias_index["deepseek-ai"] == "lab:deepseek"
    assert alias_index["qwen"] == "lab:qwen"
    assert alias_index["kimi"] == "lab:moonshot"
    assert alias_index["thudm"] == "lab:zhipu"
    assert alias_index["zai-org"] == "lab:zhipu"  # Renamed HF org

    # Chinese aliases
    assert alias_index["深度求索"] == "lab:deepseek"
    assert alias_index["通义千问"] == "lab:qwen"
    assert alias_index["通義千問"] == "lab:qwen"  # Traditional
    assert alias_index["智谱ai"] == "lab:zhipu"
    assert alias_index["月之暗面"] == "lab:moonshot"
    assert alias_index["上海人工智能实验室"] == "lab:shanghai_ai_lab"
    assert alias_index["书生·浦语"] == "lab:shanghai_ai_lab"

    # Models
    assert alias_index["deepseek-v3"] == "model:deepseek_v3"
    assert alias_index["qwen2.5"] == "model:qwen_2_5"
