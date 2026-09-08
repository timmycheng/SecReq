# -*- coding: utf-8 -*-
"""评审中心(#307): 跨项目评审进度总览, 一级菜单页数据源。

数据权限与项目同口径(可见角色全量 / pm 仅本人项目), 只返回已提交过的
评审(评估提交后产生); 条目点击进入对应评审页由前端路由完成。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models import PlatformUser
from routers.common import get_db, require_login
from services.review_service import review_overview

router = APIRouter(prefix="/api/reviews", tags=["review"])


@router.get("")
def list_reviews(user: PlatformUser = Depends(require_login),
                 db: Session = Depends(get_db)):
    """评审进度列表: 门禁状态/进度文案/提交人/评审人/需求汇总/最近动态。"""
    return review_overview(db, user)
