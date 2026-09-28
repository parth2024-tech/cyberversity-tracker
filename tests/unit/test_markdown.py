"""Unit tests for HTMLToMarkdownConverter."""

from ai_security_monitor.core.markdown import (
    HTMLToMarkdownConverter,
    markdown_converter,
)


def test_markdown_basic_formatting():
    html_raw = """
    <html>
        <body>
            <h1>vLLM High-Throughput Inference</h1>
            <p>Engine for fast LLM serving with <strong>PagedAttention</strong>.</p>
            <p>Check out the <em>official repository</em> for details.</p>
        </body>
    </html>
    """
    md = markdown_converter.convert(html_raw)
    assert "# vLLM High-Throughput Inference" in md
    assert "**PagedAttention**" in md
    assert "*official repository*" in md


def test_markdown_strips_noise_tags():
    html_raw = """
    <div>
        <nav><a href="/home">Home</a><a href="/about">About</a></nav>
        <h2>Seminal Research</h2>
        <p>Breakthrough paper announcement.</p>
        <script>alert("tracker");</script>
        <style>.ad { display: block; }</style>
        <footer>Copyright 2026 AI Lab</footer>
    </div>
    """
    md = markdown_converter.convert(html_raw)
    assert "## Seminal Research" in md
    assert "Breakthrough paper announcement" in md
    assert "tracker" not in md
    assert ".ad" not in md
    assert "Home" not in md
    assert "Copyright 2026" not in md


def test_markdown_lists_and_links():
    html_raw = """
    <div>
        <p>Key models:</p>
        <ul>
            <li><a href="https://example.com/deepseek">DeepSeek-R1</a></li>
            <li>Qwen 2.5 72B</li>
        </ul>
        <ol>
            <li>Step One</li>
            <li>Step Two</li>
        </ol>
    </div>
    """
    md = markdown_converter.convert(html_raw)
    assert "- [DeepSeek-R1](https://example.com/deepseek)" in md
    assert "- Qwen 2.5 72B" in md
    assert "1. Step One" in md
    assert "2. Step Two" in md


def test_markdown_table_conversion():
    html_raw = """
    <table>
        <tr><th>Model</th><th>Parameters</th></tr>
        <tr><td>DeepSeek-V3</td><td>671B</td></tr>
        <tr><td>Llama-3.3</td><td>70B</td></tr>
    </table>
    """
    md = markdown_converter.convert(html_raw)
    assert "| Model | Parameters |" in md
    assert "| --- | --- |" in md
    assert "| DeepSeek-V3 | 671B |" in md
    assert "| Llama-3.3 | 70B |" in md


def test_markdown_codeblock():
    html_raw = """
    <pre><code>pip install vllm
vllm serve deepseek-ai/DeepSeek-R1</code></pre>
    """
    md = markdown_converter.convert(html_raw)
    assert "```" in md
    assert "pip install vllm" in md
