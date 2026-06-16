"""VLM 审查外回路（突击方案 §2.3vlm / ⟦COMMIT:5⟧ ⟦DECIDE:vlm-tonight⟧=今晚接）。

定位：**外回路**——语义层、贵、异步、跑在审查队列上，**产出修正建议、绝不阻塞放置**。
与 consistency_check（AABB 内回路，确定性、每次摆放都跑、放置前 gate）互补：
  - AABB 内回路抓几何硬伤（穿模/挡门/超 Zone/悬空）。
  - VLM 外回路抓 AABB 抓不到的语义问题：朝向（兽头朝外）、语义摆放（电视朝沙发）、
    整体"看起来对不对"。

⟦RISK:vlm-screenshot-deadlock⟧（独立于物理的第二个卡死源）：
  物理求解器死循环已修（关物理），但 VLM 要截图、截图走引擎渲染同步，是第二个独立
  卡死源。**前置验证已通过**：现有 model_reviewer._capture_single_model 已用
  ThreadPoolExecutor + future.result(timeout=5.0) + cancel_futures 把截图隔离到
  worker 线程，超时即 skip。本模块复用该机制，并额外经 EngineWriteGate.screenshot
  串行收口（防截图与 import/remove 写入交错）。

铁律（突击方案 §10.5）：VLM 是外回路，**产建议不阻塞放置**。它输出 advisory
corrections（rotation/scale/issues），调用方/FinalReview 决定是否采纳——VLM 自己
绝不直接改场景、绝不卡主链路。

设计：纯编排，capture_fn / review_fn / engine_gate 依赖注入，便于离线测。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class VlmAdvice:
    """VLM 对单个模型的审查建议（advisory，不强制）。"""
    actor_id: str
    overall: str = "PASS"                       # "PASS" | "WARN" | "FAIL" | "SKIPPED"
    rotation_correction: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale_correction: List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    issues: List[str] = field(default_factory=list)
    fix_suggestion: str = ""

    def has_correction(self) -> bool:
        """是否给出了非平凡的修正建议（旋转非零或缩放非 1）。"""
        rot_nontrivial = any(abs(r) > 1e-3 for r in self.rotation_correction)
        scale_nontrivial = any(abs(s - 1.0) > 1e-3 for s in self.scale_correction)
        return rot_nontrivial or scale_nontrivial


@dataclass
class VlmReviewReport:
    """一轮 VLM 外回路审查的汇总。"""
    advices: List[VlmAdvice] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)       # 截图/审查失败被跳过的
    timed_out: List[str] = field(default_factory=list)      # 截图超时（卡死源兜底命中）

    def actionable(self) -> List[VlmAdvice]:
        """返回有可执行修正建议的条目（供 FinalReview 选择性采纳）。"""
        return [a for a in self.advices if a.has_correction() or a.overall == "FAIL"]

    def to_user_text(self) -> str:
        act = self.actionable()
        if not act:
            return "VLM 审查未发现明显语义问题。"
        lines = ["VLM 审查发现可优化项（建议，非强制）："]
        for a in act[:5]:
            tip = a.fix_suggestion or "、".join(a.issues[:2]) or a.overall
            lines.append(f"- {a.actor_id}：{tip}")
        return "\n".join(lines)


def review_models_async(
    targets: List[Dict[str, Any]],
    *,
    capture_fn: Callable[[str, str], Optional[str]],
    review_fn: Callable[[str, str, str], Dict[str, Any]],
    engine_gate: Any = None,
    screenshot_timeout: float = 5.0,
) -> VlmReviewReport:
    """对一批模型跑 VLM 外回路审查，产出 advisory 报告（绝不改场景、绝不阻塞）。

    targets: [{actor_id, model_name?, model_type?}]
    capture_fn(output_dir, model_name) -> screenshot_dir | None（截图路径，已自带
        timeout+skip；本函数额外经 engine_gate.screenshot 串行收口）。
    review_fn(screenshot_dir, model_name, model_type) -> dict（VLM 审查结果）。
    engine_gate: EngineWriteGate（截图经 .screenshot 收口；None 则直接调 capture_fn）。

    任一目标的截图/审查失败 → 记 skipped/timed_out，**不中断整批、不抛**。
    """
    report = VlmReviewReport()
    if not targets:
        return report

    for tgt in targets:
        actor_id = (tgt.get("actor_id") or tgt.get("name") or "").strip()
        if not actor_id:
            continue
        model_name = tgt.get("model_name") or actor_id
        model_type = tgt.get("model_type") or model_name
        out_dir = tgt.get("output_dir") or f"_vlm_review/{actor_id}"

        # 1. 截图（经 EngineWriteGate 收口；capture_fn 自带 timeout+skip 兜底卡死源）
        try:
            if engine_gate is not None:
                shot_dir = engine_gate.screenshot(capture_fn, out_dir, model_name)
            else:
                shot_dir = capture_fn(out_dir, model_name)
        except TimeoutError:
            logger.warning("[VlmReviewLoop] %s 截图超时（卡死源兜底命中），跳过", actor_id)
            report.timed_out.append(actor_id)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("[VlmReviewLoop] %s 截图异常，跳过: %s", actor_id, exc)
            report.skipped.append(actor_id)
            continue

        if not shot_dir:
            logger.info("[VlmReviewLoop] %s 无截图（超时或失败），跳过审查", actor_id)
            report.skipped.append(actor_id)
            continue

        # 2. VLM 审查（产建议，不阻塞）
        try:
            raw = review_fn(shot_dir, model_name, model_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[VlmReviewLoop] %s VLM 审查异常，跳过: %s", actor_id, exc)
            report.skipped.append(actor_id)
            continue

        advice = VlmAdvice(
            actor_id=actor_id,
            overall=str(raw.get("overall", "PASS")),
            rotation_correction=list(raw.get("rotation_correction", [0.0, 0.0, 0.0])),
            scale_correction=list(raw.get("scale_correction", [1.0, 1.0, 1.0])),
            issues=list(raw.get("issues", []) or []),
            fix_suggestion=str(raw.get("fix_suggestion", "") or ""),
        )
        report.advices.append(advice)

    logger.info(
        "[VlmReviewLoop] 完成 — 审查 %d, 跳过 %d, 超时 %d, 可执行建议 %d",
        len(report.advices), len(report.skipped), len(report.timed_out),
        len(report.actionable()),
    )
    return report


__all__ = ["VlmAdvice", "VlmReviewReport", "review_models_async"]
