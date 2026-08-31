# -*- coding: utf-8 -*-
"""功能点智能提取(走查整改 Step-3): 规则路径的多功能拆分与长文本兜底。"""
from services.feature_extract import extract_by_rules


def test_one_sentence_two_functions_split():
    """一句话连续提到两个功能 → 各自成候选(分类不混在一起)。"""
    candidates = extract_by_rules("系统支持账户登录，并提供数据导出功能。")
    names = [c["name"] for c in candidates]
    assert len(candidates) == 2
    assert any("账户登录" in n for n in names)
    assert any("数据导出" in n for n in names)


def test_long_text_without_punctuation_still_extracts():
    """整段无标点的超长文本不再被整体丢弃, 至少拆出主要功能簇。"""
    text = ("本系统为个人网银系统支持用户通过手机号验证码注册登录登录后可以查询账户余额"
            "和交易明细用户可以在转账汇款模块发起行内转账转账需要短信验证码确认"
            "管理后台提供操作日志审计和数据批量导出功能运维人员通过管理后台进行参数配置")
    candidates = extract_by_rules(text)
    assert len(candidates) >= 5
    # 主要功能类别都被覆盖到
    all_cats = {cat for c in candidates for cat in c["categories"]}
    assert {"auth_login", "payment", "export_data"} <= all_cats


def test_multi_sentence_and_conjunction():
    text = "客户可在线提交转账支付申请，并查询交易订单。管理后台提供数据导出。支持微信第三方登录。"
    candidates = extract_by_rules(text)
    assert len(candidates) >= 3
    payment = [c for c in candidates if c["involves_payment"]]
    assert payment and any("转账" in c["name"] for c in payment)


def test_sensitive_flagged_and_dedup():
    candidates = extract_by_rules("系统支持指纹与人脸生物识别登录，登录需要短信验证码。系统支持指纹与人脸生物识别登录。")
    bio = [c for c in candidates if "生物识别" in c["name"]]
    assert bio and bio[0]["sensitivity"] == "sensitive"
    # 重复句不产生重复候选
    names = [c["name"] for c in candidates]
    assert len(names) == len(set(names))


def test_no_keyword_no_candidate():
    assert extract_by_rules("本系统用于企业内部宣传展示。") == []
