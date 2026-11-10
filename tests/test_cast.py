"""微5：解析層 t2c/cast.py（D12 唯一入口）——id／姓名／別名／正規化、建議、三級判定。

解析層只有一份是決策 D12；這裡釘住它的行為，順便釘住「不自動套用不同拼法」（D11）。
執行：python -m pytest tests/test_cast.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ui import sample_project  # noqa: E402
from t2c import bible, cast  # noqa: E402


def test_normalize_folds_width_case_and_separators():
    assert cast.normalize("Ａｌｅ－Ｈｅｉｎｅｓｓｅｎ") == cast.normalize("ale heinessen")
    assert cast.normalize("A_hinessen.") == "ahinessen"
    assert cast.normalize(None) == "" and cast.normalize("  ") == ""


def test_resolve_by_id_name_alias(tmp_path):
    proj = sample_project(tmp_path)
    assert cast.resolve(proj, "hao") == ("hao", "id")
    assert cast.resolve(proj, "周子浩")[0] == "hao"
    assert cast.resolve(proj, "阿浩") == ("hao", "alias")
    assert cast.resolve(proj, "nobody") == (None, None)
    assert cast.resolve(proj, "   ") == (None, None)


def test_resolve_normalized_only_after_exact_matches(tmp_path):
    proj = sample_project(tmp_path)
    assert cast.resolve(proj, "ＨＡＯ") == ("hao", "normalized")      # 全形＋大小寫
    assert cast.resolve(proj, " 周子浩 ")[0] == "hao"                # 空白


def test_grade_three_levels(tmp_path):
    proj = sample_project(tmp_path)
    assert cast.grade(proj, {"id": "hao"}) == ("hao", "card", [])
    assert cast.grade(proj, {"id": "hynesen"})[1] == "missing"
    assert cast.grade(proj, {"id": "hynesen", "extra": True}) == (None, "extra", [])
    assert cast.grade(proj, {"id": "阿浩"})[0] == "hao"               # 別名也算解析成功


def test_suggest_offers_close_names_but_never_applies_them(tmp_path):
    proj = sample_project(tmp_path)
    assert cast.resolve(proj, "ＡＨＯ")[0] is None                    # D11：打錯不自動套用
    assert cast.suggest(proj, "ＡＨＯ") == ["hao"]                    # 只給建議
    bible.add_alias(proj, "hao", "heinessen")
    proj.characters["hao"]["aliases"] = ["阿浩", "heinessen"]
    assert cast.resolve(proj, "hynesen") == (None, None)             # 不同拼法救不到
    assert cast.suggest(proj, "hynesen") == ["hao"]                  # 但會建議到有 heinessen 別名的那張卡


def test_locations_use_the_same_resolver(tmp_path):
    proj = sample_project(tmp_path)
    cid, how = cast.resolve(proj, "rooftop", kind="location")
    assert cid == "rooftop" and how == "id"

