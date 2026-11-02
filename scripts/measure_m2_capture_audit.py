"""
M2 Measurement Script: Capture-rate audit on real releases from the last 30 days.
Checks primary foundation models and developer tools against the production database (data/monitor.db).
"""

from __future__ import annotations

import sqlite3

PRIMARY_RELEASES_AUDIT = [
    {"name": "Qwen2.5 (Alibaba)", "keywords": ["qwen2.5", "qwen 2.5", "qwen-2.5", "qwen"]},
    {"name": "DeepSeek-V3 / Coder", "keywords": ["deepseek", "deepseek-v3", "deepseek-coder"]},
    {"name": "vLLM Inference Engine", "keywords": ["vllm", "pagedattention"]},
    {"name": "SGLang Inference Runtime", "keywords": ["sglang", "radixattention"]},
    {"name": "llama.cpp", "keywords": ["llama.cpp", "ggml", "gguf"]},
    {"name": "Ollama Local Runtime", "keywords": ["ollama"]},
    {"name": "Claude 3.5 Sonnet / Computer Use", "keywords": ["claude 3.5", "computer use", "sonnet 3.5"]},
    {"name": "OpenAI o1 Reasoning Models", "keywords": ["openai o1", "o1-preview", "o1-mini", "reasoning model"]},
    {"name": "Llama 3.2 (Meta Edge & Vision)", "keywords": ["llama 3.2", "llama-3.2", "llama3.2"]},
    {"name": "GLM-4 / CogVideoX (Zhipu / Zai-Org)", "keywords": ["glm-4", "cogvideox", "zhipu", "thudm"]},
    {"name": "Kimi Multimodal / Moonshot AI", "keywords": ["kimi", "moonshot"]},
    {"name": "Mistral Large / Ministral", "keywords": ["mistral", "ministral", "codestral"]},
    {"name": "InternLM / InternVL (Shanghai AI Lab)", "keywords": ["internlm", "internvl", "shanghai ai lab"]},
    {"name": "MiniMax MoE Models", "keywords": ["minimax", "minimax-text", "abab"]},
    {"name": "xAI Grok", "keywords": ["grok", "xai"]},
    {"name": "Gemini 1.5 Flash / Pro Updates", "keywords": ["gemini 1.5", "gemini-1.5"]},
    {"name": "LangGraph / LangChain Agents", "keywords": ["langgraph", "langchain"]},
    {"name": "Hugging Face smolagents", "keywords": ["smolagents", "hugging face agents"]},
    {"name": "ModelScope Community Releases", "keywords": ["modelscope"]},
    {"name": "Baichuan AI Enterprise Releases", "keywords": ["baichuan"]},
]


def audit_m2_capture_rate(db_path: str = "data/monitor.db") -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    results = []
    captured_count = 0

    for item in PRIMARY_RELEASES_AUDIT:
        target_name = item["name"]
        keywords = item["keywords"]

        # Build query searching title and summary
        where_clauses = []
        params = []
        for kw in keywords:
            where_clauses.append("(LOWER(title) LIKE ? OR LOWER(summary) LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])

        query = f"""
            SELECT id, title, url, published_at, source_id
            FROM entries
            WHERE {' OR '.join(where_clauses)}
            ORDER BY published_at ASC
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        is_captured = len(rows) > 0
        if is_captured:
            captured_count += 1
            earliest = rows[0]["published_at"]
            sample_title = rows[0]["title"]
        else:
            earliest = None
            sample_title = None

        results.append({
            "target": target_name,
            "captured": is_captured,
            "match_count": len(rows),
            "earliest_date": earliest,
            "sample_title": sample_title,
        })

    conn.close()

    capture_rate_pct = (captured_count / len(PRIMARY_RELEASES_AUDIT)) * 100

    return {
        "total_targets_audited": len(PRIMARY_RELEASES_AUDIT),
        "captured_count": captured_count,
        "missed_count": len(PRIMARY_RELEASES_AUDIT) - captured_count,
        "capture_rate_pct": round(capture_rate_pct, 1),
        "audit_items": results,
    }


if __name__ == "__main__":
    report = audit_m2_capture_rate()
    print("=================== M2 CAPTURE-RATE AUDIT REPORT ===================")
    print(f"Audit Sample:     {report['total_targets_audited']} primary AI ecosystem releases (30-day window)")
    print(f"Capture Rate:     {report['captured_count']}/{report['total_targets_audited']} ({report['capture_rate_pct']}%)")
    print(f"Missed Count:     {report['missed_count']}")
    print("\n--- DETAILED CAPTURE LOG ---")
    for r in report["audit_items"]:
        status = "✅ CAPTURED" if r["captured"] else "❌ MISSED"
        count_str = f"({r['match_count']:>3} entries)" if r["captured"] else "           "
        print(f"  {status} {count_str} | {r['target']:<35} | Earliest: {str(r['earliest_date'])[:10]}")
        if r["captured"] and r["sample_title"]:
            print(f"       -> Sample: {r['sample_title'][:70]}...")
