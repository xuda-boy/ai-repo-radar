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
