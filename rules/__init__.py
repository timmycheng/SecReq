# -*- coding: utf-8 -*-
"""规则引擎包: 知识库加载 + 需求生成。"""
from rules.loader import KnowledgeBase, KnowledgeBaseError, Template, load_knowledge_base
from rules.engine import Match, RuleEngine, RuleEngineError

__all__ = [
    "KnowledgeBase",
    "KnowledgeBaseError",
    "Template",
    "load_knowledge_base",
    "RuleEngine",
    "RuleEngineError",
    "Match",
]
