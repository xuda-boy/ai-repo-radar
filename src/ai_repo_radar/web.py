from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ai_repo_radar.cache import CacheRepository, SavedItem, rebuild_cache
from ai_repo_radar.feedback import create_feedback_event, create_feedback_retraction
from ai_repo_radar.models import (
    DailyReport,
    EvidenceKind,
    FeedbackAction,
    Recommendation,
    RecommendationKind,
    SyncStatus,
)
from ai_repo_radar.sample_data import (
    canonical_fixture_repository_name,
    is_fixture_report,
    is_fixture_repository,
)
from ai_repo_radar.storage import JsonDataStore
from ai_repo_radar.sync import (
    private_repository_root,
    pull_private_data_safely,
    sync_private_data_safely,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
KIND_LABELS = {
    RecommendationKind.INTEREST: "兴趣匹配",
    RecommendationKind.RISING: "快速涨星",
    RecommendationKind.EXPLORATION: "探索",
}
KIND_ENGLISH = {
    RecommendationKind.INTEREST: "Interest match",
    RecommendationKind.RISING: "Fast rising",
    RecommendationKind.EXPLORATION: "Exploration",
}
FEEDBACK_ACTIONS = (
    (FeedbackAction.MORE_LIKE, "更多此类", "arrow"),
    (FeedbackAction.SAVE, "收藏", "bookmark"),
    (FeedbackAction.IRRELEVANT, "不相关", "minus"),
    (FeedbackAction.KNOWN, "已了解", "check"),
)
FEEDBACK_ACTION_LABELS = {action: label for action, label, _icon in FEEDBACK_ACTIONS}
FEEDBACK_ACTION_LABELS[FeedbackAction.REVOKE] = "撤回反馈"
SYNC_STATUS_LABELS = {
    SyncStatus.LOCAL: "本地待同步",
    SyncStatus.SYNCING: "同步中",
    SyncStatus.SYNCED: "已同步",
    SyncStatus.PENDING_RETRY: "等待重试",
}


def _format_number(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m".replace(".0m", "m")
    if value >= 1_000:
        return f"{value / 1_000:.1f}k".replace(".0k", "k")
    return f"{value:,}"


def _format_delta(value: int | None, *, estimated: bool = False) -> str:
    if value is None:
        return "快照不足"
    prefix = "约 " if estimated else ""
    sign = "+" if value >= 0 else ""
    return f"{prefix}{sign}{value:,}"


def _relative_time(value: datetime, reference: datetime) -> str:
    current = reference if reference.tzinfo else reference.replace(tzinfo=UTC)
    target = value if value.tzinfo else value.replace(tzinfo=UTC)
    seconds = max(0, int((current - target).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


def _health_label(recommendation: Recommendation, report: DailyReport) -> str:
    pushed = recommendation.repository.pushed_at
    generated = report.generated_at
    if pushed.tzinfo is None:
        pushed = pushed.replace(tzinfo=UTC)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    age = max(0, (generated - pushed).days)
    if age <= 7:
        return "维护活跃"
    if age <= 30:
        return "持续维护"
    return "低频维护"


def _report_mix(report: DailyReport) -> str:
    counts = Counter(item.kind for item in report.recommendations)
    return " · ".join(
        (
            f"兴趣 {counts[RecommendationKind.INTEREST]}",
            f"快速涨星 {counts[RecommendationKind.RISING]}",
            f"探索 {counts[RecommendationKind.EXPLORATION]}",
        )
    )


def _today_overview(report: DailyReport | None) -> dict[str, object]:
    if report is None:
        return {
            "recommendations": 0,
            "candidates": 0,
            "delta_24h": "—",
            "interest": 0,
            "rising": 0,
            "exploration": 0,
            "enhanced": 0,
            "enhanced_percent": "0%",
        }
    counts = Counter(item.kind for item in report.recommendations)
    available_deltas = [
        item.growth.delta_24h
        for item in report.recommendations
        if item.growth.delta_24h is not None
    ]
    enhanced = sum(bool(item.summary_zh) for item in report.recommendations)
    total = len(report.recommendations)
    return {
        "recommendations": total,
        "candidates": report.stats.candidate_count,
        "delta_24h": _format_delta(sum(available_deltas)) if available_deltas else "快照不足",
        "interest": counts[RecommendationKind.INTEREST],
        "rising": counts[RecommendationKind.RISING],
        "exploration": counts[RecommendationKind.EXPLORATION],
        "enhanced": enhanced,
        "enhanced_percent": f"{round(enhanced / total * 100)}%" if total else "0%",
    }


def _chart_geometry(recommendation: Recommendation) -> dict[str, object]:
    raw_points = recommendation.growth.history
    if not raw_points:
        return {"available": False, "points": []}
    points = raw_points if len(raw_points) > 1 else [raw_points[0], raw_points[0]]
    width, height = 720.0, 190.0
    left, right, top, bottom = 44.0, 18.0, 18.0, 30.0
    inner_width = width - left - right
    inner_height = height - top - bottom
    minimum = min(point.stars for point in points)
    maximum = max(point.stars for point in points)
    padding = max(1.0, (maximum - minimum) * 0.14)
    low, high = minimum - padding, maximum + padding

    coordinates: list[dict[str, object]] = []
    for index, point in enumerate(points):
        x = left + (inner_width * index / max(1, len(points) - 1))
        y = top + inner_height - ((point.stars - low) / (high - low)) * inner_height
        coordinates.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "date": point.observed_on.strftime("%m/%d"),
                "stars": point.stars,
                "stars_label": f"{point.stars:,}",
                "last": index == len(points) - 1,
            }
        )
    path = " ".join(
        f"{'M' if index == 0 else 'L'} {point['x']} {point['y']}"
        for index, point in enumerate(coordinates)
    )
    area = (
        f"{path} L {coordinates[-1]['x']} {top + inner_height} "
        f"L {coordinates[0]['x']} {top + inner_height} Z"
    )
    label_indexes = sorted({0, (len(coordinates) - 1) // 2, len(coordinates) - 1})
    return {
        "available": True,
        "path": path,
        "area": area,
        "points": coordinates,
        "grid_y": [top, top + inner_height / 2, top + inner_height],
        "labels": [coordinates[index] for index in label_indexes],
        "start": raw_points[0].stars,
        "end": raw_points[-1].stars,
        "max": maximum,
    }


def _recommendation_view(recommendation: Recommendation, report: DailyReport) -> dict[str, object]:
    estimated = recommendation.growth.evidence == EvidenceKind.ESTIMATED
    return {
        "item": recommendation,
        "kind_label": KIND_LABELS[recommendation.kind],
        "kind_english": KIND_ENGLISH[recommendation.kind],
        "evidence_label": _evidence_label(recommendation),
        "stars": _format_number(recommendation.repository.stars),
        "delta_24h": _format_delta(recommendation.growth.delta_24h, estimated=estimated),
        "delta_7d": _format_delta(recommendation.growth.delta_7d, estimated=estimated),
        "updated": _relative_time(recommendation.repository.pushed_at, report.generated_at),
        "health": _health_label(recommendation, report),
        "chart": _chart_geometry(recommendation),
    }


def _evidence_label(recommendation: Recommendation) -> str:
    if is_fixture_repository(recommendation.repository):
        return "样例"
    if recommendation.growth.evidence == EvidenceKind.ESTIMATED:
        return "估算"
    return "实测"


def _select_recommendation(report: DailyReport, repo_full_name: str | None) -> Recommendation | None:
    if repo_full_name:
        selected = next(
            (
                item
                for item in report.recommendations
                if item.repository.full_name == repo_full_name
            ),
            None,
        )
        if selected:
            return selected
    return report.recommendations[0] if report.recommendations else None


def _select_report(cache: CacheRepository, raw_date: str | None) -> DailyReport | None:
    if raw_date:
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="date must use YYYY-MM-DD") from error
        report = cache.get_report(parsed)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return report
    return cache.latest_report()


def _sync_label(pending: int, *, configured: bool) -> str:
    if not configured:
        return f"{pending} 条反馈仅本地" if pending else "仅本地模式"
    return f"{pending} 条反馈待同步" if pending else "数据已同步"


def _sync_tone(status: SyncStatus) -> str:
    if status == SyncStatus.SYNCED:
        return "success"
    if status == SyncStatus.PENDING_RETRY:
        return "error"
    return "warning"


def _beijing_time(value: datetime) -> datetime:
    current = value if value.tzinfo else value.replace(tzinfo=UTC)
    return current.astimezone(BEIJING)


def _data_freshness(
    report: DailyReport | None,
    *,
    configured: bool,
    now: datetime | None = None,
) -> dict[str, str]:
    if report is None:
        return {
            "label": "尚无日报",
            "tone": "error" if configured else "warning",
            "detail": "还没有可展示的日报；请先运行每日任务。",
        }
    if is_fixture_report(report):
        return {
            "label": "固定样例",
            "tone": "sample",
            "detail": f"当前为 {report.report_date.isoformat()} 固定样例，不会自动更新。",
        }
    if not configured:
        return {
            "label": "本地数据",
            "tone": "warning",
            "detail": (
                f"最新日报为 {report.report_date.isoformat()}；"
                "当前目录未连接私人 Git 仓，无法自动拉取。"
            ),
        }

    current = now.astimezone(BEIJING) if now else datetime.now(BEIJING)
    lag_days = max(0, (current.date() - report.report_date).days)
    if lag_days == 0:
        return {
            "label": "今日数据",
            "tone": "success",
            "detail": f"已加载 {report.report_date.isoformat()} 日报。",
        }
    if lag_days == 1:
        return {
            "label": "等待今日日报",
            "tone": "warning",
            "detail": f"当前仍是 {report.report_date.isoformat()}，后台会继续检查云端更新。",
        }
    return {
        "label": f"数据已过期 {lag_days} 天",
        "tone": "error",
        "detail": f"最新日报停留在 {report.report_date.isoformat()}，建议立即检查更新。",
    }


def _interval_label(seconds: float) -> str:
    if seconds <= 0:
        return "已关闭"
    if seconds < 60:
        return f"{int(seconds)} 秒"
    return f"{max(1, round(seconds / 60))} 分钟"


def _same_origin(request: Request) -> bool:
    value = request.headers.get("origin") or request.headers.get("referer")
    if not value:
        return True
    try:
        from urllib.parse import urlparse

        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"}


def create_app(
    *,
    data_root: Path,
    database_path: Path,
    auto_sync_interval_seconds: float = 300,
) -> FastAPI:
    if auto_sync_interval_seconds < 0:
        raise ValueError("auto sync interval cannot be negative")
    store = JsonDataStore(data_root)
    store.initialize()
    resolved_database = database_path.expanduser().resolve()
    if not resolved_database.exists():
        rebuild_cache(store, resolved_database)
    cache = CacheRepository(resolved_database)
    templates = Jinja2Templates(directory=PACKAGE_ROOT / "templates")
    templates.env.filters["compact_number"] = _format_number
    templates.env.filters["delta"] = _format_delta
    templates.env.filters["urlquote"] = lambda value: quote(str(value), safe="")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        worker: threading.Thread | None = None
        if application.state.sync_configured and auto_sync_interval_seconds > 0:
            worker = threading.Thread(
                target=application.state.auto_refresh_worker,
                name="ai-repo-radar-auto-refresh",
                daemon=True,
            )
            application.state.auto_refresh_thread = worker
            worker.start()
        try:
            yield
        finally:
            application.state.auto_refresh_stop.set()
            if worker:
                worker.join(timeout=2)

    app = FastAPI(
        title="AI Repo Radar",
        version="0.2.2",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.state.store = store
    app.state.cache = cache
    app.state.sync_lock = threading.Lock()
    app.state.feedback_lock = threading.Lock()
    app.state.sync_configured = private_repository_root(store.root) is not None
    app.state.auto_sync_interval_seconds = auto_sync_interval_seconds
    app.state.auto_refresh_stop = threading.Event()
    app.state.auto_refresh_thread = None
    app.state.last_data_refresh_at = datetime.now(UTC) if app.state.sync_configured else None
    app.state.last_data_refresh_success = None
    app.state.last_data_refresh_error_category = None

    def refresh_private_data(*, blocking: bool = False) -> dict[str, object]:
        if not app.state.sync_configured:
            return {
                "success": False,
                "busy": False,
                "changed": False,
                "message": "当前数据目录未连接私人 Git 仓，无法检查云端日报。",
                "tone": "warning",
                "report_date": cache.latest_report().report_date
                if cache.latest_report()
                else None,
            }
        if not app.state.sync_lock.acquire(blocking=blocking):
            return {
                "success": False,
                "busy": True,
                "changed": False,
                "message": "已有更新或反馈同步正在运行，请稍后再试。",
                "tone": "warning",
                "report_date": cache.latest_report().report_date
                if cache.latest_report()
                else None,
            }

        before = cache.latest_report()
        before_date = before.report_date if before else None
        try:
            result = pull_private_data_safely(store)
            if result.success:
                rebuild_cache(store, resolved_database)
            after = cache.latest_report()
            after_date = after.report_date if after else None
            changed = result.changed or before_date != after_date
            app.state.last_data_refresh_at = datetime.now(UTC)
            app.state.last_data_refresh_success = result.success
            app.state.last_data_refresh_error_category = result.error_category
            if not result.success:
                message = (
                    "更新未完成，当前数据没有被覆盖。"
                    "请检查网络、私人仓工作树与 Git 凭据。"
                )
                tone = "error"
            elif after_date != before_date and after_date is not None:
                message = f"已更新至 {after_date.isoformat()} 日报。"
                tone = "success"
            elif changed:
                message = "私人数据已更新，当前最新日报日期未变化。"
                tone = "success"
            else:
                message = "已检查云端，当前没有新日报。"
                tone = "success"
            return {
                "success": result.success,
                "busy": False,
                "changed": changed,
                "message": message,
                "tone": tone,
                "report_date": after_date,
            }
        except Exception:
            LOGGER.exception("automatic private data refresh failed")
            app.state.last_data_refresh_at = datetime.now(UTC)
            app.state.last_data_refresh_success = False
            app.state.last_data_refresh_error_category = "cache_error"
            current = cache.latest_report()
            return {
                "success": False,
                "busy": False,
                "changed": False,
                "message": "缓存更新未完成，当前数据没有被覆盖，请稍后重试。",
                "tone": "error",
                "report_date": current.report_date if current else None,
            }
        finally:
            app.state.sync_lock.release()

    def auto_refresh_worker() -> None:
        while not app.state.auto_refresh_stop.wait(auto_sync_interval_seconds):
            refresh_private_data()

    app.state.refresh_private_data = refresh_private_data
    app.state.auto_refresh_worker = auto_refresh_worker
    app.mount("/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    def sync_context(
        request: Request,
        *,
        message: str | None = None,
        tone: str | None = None,
        data_message: str | None = None,
        data_tone: str | None = None,
        latest_report: DailyReport | None = None,
    ) -> dict[str, object]:
        pending_events = list(reversed(store.pending_feedback_events()))
        pending = len(pending_events)
        configured = bool(app.state.sync_configured)
        current_report = latest_report or cache.latest_report()
        freshness = _data_freshness(current_report, configured=configured)
        if freshness["tone"] in {"warning", "error", "sample"}:
            system_label = freshness["label"]
            system_tone = freshness["tone"]
        elif pending:
            system_label = _sync_label(pending, configured=configured)
            system_tone = "warning"
        else:
            system_label = "今日数据已同步"
            system_tone = "success"
        refreshed_at = app.state.last_data_refresh_at
        return {
            "request": request,
            "pending_sync": pending,
            "pending_feedback": [
                {
                    "repo_full_name": canonical_fixture_repository_name(event.repo_full_name),
                    "action_label": FEEDBACK_ACTION_LABELS[event.action],
                    "effective_date": event.effective_date.strftime("%m/%d"),
                }
                for event in pending_events[:5]
            ],
            "pending_feedback_extra": max(0, pending - 5),
            "sync_configured": configured,
            "sync_label": _sync_label(pending, configured=configured),
            "sync_message": message,
            "sync_tone": tone,
            "data_freshness_label": freshness["label"],
            "data_freshness_tone": freshness["tone"],
            "data_freshness_detail": freshness["detail"],
            "data_refresh_message": data_message,
            "data_refresh_tone": data_tone,
            "data_last_checked": (
                _beijing_time(refreshed_at).strftime("%m-%d %H:%M")
                if refreshed_at
                else "尚未检查"
            ),
            "auto_sync_interval_label": _interval_label(auto_sync_interval_seconds),
            "auto_sync_enabled": configured and auto_sync_interval_seconds > 0,
            "system_status_label": system_label,
            "system_status_tone": system_tone,
            "csrf_token": app.state.csrf_token,
        }

    def base_context(request: Request, *, page: str, title: str, subtitle: str) -> dict[str, object]:
        latest = cache.latest_report()
        context = {
            "request": request,
            "page": page,
            "page_title": title,
            "page_subtitle": subtitle,
            "latest_report": latest,
        }
        context.update(sync_context(request, latest_report=latest))
        return context

    def feedback_ledger_context(request: Request) -> dict[str, object]:
        events = store.load_feedback_events(include_outbox=True)
        retractions = {
            event.reverts_event_id: event
            for event in events
            if event.action == FeedbackAction.REVOKE and event.reverts_event_id is not None
        }
        originals = [event for event in events if event.action != FeedbackAction.REVOKE]
        retracted_event_ids = set(retractions).intersection(
            event.event_id for event in originals
        )
        today_date = date.today()
        items: list[dict[str, object]] = []
        for event in reversed(originals):
            retraction = retractions.get(event.event_id)
            if retraction is None:
                state_label = "次日生效" if event.effective_date > today_date else "生效中"
                state_tone = "active"
            elif retraction.effective_date > today_date:
                state_label = "撤回待生效"
                state_tone = "pending"
            else:
                state_label = "已撤回"
                state_tone = "revoked"
            items.append(
                {
                    "event_id": str(event.event_id),
                    "repo_full_name": canonical_fixture_repository_name(event.repo_full_name),
                    "action_label": FEEDBACK_ACTION_LABELS[event.action],
                    "created_at": event.created_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                    "effective_date": event.effective_date.isoformat(),
                    "sync_label": SYNC_STATUS_LABELS[event.sync_status],
                    "sync_tone": _sync_tone(event.sync_status),
                    "state_label": state_label,
                    "state_tone": state_tone,
                    "retraction": (
                        {
                            "effective_date": retraction.effective_date.isoformat(),
                            "sync_label": SYNC_STATUS_LABELS[retraction.sync_status],
                            "sync_tone": _sync_tone(retraction.sync_status),
                        }
                        if retraction
                        else None
                    ),
                }
            )
        return {
            "request": request,
            "feedback_items": items,
            "feedback_total": len(originals),
            "feedback_active": len(originals) - len(retracted_event_ids),
            "feedback_revoked": len(retracted_event_ids),
            "feedback_pending": len(store.pending_feedback_events()),
            "csrf_token": app.state.csrf_token,
        }

    def recommendation_context(
        request: Request,
        report: DailyReport,
        recommendation: Recommendation,
    ) -> dict[str, object]:
        feedback = cache.feedback_for_report(report.report_date).get(
            recommendation.repository.full_name
        )
        context = {
            "request": request,
            "report": report,
            "recommendation": recommendation,
            "view": _recommendation_view(recommendation, report),
            "feedback_actions": FEEDBACK_ACTIONS,
            "selected_action": feedback.action if feedback else None,
            "csrf_token": app.state.csrf_token,
        }
        context.update(sync_context(request))
        return context

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/data-status")
    def data_status(request: Request) -> dict[str, object]:
        latest = cache.latest_report()
        context = sync_context(request, latest_report=latest)
        return {
            "report_date": latest.report_date.isoformat() if latest else None,
            "label": context["data_freshness_label"],
            "tone": context["data_freshness_tone"],
            "detail": context["data_freshness_detail"],
            "last_checked": context["data_last_checked"],
            "system_label": context["system_status_label"],
            "system_tone": context["system_status_tone"],
            "configured": context["sync_configured"],
        }

    @app.post("/refresh-data", response_class=HTMLResponse)
    def refresh_data(
        request: Request,
        csrf_token: str = Form(...),
    ):
        if not hmac.compare_digest(csrf_token, app.state.csrf_token) or not _same_origin(request):
            raise HTTPException(status_code=403, detail="invalid local form token")

        outcome = refresh_private_data()
        latest = cache.latest_report()
        context = sync_context(
            request,
            data_message=str(outcome["message"]),
            data_tone=str(outcome["tone"]),
            latest_report=latest,
        )
        if request.headers.get("HX-Request") != "true":
            return RedirectResponse(url="/", status_code=303)
        response = templates.TemplateResponse(
            request=request,
            name="partials/data_refresh_panel.html",
            context=context,
        )
        response.headers["HX-Trigger"] = json.dumps(
            {
                "radar:dataUpdated": {
                    "message": outcome["message"],
                    "reportDate": latest.report_date.isoformat() if latest else None,
                    "label": context["data_freshness_label"],
                    "tone": context["data_freshness_tone"],
                    "detail": context["data_freshness_detail"],
                    "lastChecked": context["data_last_checked"],
                    "systemLabel": context["system_status_label"],
                    "systemTone": context["system_status_tone"],
                    "changed": outcome["changed"],
                }
            },
            ensure_ascii=True,
        )
        if outcome["changed"]:
            response.headers["HX-Refresh"] = "true"
        return response

    @app.get("/", response_class=HTMLResponse)
    def today(request: Request, repo: str | None = None):
        report = cache.latest_report()
        context = base_context(
            request,
            page="today",
            title="今日推荐",
            subtitle="在多条信号里，找到今天真正值得打开的项目。",
        )
        selected = _select_recommendation(report, repo) if report else None
        context.update(
            {
                "report": report,
                "selected": selected,
                "selected_view": _recommendation_view(selected, report)
                if selected and report
                else None,
                "mix": _report_mix(report) if report else "尚无日报",
                "overview": _today_overview(report),
            }
        )
        if selected and report:
            context.update(recommendation_context(request, report, selected))
        return templates.TemplateResponse(request=request, name="today.html", context=context)

    @app.get("/partials/recommendation", response_class=HTMLResponse)
    def recommendation_partial(request: Request, repo: str):
        report = cache.latest_report()
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        recommendation = _select_recommendation(report, repo)
        if recommendation is None or recommendation.repository.full_name != repo:
            raise HTTPException(status_code=404, detail="recommendation not found")
        context = recommendation_context(request, report, recommendation)
        return templates.TemplateResponse(
            request=request,
            name="partials/recommendation_detail.html",
            context=context,
        )

    @app.post("/feedback", response_class=HTMLResponse)
    def feedback(
        request: Request,
        repo_full_name: str = Form(...),
        report_date: str = Form(...),
        action: str = Form(...),
        csrf_token: str = Form(...),
    ):
        if not hmac.compare_digest(csrf_token, app.state.csrf_token) or not _same_origin(request):
            raise HTTPException(status_code=403, detail="invalid local form token")
        try:
            parsed_date = date.fromisoformat(report_date)
            parsed_action = FeedbackAction(action)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid feedback payload") from error
        if parsed_action == FeedbackAction.REVOKE:
            raise HTTPException(status_code=400, detail="invalid feedback payload")
        report = cache.get_report(parsed_date)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        recommendation = _select_recommendation(report, repo_full_name)
        if recommendation is None or recommendation.repository.full_name != repo_full_name:
            raise HTTPException(status_code=404, detail="recommendation not found")
        event = create_feedback_event(
            repo_full_name=repo_full_name,
            action=parsed_action,
            topics=recommendation.repository.topics,
            report_date=parsed_date,
        )
        store.write_feedback_event(event, to_outbox=True)
        cache.insert_feedback(event, recommendation)
        if request.headers.get("HX-Request") != "true":
            return RedirectResponse(
                url=f"/?repo={quote(repo_full_name, safe='')}",
                status_code=303,
            )
        context = recommendation_context(request, report, recommendation)
        response = templates.TemplateResponse(
            request=request,
            name="partials/feedback_bar.html",
            context=context,
        )
        response.headers["HX-Trigger"] = json.dumps(
            {
                "radar:feedbackSaved": {
                    "message": f"{repo_full_name} · 反馈已保存到本地",
                    "pending": context["pending_sync"],
                    "configured": context["sync_configured"],
                    "label": context["sync_label"],
                }
            },
            ensure_ascii=True,
        )
        return response

    @app.get("/feedback", response_class=HTMLResponse)
    def feedback_ledger(request: Request):
        context = base_context(
            request,
            page="feedback",
            title="反馈记录",
            subtitle="看清每次偏好操作，并安全撤回误触反馈。",
        )
        context.update(feedback_ledger_context(request))
        return templates.TemplateResponse(request=request, name="feedback.html", context=context)

    @app.get("/partials/feedback-ledger", response_class=HTMLResponse)
    def feedback_ledger_partial(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="partials/feedback_ledger.html",
            context=feedback_ledger_context(request),
        )

    @app.post("/feedback/{event_id}/revoke", response_class=HTMLResponse)
    def revoke_feedback(
        request: Request,
        event_id: UUID,
        csrf_token: str = Form(...),
    ):
        if not hmac.compare_digest(csrf_token, app.state.csrf_token) or not _same_origin(request):
            raise HTTPException(status_code=403, detail="invalid local form token")
        with app.state.feedback_lock:
            events = store.load_feedback_events(include_outbox=True)
            target = next((event for event in events if event.event_id == event_id), None)
            if target is None or target.action == FeedbackAction.REVOKE:
                raise HTTPException(status_code=404, detail="feedback event not found")
            if any(event.reverts_event_id == event_id for event in events):
                raise HTTPException(status_code=409, detail="feedback event already revoked")
            retraction = create_feedback_retraction(target)
            store.write_feedback_event(retraction, to_outbox=True)
            rebuild_cache(store, resolved_database)

        if request.headers.get("HX-Request") != "true":
            return RedirectResponse(url="/feedback", status_code=303)
        context = feedback_ledger_context(request)
        sync_state = sync_context(request)
        response = templates.TemplateResponse(
            request=request,
            name="partials/feedback_ledger.html",
            context=context,
        )
        response.headers["HX-Trigger"] = json.dumps(
            {
                "radar:feedbackRevoked": {
                    "message": (
                        f"{canonical_fixture_repository_name(target.repo_full_name)} · "
                        "撤回已记录，将从次日起抵消原反馈"
                    ),
                    "pending": sync_state["pending_sync"],
                    "configured": sync_state["sync_configured"],
                    "label": sync_state["sync_label"],
                }
            },
            ensure_ascii=True,
        )
        return response

    @app.post("/sync-feedback", response_class=HTMLResponse)
    def sync_feedback(
        request: Request,
        csrf_token: str = Form(...),
    ):
        if not hmac.compare_digest(csrf_token, app.state.csrf_token) or not _same_origin(request):
            raise HTTPException(status_code=403, detail="invalid local form token")

        if not app.state.sync_configured:
            message = (
                "当前数据目录未连接私人 Git 仓，反馈只保存在本机。"
                "请使用私人数据仓作为 data-dir 重新启动仪表盘。"
            )
            tone = "warning"
        elif not app.state.sync_lock.acquire(blocking=False):
            message = "已有同步任务正在运行，请稍后再试。"
            tone = "warning"
        else:
            try:
                result = sync_private_data_safely(store)
                rebuild_cache(store, resolved_database)
                app.state.last_data_refresh_at = datetime.now(UTC)
                app.state.last_data_refresh_success = result.success
                app.state.last_data_refresh_error_category = result.error_category
            finally:
                app.state.sync_lock.release()
            if result.success:
                message = f"已同步 {result.synced_events} 条反馈到私人数据仓。"
                tone = "success"
            else:
                message = (
                    "同步未完成，反馈仍安全保存在本机。"
                    "请检查私人仓工作树、网络与 Git 凭据后重试。"
                )
                tone = "error"

        context = sync_context(request, message=message, tone=tone)
        if request.headers.get("HX-Request") != "true":
            return RedirectResponse(url="/", status_code=303)
        response = templates.TemplateResponse(
            request=request,
            name="partials/sync_panel.html",
            context=context,
        )
        response.headers["HX-Trigger"] = json.dumps(
            {
                "radar:syncUpdated": {
                    "message": message,
                    "pending": context["pending_sync"],
                    "configured": context["sync_configured"],
                    "label": context["sync_label"],
                }
            },
            ensure_ascii=True,
        )
        return response

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request, date_value: str | None = None):
        reports = cache.list_reports()
        selected = _select_report(cache, date_value)
        context = base_context(
            request,
            page="history",
            title="历史日报",
            subtitle="回看推荐结果、收藏反馈与自动任务状态。",
        )
        context.update(
            {
                "reports": reports,
                "selected_report": selected,
                "selected_mix": _report_mix(selected) if selected else "尚无日报",
                "history_overview": {
                    "days": len(reports),
                    "recommendations": sum(item.recommendation_count for item in reports),
                    "saved": sum(item.saved_count for item in reports),
                    "degraded": sum(item.status == "degraded" for item in reports),
                },
            }
        )
        return templates.TemplateResponse(request=request, name="history.html", context=context)

    @app.get("/partials/history", response_class=HTMLResponse)
    def history_partial(request: Request, date_value: str):
        report = _select_report(cache, date_value)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return templates.TemplateResponse(
            request=request,
            name="partials/history_detail.html",
            context={"request": request, "selected_report": report, "selected_mix": _report_mix(report)},
        )

    def select_saved(items: list[SavedItem], name: str | None) -> SavedItem | None:
        if name:
            selected = next((item for item in items if item.repo_full_name == name), None)
            if selected:
                return selected
        return items[0] if items else None

    @app.get("/saved", response_class=HTMLResponse)
    def saved(request: Request, repo: str | None = None):
        items = cache.list_saved()
        selected = select_saved(items, repo)
        context = base_context(
            request,
            page="saved",
            title="已收藏",
            subtitle="把一次推荐沉淀成可继续研究的项目清单。",
        )
        context.update(
            {
                "saved_items": items,
                "selected_saved": selected,
                "saved_overview": {
                    "total": len(items),
                    "with_context": sum(item.recommendation is not None for item in items),
                    "report_days": len(
                        {item.report_date for item in items if item.report_date is not None}
                    ),
                },
            }
        )
        return templates.TemplateResponse(request=request, name="saved.html", context=context)

    @app.get("/partials/saved", response_class=HTMLResponse)
    def saved_partial(request: Request, repo: str):
        selected = select_saved(cache.list_saved(), repo)
        if selected is None or selected.repo_full_name != repo:
            raise HTTPException(status_code=404, detail="saved repository not found")
        return templates.TemplateResponse(
            request=request,
            name="partials/saved_detail.html",
            context={"request": request, "selected_saved": selected},
        )

    return app
