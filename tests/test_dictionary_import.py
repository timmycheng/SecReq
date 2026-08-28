# -*- coding: utf-8 -*-
"""数据字典导入(走查整改 Step-4): 多表解析与自动分级。"""
from services.dictionary_import import build_asset_suggestions, parse_dictionary_text

DICT_TEXT = """表名\t字段名\t类型
customer_info\t客户姓名\tVARCHAR(64)
customer_info\tmobile_phone\tVARCHAR(16)
customer_info\tid_card_no\tVARCHAR(32)
customer_info\tlogin_password\tVARCHAR(128)
account\tbalance\tDECIMAL
account\tcreate_time\tDATETIME
trans_detail\ttrans_amount\tDECIMAL
trans_detail\tcounterparty_account\tVARCHAR(32)"""


def test_multi_table_split_and_levels():
    rows = parse_dictionary_text(DICT_TEXT)
    assert len(rows) == 8  # 表头行被跳过
    assets = build_asset_suggestions(rows)
    by_name = {a["name"]: a for a in assets}
    # 每张表一个资产
    assert set(by_name) == {"customer_info", "account", "trans_detail"}
    # customer_info 含证件号/密码 → C3 级
    assert by_name["customer_info"]["classification"] == "4级_C3鉴别信息"
    assert by_name["customer_info"]["is_sensitive_pii"] is True
    # account 只有余额 → 3级
    assert by_name["account"]["classification"] == "3级_C2主要信息"


def test_mask_suggestion_on_pii_fields():
    rows = parse_dictionary_text(DICT_TEXT)
    assets = build_asset_suggestions(rows)
    customer = assets[0]
    masked = {f["field_name"] for f in customer["tables"][0]["fields"] if f["need_mask"]}
    assert {"客户姓名", "mobile_phone", "id_card_no"} <= masked


def test_markdown_and_comma_formats():
    md = "| table | field | type |\n|---|---|---|\n| t1 | phone_no | VARCHAR |\n| t1 | remark | VARCHAR |"
    rows = parse_dictionary_text(md)
    assert len(rows) == 2 and rows[0]["table"] == "t1"

    comma = "t2,用户姓名,\nt2,CREATE_TIME,DATETIME"
    rows2 = parse_dictionary_text(comma)
    assert len(rows2) == 2 and rows2[0]["field"] == "用户姓名"


def test_garbage_text_raises_no_assets():
    assert parse_dictionary_text("随便写的一段话没有表格结构") == []
