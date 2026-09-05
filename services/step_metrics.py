# -*- coding: utf-8 -*-
"""步骤耗时记录与汇总报表(#229)。

record: 向导步骤保存成功时落一条耗时(失败不记, 避免噪声);
report: 各步骤 平均/中位/样本数, 支持按项目聚合查看, 供试点汇报导出。
"""
from statistics import median

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Project, StepDuration

# 步骤 code 与前端向导 STEPS 对齐(前端上报原文, 此处仅用于报表展示兜底)
STEP_LABELS = {
    "project_info": "基本信息与定级",
    "features": "功能清单",
    "data_assets": "数据字典",
    "permission_matrix": "权限矩阵",
    "api_endpoints": "API 接口清单",
    "confirm": "确认生成",
}


def record_step_duration(db: Session, project: Project, step: str,
                         duration_seconds: float, operator_name: str | None) -> None:
    """落一条步骤耗时; 记录失败不影响保存主流程。"""
    if duration_seconds <= 0 or duration_seconds > 24 * 3600:
        return  # 明显异常的时钟漂移不入库
    db.add(StepDuration(
        project_id=project.id, system_id=project.system_id,
        step=step[:40], duration_seconds=round(float(duration_seconds), 1),
        operator_name=operator_name,
    ))
    db.commit()  # 保存端点的主体已完成自己的事务, 埋点行独立提交


def step_metrics_report(db: Session, project_id: int | None = None) -> dict:
    """各步骤 平均/中位/P90/样本数; project_id 给定时按轮次过滤。"""
    query = db.query(
        StepDuration.step,
        func.count().label("samples"),
        func.avg(StepDuration.duration_seconds).label("avg"),
    ).group_by(StepDuration.step)
    if project_id is not None:
        query = query.filter(StepDuration.project_id == project_id)
    avg_by_step = {step: (samples, avg) for step, samples, avg in query.all()}

    durations_by_step: dict[str, list[float]] = {}
    detail_query = db.query(
        StepDuration.step, StepDuration.duration_seconds)
    if project_id is not None:
        detail_query = detail_query.filter(StepDuration.project_id == project_id)
    for step, duration in detail_query.all():
        durations_by_step.setdefault(step, []).append(duration)

    total_seconds = 0.0
    steps_out = []
    for step, values in durations_by_step.items():
        ordered = sorted(values)
        samples, avg = avg_by_step[step]
        p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
        total_seconds += avg
        steps_out.append({
            "step": step,
            "label": STEP_LABELS.get(step, step),
            "samples": samples,
            "avg_seconds": round(avg, 1),
            "median_seconds": round(median(ordered), 1),
            "p90_seconds": round(p90, 1),
        })
    rounds = (
        db.query(func.count(func.distinct(StepDuration.project_id))).scalar() or 0
    ) if project_id is None else 1
    return {
        "steps": steps_out,
        "total_avg_seconds": round(total_seconds, 1),
        "rounds_covered": rounds,
    }
