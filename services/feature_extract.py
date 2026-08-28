# -*- coding: utf-8 -*-
"""功能点智能提取(走查整改 Step-3): 粘贴业务需求段落 → 候选功能点。

两级实现:
1. LLM(OpenAI 兼容接口, 配置见 services.settings_service): 理解整段语义, 输出结构化功能点;
2. 规则降级: 按分类关键词切句匹配(无外部依赖, 效果有限但零成本)。

两条路径输出同一形态的候选列表, 由用户在前端勾选确认后并入功能清单。
"""
import json
import re

import httpx

import shared.constants as C

_TIMEOUT_SECONDS = 45

_SYSTEM_PROMPT = """你是银行/金融行业的安全需求分析助手。用户会粘贴一段业务需求描述(可能来自业务需求书、会议纪要等),
请从中提取出全部"功能点"(系统要实现的业务功能), 输出 JSON。

要求:
- 每个功能点一个对象: {"name": 功能名(不超过20字), "module": 所属模块(可空字符串),
  "categories": 分类代码数组(从下面列表选, 可多个), "involves_payment": 是否涉及资金交易(bool),
  "exposed_to_internet": 是否面向互联网用户(bool), "sensitivity": "public|internal|sensitive|confidential"}
- 分类代码表:
%s
- 只输出 JSON 数组, 不要任何解释文字。

可用分类代码: %s""" % (
    "\n".join(f"- {code}: {label}" for code, label in C.FEATURE_CATEGORIES.items()),
    "、".join(C.FEATURE_CATEGORIES),
)


class FeatureExtractionError(Exception):
    """提取失败(两条路径都不可用时)。"""


def extract_candidates(text: str, llm_config: dict | None = None) -> tuple[list[dict], str, str]:
    """提取候选功能点。返回 (candidates, mode, note)。

    mode: "llm" | "rules"; llm 失败自动降级 rules 并在 note 说明。
    """
    text = (text or "").strip()
    if not text:
        raise FeatureExtractionError("粘贴的内容为空")
    if llm_config:
        try:
            return extract_by_llm(text, llm_config), "llm", ""
        except Exception as exc:  # 网络/解析失败一律降级, 不阻塞录入
            return extract_by_rules(text), "rules", f"大模型调用失败已降级为关键词提取: {exc}"
    return extract_by_rules(text), "rules", "未配置大模型, 使用关键词规则提取(无标点长文本建议在系统管理配置大模型, 拆分更准确)"


def extract_by_llm(text: str, config: dict) -> list[dict]:
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text[:8000]},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    resp = httpx.post(
        f"{config['base_url']}/chat/completions",
        json=payload, headers=headers, timeout=_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _normalize(_parse_json_array(content))


def _parse_json_array(content: str) -> list:
    """从模型回复中抠出 JSON 数组(容忍 ```json 围栏与前后闲话)。"""
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match is None:
        raise ValueError(f"模型回复中没有 JSON 数组: {content[:200]}")
    return json.loads(match.group(0))


def _normalize(items: list) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:100]
        if not name or name in seen:
            continue
        seen.add(name)
        raw_categories = item.get("categories") or []
        if isinstance(raw_categories, str):
            raw_categories = [raw_categories]
        categories = [c for c in raw_categories if c in C.FEATURE_CATEGORIES][:5] or ["search"]
        sensitivity = item.get("sensitivity")
        if sensitivity not in C.SENSITIVITY_LEVELS:
            sensitivity = "internal"
        out.append({
            "name": name,
            "module": str(item.get("module") or "").strip()[:50] or None,
            "categories": categories,
            "involves_payment": bool(item.get("involves_payment")),
            "exposed_to_internet": bool(item.get("exposed_to_internet")),
            "sensitivity": sensitivity,
            "source_quote": str(item.get("source_quote") or "").strip()[:200] or None,
        })
    return out[:50]


# ── 规则降级: 关键词切句 ──────────────────────────────
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "auth_login": ["登录", "注册", "认证", "单点登录", "扫码", "身份核验"],
    "password_mgmt": ["改密", "修改密码", "找回密码", "重置密码", "密码管理"],
    "file_upload": ["上传", "附件", "影像件"],
    "file_download": ["下载附件", "下载文件"],
    "payment": ["支付", "付款", "扣款", "转账", "充值", "缴费"],
    "refund": ["退款", "退费"],
    "order": ["订单", "下单", "购物车", "赎回", "申购"],
    "export_data": ["导出", "批量下载"],
    "message_push": ["推送", "消息通知", "站内信", "公告", "提醒"],
    "comment_ugc": ["评论", "留言", "发帖", "评价"],
    "api_open": ["开放接口", "OpenAPI", "openapi", "第三方接入", "对外接口"],
    "admin_console": ["管理后台", "运营后台", "管理端", "后台管理"],
    "third_auth": ["第三方登录", "微信登录", "支付宝登录", "OAuth", "oauth"],
    "ai_feature": ["智能", "AI", "大模型", "智能推荐", "智能客服", "OCR", "图像识别"],
    "audit_log": ["审计", "操作日志", "留痕"],
    "search": ["搜索", "检索", "筛选查询"],
    "sms_email": ["短信", "邮件", "验证码"],
}
_SENTENCE_SPLIT = re.compile(r"[。；;！!？?\n\r]+")
_CLAUSE_SPLIT = re.compile(r"[，,、]|以及|同时|并且|然后|接着")
_CLAUSE_LEN = (4, 60)
_INTERNET_HINTS = ["互联网", "公网", "线上", "APP", "app", "小程序", "H5", "微信", "移动端", "网上", "手机银行"]
_SENSITIVE_HINTS = ["身份证", "银行卡", "账户", "手机号", "敏感", "个人信息", "交易密码", "指纹", "人脸", "生物识别", "密码"]


