from __future__ import annotations

from ai_repo_radar.models import ModelStatus, ReportStatus
from ai_repo_radar.pipeline import EnhancementResult, run_pipeline


class FailingEnhancer:
    def enhance(self, recommendations, readmes) -> EnhancementResult:
        return EnhancementResult(
            enhancements=[],
            error_category="timeout",
            message="模型超时；规则推荐仍然可用。",
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
