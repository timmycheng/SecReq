# -*- coding: utf-8 -*-
"""服务端错误收敛: 完整堆栈留日志, 客户端只拿通用文案 + 追踪码。

背景: 兜底 except 分支若把异常原文直接回显, 会把 SQL 语句、文件路径、
知识库结构等内部信息暴露给调用方。本模块提供统一出口, 让日志与响应分离:
服务端保留可排查的完整栈, 客户端只看到"出了什么事 + 去哪查"。

适用: 兜底分支(预期外的异常)。业务校验错误(模板不存在、参数越界等)
仍按原样回显具体原因 —— 那些信息对用户有用且不含内部细节。
"""
import logging
import secrets

from fastapi import HTTPException

TRACE_ID_BYTES = 6  # 12 个十六进制字符, 够短便于口述与复制


def new_trace_id() -> str:
    """生成短追踪码, 供用户报障时与服务端日志比对。"""
    return secrets.token_hex(TRACE_ID_BYTES)


def server_error(
    logger: logging.Logger,
    exc: BaseException,
    user_message: str,
    status_code: int = 500,
    **context,
) -> HTTPException:
    """记录异常栈与上下文, 返回只含通用文案与追踪码的 HTTPException。

    调用方式: `raise server_error(logger, exc, "生成失败") from exc`
    """
    trace_id = new_trace_id()
    logger.error("[trace=%s] %s", trace_id, user_message, exc_info=exc)
    if context:
        logger.error("[trace=%s] 上下文: %s", trace_id, context)
    return HTTPException(
        status_code=status_code,
        detail=f"{user_message}(追踪码 {trace_id})",
    )
