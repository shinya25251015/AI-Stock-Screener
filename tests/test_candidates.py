"""候補リストの読み込みと、社名突合によるコード検証のテスト。"""

from screener import candidates

SAMPLE = '''\
title: "テスト候補"
asof: "2026-08-12"
source_note: "テスト"
groups:
  - label: "⑥-c 鉄道保守"
    theme: "鉄道インフラの老朽化更新と保守。"
    candidates:
      - { name: "大同信号", code: "6743", note: "鉄道信号。小型" }
      - { name: "名工建設", code: "1869", ticker: "1869.N", note: "名証単独上場" }
  - label: "規制強化"
    theme: "法令で義務づけられた調査・点検・処理。"
    candidates:
      - { name: "ベステラ", code: "1433" }
'''


def _write(tmp_path):
    path = tmp_path / "cand.yaml"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


def test_load_flattens_groups_and_keeps_labels(tmp_path):
    clist = candidates.load(_write(tmp_path))
    assert len(clist.candidates) == 3
    assert clist.groups() == ["⑥-c 鉄道保守", "規制強化"]
    assert clist.candidates[0].group == "⑥-c 鉄道保守"


def test_theme_is_inherited_from_group(tmp_path):
    clist = candidates.load(_write(tmp_path))
    assert "鉄道インフラ" in clist.candidates[0].theme


def test_ticker_defaults_to_tokyo_but_explicit_wins(tmp_path):
    """名証・札証・福証は ticker を明示する。`.T` を当てると404になる。"""
    clist = candidates.load(_write(tmp_path))
    assert clist.candidates[0].resolved_ticker() == "6743.T"
    assert clist.candidates[1].resolved_ticker() == "1869.N"


def test_names_match_absorbs_common_notation_differences():
    # Yahoo!側は「(株)」が前にも後ろにも付き、全角英数も混ざる。
    assert candidates.names_match("大同信号", "大同信号(株)")
    assert candidates.names_match("日本管財ホールディングス", "日本管財ホールディングス(株)")
    assert candidates.names_match("ID&Eホールディングス", "ＩＤ＆Ｅホールディングス(株)")
    assert candidates.names_match("ベステラ", "ベステラ(株)")


def test_names_match_rejects_a_different_company():
    """コードの取り違えを弾けること（§8）。"""
    assert not candidates.names_match("東鉄工業", "日本電設工業(株)")
    assert not candidates.names_match("日本信号", "京三製作所(株)")


def test_names_match_flags_a_renamed_company():
    """2026-08-12の実例: 九電工は2025-10-01に「クラフティア」へ商号変更していた。

    不一致は「コードが違う」だけでなく「**こちらの社名が古い**」でも起きる。
    どちらかを確かめずに片方へ倒さないための、記録としてのテスト。
    """
    assert not candidates.names_match("九電工", "(株)クラフティア")


def test_names_match_handles_empty():
    assert not candidates.names_match("", "大同信号(株)")
    assert not candidates.names_match("大同信号", "")
