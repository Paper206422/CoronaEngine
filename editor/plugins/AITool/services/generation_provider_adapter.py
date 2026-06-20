from __future__ import annotations

import inspect
from typing import Any, Callable

from .generation_scheduler import DEFAULT_STAGE_ORDER, GenerationJob


PROVIDER_STAGE_METHODS = {
    "prepare": "prepare",
    "submit": "submit",
    "poll": "poll",
    "download": "download",
    "postprocess": "postprocess",
    "import": "import_result",
}


class ProviderStageRunner:
    """Adapter from provider-style generation APIs to GenerationScheduler stages.

    This lets Hunyuan/Rodin/image providers migrate away from one large blocking
    call and background daemon threads. A provider can implement any subset of
    prepare/submit/poll/download/postprocess/import_result; missing stages are
    recorded as skipped so the scheduler remains observable.
    """

    def __init__(
        self,
        provider_factory: Callable[[], Any] | Any,
        *,
        stage_methods: dict[str, str] | None = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._stage_methods = {**PROVIDER_STAGE_METHODS, **(stage_methods or {})}

    def stage_handlers(self) -> dict[str, Callable[[GenerationJob], Any]]:
        return {stage: self._make_handler(stage) for stage in DEFAULT_STAGE_ORDER}

    def _make_handler(self, stage: str) -> Callable[[GenerationJob], Any]:
        def _handler(job: GenerationJob) -> Any:
            provider = self._provider_for(job)
            method_name = self._stage_methods.get(stage, stage)
            method = getattr(provider, method_name, None)
            if not callable(method):
                return {
                    f"{stage}_skipped": True,
                    "provider_completed_stages": [
                        *job.result.get("provider_completed_stages", []),
                        stage,
                    ],
                }
            context = self._context(job, stage)
            value = self._call_provider_method(method, job, context)
            if isinstance(value, dict):
                return {
                    **value,
                    "provider_completed_stages": [
                        *job.result.get("provider_completed_stages", []),
                        stage,
                    ],
                }
            return {
                stage: value,
                "provider_completed_stages": [
                    *job.result.get("provider_completed_stages", []),
                    stage,
                ],
            }

        return _handler

    def _provider_for(self, job: GenerationJob) -> Any:
        provider = job.runtime_context.get("generation_provider")
        if provider is not None:
            return provider
        if callable(self._provider_factory):
            provider = self._provider_factory()
        else:
            provider = self._provider_factory
        job.runtime_context["generation_provider"] = provider
        return provider

    @staticmethod
    def _context(job: GenerationJob, stage: str) -> dict[str, Any]:
        return {
            "stage": stage,
            "job_id": job.job_id,
            "session_id": job.session_id,
            "plan_id": job.plan_id,
            "batch_id": job.batch_id,
            "payload": dict(job.payload),
            "result": dict(job.result),
            "runtime_context": job.runtime_context,
        }

    @staticmethod
    def _call_provider_method(method: Callable[..., Any], job: GenerationJob, context: dict[str, Any]) -> Any:
        signature = inspect.signature(method)
        params = signature.parameters
        if "job" in params and "context" in params:
            return method(job=job, context=context)
        if "context" in params:
            return method(context=context)
        if "job" in params:
            return method(job=job)
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
            return method(job=job, context=context)
        return method()


class DeferredDownloadProvider:
    """Provider wrapper for legacy deferred download callables.

    Existing 3D tools often return a preview immediately and continue mesh
    downloads in daemon threads. This adapter makes the deferred operation a
    scheduler download stage instead, preserving the callable while giving the
    scheduler ownership of concurrency, cancellation boundaries, and status.
    """

    def __init__(
        self,
        download_fn: Callable[..., Any],
        *,
        postprocess_fn: Callable[..., Any] | None = None,
        import_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._download_fn = download_fn
        self._postprocess_fn = postprocess_fn
        self._import_fn = import_fn

    def download(self, context: dict[str, Any]) -> dict[str, Any]:
        payload = dict(context.get("payload") or {})
        result = dict(context.get("result") or {})
        kwargs = {
            **dict(payload.get("download_kwargs") or {}),
            **dict(result.get("download_kwargs") or {}),
        }
        value = self._call(self._download_fn, context, kwargs)
        if isinstance(value, dict):
            return {"download_result": value, "deferred_download_done": True}
        return {"download_result": value, "deferred_download_done": True}

    def postprocess(self, context: dict[str, Any]) -> dict[str, Any]:
        if self._postprocess_fn is None:
            return {"postprocess_skipped": True}
        value = self._call(self._postprocess_fn, context, {})
        return value if isinstance(value, dict) else {"postprocess_result": value}

    def import_result(self, context: dict[str, Any]) -> dict[str, Any]:
        if self._import_fn is None:
            return {"import_skipped": True}
        value = self._call(self._import_fn, context, {})
        return value if isinstance(value, dict) else {"import_result": value}

    @staticmethod
    def _call(fn: Callable[..., Any], context: dict[str, Any], kwargs: dict[str, Any]) -> Any:
        signature = inspect.signature(fn)
        params = signature.parameters
        if "context" in params and any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
            return fn(context=context, **kwargs)
        if "context" in params:
            return fn(context=context)
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
            return fn(**kwargs)
        if kwargs:
            accepted = {key: value for key, value in kwargs.items() if key in params}
            return fn(**accepted)
        return fn()


__all__ = [
    "DeferredDownloadProvider",
    "PROVIDER_STAGE_METHODS",
    "ProviderStageRunner",
]
