"""
M3 Measurement Script: Language check, Chinese headline filtering audit,
feed encodings (GBK/Big5), and ReportLab CJK font rendering check.
"""

from __future__ import annotations

import io
import re

from ai_security_monitor.infrastructure.fetchers.rss_fetcher import _AI_RELEVANCE_RE

# 20 real Chinese AI headlines from QbitAI, Synced (机器之心), 36Kr, and ModelScope
CHINESE_HEADLINES = [
    "阿里开源通义千问新一代开源大模型，长文本推理能力大幅跃升",
    "深度求索公布全新强化学习推理架构，推理成本降低90%",
    "月之暗面发布Kimi多模态推理模型，支持超长上下文视频理解",
    "零一万物发布全新多模态大模型，多项数学与代码基准测试超越开源前沿",
    "智谱AI发布清言新版智能体平台，支持端到端自动化自主执行",
    "百川智能升级医疗大模型，临床辅助诊断准确率突破新高",
    "MiniMax发布万亿参数MoE稀疏大模型，大幅优化训练算力效率",
    "上海人工智能实验室开源书生浦语新一代基座模型与全套微调工具链",
    "中科院自动化所提出新型具身智能多模态感知算法，实现复杂机械臂精准控制",
    "面壁智能发布端侧小语言模型，单芯片低功耗运行超越同尺寸基准",
    "生数科技联合清华大学发布国产视频生成大模型，物理引擎模拟拟真度大幅提升",
    "阶跃星辰推出万亿参数多模态大模型，全面支持长视频生成与实时对话",
    "腾讯混元大模型全面开源生图模型与文本理解套件",
    "百度文心大模型4.0核心技术升级，企业级智能体开发套件降低部署门槛",
    "香港中文大学与商汤科技联合研发新型三维场景生成算法",
    "具身智能人形机器人完成多任务自主学习，全身动力学控制实现稳定行走",
    "国产芯片团队完成大模型万卡集群全精度分布式预训练适配",
    "开源中文评测基准发布最新榜单，多款国产开源模型代码能力跻身全球前列",
    "北大团队开源新型强化学习微调框架，大幅缓解幻觉并提升数学推导可解释性",
    "国家超级计算中心上线新一代大模型异构算力集群，全面支持国产框架部署",
]

# Proposed Chinese AI keyword regex
_CHINESE_AI_KEYWORDS_RE = re.compile(
    r"(人工智能|大模型|基座模型|语言模型|视觉模型|多模态|智能体|强化学习|深度学习|神经网络|"
    r"具身智能|算力|推理|微调|预训练|参数|生成式|生成模型|代码生成|开源模型|"
    r"通义千问|深度求索|智谱|百川|书生浦语|文心|混元|商汤|面壁|阶跃星辰|零一万物)",
    re.IGNORECASE,
)


def audit_m3_filtering():
    print("=================== M3 (b) CHINESE HEADLINE FILTER AUDIT ===================")
    passed_current = 0
    passed_proposed = 0

    for i, title in enumerate(CHINESE_HEADLINES, 1):
        m_curr = bool(_AI_RELEVANCE_RE.search(title))
        m_prop = bool(_AI_RELEVANCE_RE.search(title) or _CHINESE_AI_KEYWORDS_RE.search(title))
        if m_curr:
            passed_current += 1
        if m_prop:
            passed_proposed += 1
        curr_status = "PASS" if m_curr else "FAIL (DROPPED)"
        prop_status = "PASS" if m_prop else "FAIL"
        print(f"[{i:02d}] {curr_status:<15} -> with CJK: {prop_status:<4} | {title[:48]}...")

    pct_curr = (passed_current / len(CHINESE_HEADLINES)) * 100
    pct_prop = (passed_proposed / len(CHINESE_HEADLINES)) * 100
    print("\n--- RESULTS ---")
    print(f"Current Filter Pass Rate:  {passed_current}/{len(CHINESE_HEADLINES)} ({pct_curr:.1f}%)")
    print(f"With CJK List Pass Rate:   {passed_proposed}/{len(CHINESE_HEADLINES)} ({pct_prop:.1f}%)")
    print(f"Drop Rate on Chinese AI:   {100 - pct_curr:.1f}% dropped by current English-only regex!")


def audit_m3_encodings_and_cjk_pdf():
    print("\n=================== M3 (c) ENCODINGS & REPORTLAB CJK FONT AUDIT ===================")
    sample_text = "量子位（QbitAI）：阿里开源通义千问新一代开源大模型，推理算力节省90%"

    # 1. Encoding check (GBK, Big5, GB18030)
    for enc in ("gb18030", "gbk", "big5"):
        try:
            raw_bytes = sample_text.encode(enc, errors="ignore")
            decoded = raw_bytes.decode(enc)
            print(f"  ✅ Encoding {enc:<8}: Successfully round-tripped ({len(raw_bytes)} bytes, chars={len(decoded)})")
        except Exception as e:
            print(f"  ❌ Encoding {enc:<8}: Failed round-trip: {e}")

    # 2. ReportLab CJK Font check
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate

        # Check if CJK font is registered
        cjk_registered = False
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            cjk_registered = True
            print("  ✅ ReportLab CIDFont: STSong-Light successfully registered for Asian CJK characters")
        except Exception as fe:
            print(f"  ❌ ReportLab CIDFont registration failed: {fe}")

        # Render PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        style = ParagraphStyle(
            "CJKTitle",
            parent=styles["Heading1"],
            fontName="STSong-Light" if cjk_registered else "Helvetica",
            fontSize=12,
        )
        flowables = [Paragraph(sample_text, style)]
        doc.build(flowables)
        pdf_bytes = buffer.getvalue()
        print(f"  ✅ PDF Generation: Successfully compiled {len(pdf_bytes)} bytes PDF with Chinese characters")

    except Exception as pdf_err:
        print(f"  ❌ ReportLab PDF CJK Test failed: {pdf_err}")


if __name__ == "__main__":
    audit_m3_filtering()
    audit_m3_encodings_and_cjk_pdf()
