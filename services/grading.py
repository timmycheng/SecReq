# -*- coding: utf-8 -*-
"""等保定级问卷: 题库加载 + 加权打分 → 建议定级与判定理由。

题库为数据文件 rules/grading_questions.yml, 判定依据文案与分值由安全中心维护。
打分口径: 各题选项分值求和; 另设跨题组合规则(如"敏感个人信息+资金交易"直接三级),
从高到低首个命中的阈值档位即建议定级。人工修正由 GradingSurvey.final_level 承载,
规则引擎取 effective_level() 始终以修正后值为准。
"""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "rules" / "grading_questions.yml"


class GradingError(Exception):
    """问卷答案与题库不一致时抛出。"""


@dataclass
class GradingQuestion:
    id: str
    title: str
    options: list[dict] = field(default_factory=list)  # [{id,label,score,basis,tags}]

    def option(self, option_id: str) -> dict | None:
        return next((o for o in self.options if o["id"] == option_id), None)


@dataclass
class GradingResult:
    """一次打分产物: 分值明细 + 建议定级 + 判定理由。"""

    suggested_level: str
    suggested_reason: str
    total_score: int
    max_score: int
    matched_tags: list[str]
    details: list[dict]  # [{question_id, option_id, label, score, basis}]


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime_ns: int) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data.get("questions"), list) or not data["questions"]:
        raise GradingError("题库 questions 不能为空")
    for q in data["questions"]:
        if not q.get("id") or not q.get("options"):
            raise GradingError(f"题目缺少 id 或 options: {q}")
    return data


def load_question_bank(path: str | Path | None = None) -> dict:
    """加载题库原始结构(mtime 参与缓存键, 安全中心改文件即时生效)。"""
    p = Path(path or DEFAULT_QUESTIONS_PATH)
    return _load_cached(str(p), p.stat().st_mtime_ns)


def load_questions(path: str | Path | None = None) -> list[GradingQuestion]:
    """题库 → 运行时形态列表。"""
    data = load_question_bank(path)
    return [
        GradingQuestion(id=q["id"], title=q.get("title", ""), options=q.get("options") or [])
        for q in data["questions"]
    ]


def grade_survey(
    answers: list[dict],
    path: str | Path | None = None,
) -> GradingResult:
    """按题库给答案打分并给出建议定级。

    answers 形态: [{"question_id": "Q1", "option_id": "C"}, ...], 必须覆盖全部题目。
    """
    bank = load_question_bank(path)
    questions = {
        q["id"]: q for q in bank["questions"]
    }

    by_qid: dict[str, str] = {}
    for ans in answers or []:
        qid, oid = ans.get("question_id"), ans.get("option_id")
        if qid not in questions:
            raise GradingError(f"未知题目: {qid}")
        if qid in by_qid:
            raise GradingError(f"题目 {qid} 出现重复答案")
        if not any(o["id"] == oid for o in questions[qid]["options"]):
            raise GradingError(f"题目 {qid} 不存在选项 {oid}")
        by_qid[qid] = oid

    missing = [q for q in questions if q not in by_qid]
    if missing:
        raise GradingError(f"问卷未答完, 缺少题目: {'、'.join(sorted(missing))}")

    details: list[dict] = []
    tags: set[str] = set()
    total = 0
    max_score = 0
    for q in bank["questions"]:  # 按题库声明顺序输出
        opt = next(o for o in q["options"] if o["id"] == by_qid[q["id"]])
        score = int(opt.get("score", 0))
        total += score
        max_score += max(int(o.get("score", 0)) for o in q["options"])
        tags.update(opt.get("tags") or [])
        details.append(
            {
                "question_id": q["id"],
                "option_id": opt["id"],
                "label": opt.get("label", ""),
                "basis": opt.get("basis", ""),
                "score": score,
            }
        )

    level = None
    combined_hit = False
    for rule in sorted(bank["levels"], key=lambda r: -int(r.get("min_score", 0))):
        combined = set(rule.get("combined_tags") or [])
        hit_combined = bool(combined) and combined <= tags
        if level is None and (total >= int(rule.get("min_score", 0)) or hit_combined):
            level = rule["level"]
            combined_hit = hit_combined

    # 阈值兜底: 总分低于最低档也归入最后一个档位(levels 已含 min_score=0 档, 正常必命中)
    if level is None:
        level = bank["levels"][-1]["level"]

    reason_points = [d["basis"] for d in details if d["basis"]]
    prefix = "各风险要点直接满足组合判定条件" if combined_hit else "累计得分"
    reason = (
        f"{prefix}{'、'.join(reason_points)}; "
        f"总分 {total}/{max_score}, 综合判定建议为等保{level}。"
    )
    return GradingResult(
        suggested_level=level,
        suggested_reason=reason,
        total_score=total,
        max_score=max_score,
        matched_tags=sorted(tags),
        details=details,
    )
