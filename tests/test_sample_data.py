from ai_repo_radar.sample_data import load_sample_fixture


def test_packaged_sample_uses_canonical_real_repository_links() -> None:
    fixture = load_sample_fixture()
    candidates = {
        repository.full_name
        for repository in fixture.repositories
        if "fixture-filter" not in repository.discovery_sources
    }

    assert candidates == {
        "Arize-ai/phoenix",
        "confident-ai/deepeval",
        "huggingface/smolagents",
        "langchain-ai/langgraph",
        "langfuse/langfuse",
        "ollama/ollama",
        "promptfoo/promptfoo",
        "protectai/llm-guard",
        "run-llama/llama_index",
        "vllm-project/vllm",
    }
    assert all(
        repository.html_url.rstrip("/")
        == f"https://github.com/{repository.full_name}"
        for repository in fixture.repositories
    )


def test_packaged_sample_has_distinct_repository_specific_copy() -> None:
    fixture = load_sample_fixture()
    expected_fragments = {
        "Arize-ai/phoenix": "追踪调用链",
        "confident-ai/deepeval": "测试用例与评测指标",
        "huggingface/smolagents": "轻量与可读性",
        "langchain-ai/langgraph": "持久化执行",
        "langfuse/langfuse": "提示词版本和数据集",
        "ollama/ollama": "模型下载、运行与管理",
        "promptfoo/promptfoo": "红队与漏洞测试",
        "protectai/llm-guard": "输入与输出扫描器",
        "run-llama/llama_index": "数据连接、索引、检索",
        "vllm-project/vllm": "高吞吐和显存效率",
    }

    assert set(fixture.enhancements) == set(expected_fragments)
    assert len({item.summary_zh for item in fixture.enhancements.values()}) == 10
    assert len({item.quick_start for item in fixture.enhancements.values()}) == 10
    assert all(
        expected_fragment in fixture.enhancements[full_name].summary_zh
        for full_name, expected_fragment in expected_fragments.items()
    )
    assert all(
        "适合作为近期 AI 开源方向的源码观察样本" not in item.summary_zh
        for item in fixture.enhancements.values()
    )