def _hits(text: str) -> list[str]:
    """命中分类代码(去重, 按声明顺序)。"""
    return [
        code for code, words in _CATEGORY_KEYWORDS.items()
        if any(w in text for w in words)
    ]


def _make_candidate(text: str, categories: list[str]) -> dict:
    return {
        "name": text[:50],
        "module": None,
        "categories": categories[:5],
        "involves_payment": any(c in ("payment", "refund") for c in categories),
        "exposed_to_internet": any(w in text for w in _INTERNET_HINTS),
        "sensitivity": "sensitive" if any(w in text for w in _SENSITIVE_HINTS) else "internal",
        "source_quote": text,
    }


def _trim_edge(text: str) -> str:
    """去掉候选窗口边缘的连接词/泛词, 让功能名更像一个短语。"""
    leads = ["用户可以", "用户可", "可以", "并支持", "支持", "并提供", "提供", "同时", "以及", "并且", "然后", "并", "及"]
    changed = True
    while changed:
        changed = False
        for lead in leads:
            if text.startswith(lead) and len(text) - len(lead) >= 4:
                text = text[len(lead):]
                changed = True
    for tail in ["的功能", "等功能", "功能"]:
        if text.endswith(tail) and len(text) - len(tail) >= 4:
            text = text[: -len(tail)]
            break
    return text.strip(" 、,，.。:：()（）-—*")


def _keyword_windows(sentence: str, before: int = 10, after: int = 25) -> list[dict]:
    """超长无标点句: 在每个关键词命中点截取邻域。

    相邻关键词间距近时以两者中点为界(避免窗口互相重叠), 间距远时用固定前后缀,
    保证一串功能描述被切成若干条边界可读的候选。
    """
    hits: list[tuple[int, int, str]] = []
    seen_span: set[tuple[int, str]] = set()
    for code, words in _CATEGORY_KEYWORDS.items():
        for word in words:
            idx = sentence.find(word)
            if idx >= 0 and (idx, word) not in seen_span:
                seen_span.add((idx, word))
                hits.append((idx, idx + len(word), code))
    hits.sort()

    windows: list[dict] = []
    for i, (start, end, code) in enumerate(hits):
        if i == 0:
            seg_start = max(0, start - before)
        else:
            prev_end = hits[i - 1][1]
            seg_start = (prev_end + start) // 2 if start - prev_end < 20 else max(0, start - before)
        if i == len(hits) - 1:
            seg_end = min(len(sentence), end + after)
        else:
            nxt_start = hits[i + 1][0]
            seg_end = (end + nxt_start) // 2 if nxt_start - end < 20 else min(len(sentence), end + after)
        text = _trim_edge(sentence[seg_start:seg_end])
        if len(text) >= 4:
            windows.append({"text": text, "categories": [code]})
    return windows


def extract_by_rules(text: str) -> list[dict]:
    """关键词规则: 句 → 子句 → 关键词窗口 三级拆分。

    - 句子(。；;!?换行分隔)内按 逗号/顿号/连词 切子句, 每个命中关键词的子句独立成候选
      (一句话多个功能各自一条);
    - 关键词跨子句(如"批量导出")时整句出一条候选;
    - 整段无标点的超长文本: 按关键词命中点截取邻域窗口, 每个功能簇一条候选。
    """
    candidates: list[dict] = []
    seen: set[str] = set()

    def push(text: str, categories: list[str]) -> None:
        key = text[:40]
        if key in seen:
            return
        seen.add(key)
        candidates.append(_make_candidate(text, categories))

    for raw in _SENTENCE_SPLIT.split(text):
        sentence = raw.strip(" 、,，.。:：()（）-—*")
        if not sentence:
            continue
        sentence_hits = _hits(sentence)
        if not sentence_hits:
            continue

        # 子句级拆分: 一句话里的多个功能各自成候选
        clause_found = False
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = clause.strip(" 、,，.。:：()（）-—*")
            if not _CLAUSE_LEN[0] <= len(clause) <= _CLAUSE_LEN[1]:
                continue
            clause_cat = _hits(clause)
            if clause_cat:
                clause_found = True
                push(clause, clause_cat)

        # 关键词跨子句(如"批量导出") → 整句一条; 超长句走关键词窗口
        if not clause_found:
            if len(sentence) <= 100:
                push(sentence, sentence_hits)
            else:
                for window in _keyword_windows(sentence):
                    push(window["text"], window["categories"])

        if len(candidates) >= 50:
            break
    return candidates
