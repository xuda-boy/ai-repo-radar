from __future__ import annotations

from ai_repo_radar.models import ModelStatus, ReportStatus, RepositoryEnhancement
from ai_repo_radar.pipeline import EnhancementResult, run_pipeline


class FailingEnhancer:
    def enhance(self, recommendations, readmes) -> EnhancementResult:
        return EnhancementResult(
            enhancements=[],
            error_category="timeout",
            message="模型超时；规则推荐仍然可用。",
        )


class PartiallyFailingEnhancer:
    def enhance(self, recommendations, readmes) -> EnhancementResult:
        first = recommendations[0].repository.full_name
        return EnhancementResult(
            enhancements=[
                RepositoryEnhancement(
                    full_name=first,
                    summary_zh="该项目已成功生成中文摘要。",
                    quick_start="先运行公开的最小示例。",
                )
            ],
            error_category="invalid_response",
            message="其余项目的模型响应无效。",
        )


def test_model_failure_preserves_rule_ranking_and_marks_degraded(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    data_store.append_snapshots(sample_fixture.historical_snapshots)
    result = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=FailingEnhancer(),
        generated_at=sample_fixture.generated_at,
    )

    assert result.report.status == ReportStatus.DEGRADED
    assert result.report.model_status == ModelStatus.DEGRADED
    assert result.report.model_error_category == "timeout"
    assert len(result.report.recommendations) == 8
    assert all(
        item.model_status == ModelStatus.DEGRADED
        for item in result.report.recommendations
    )
    assert result.snapshots_written == len(sample_fixture.repositories)


def test_partial_model_failure_preserves_valid_enhancements(
    sample_fixture,
    data_store,
    radar_config,
) -> None:
    data_store.append_snapshots(sample_fixture.historical_snapshots)

    result = run_pipeline(
        sample_fixture.repositories,
        store=data_store,
        config=radar_config,
        report_date=sample_fixture.report_date,
        readmes=sample_fixture.readmes,
        enhancer=PartiallyFailingEnhancer(),
        generated_at=sample_fixture.generated_at,
    )

    assert result.report.status == ReportStatus.DEGRADED
    assert result.report.model_error_category == "invalid_response"
    assert result.report.recommendations[0].model_status == ModelStatus.ENHANCED
    assert result.report.recommendations[0].summary_zh == "该项目已成功生成中文摘要。"
    assert all(
        item.model_status == ModelStatus.DEGRADED
        for item in result.report.recommendations[1:]
    )
