"""watchlist.yaml の読み込み（特にYAMLコメントからの理由復元）のテスト。"""

from screener import watchlist

SAMPLE = '''\
watchlist:
  # 日本電子(6951)は2026-07-20にholdings.yamlへ移動
  - code: "5186"
    name: "ニッタ"
    ticker: "5186.T"
    code_verified: true
    status: "観察"
    note: >
      サイズ基準で降格。

  - code: "6623"
    name: "愛知電機"
    ticker: "6623.N"  # 名証プレミア単独上場。6623.Tは実在せず404
    code_verified: true
    status: "新規候補・観察"
    verified_fundamentals:
      roe_pct: 10.23
      asof: "2026-08-10"
      recheck_at: "2026-11-16"
    note: >
      ⑥送配電更新枠。

leads_unverified:
  - { name: "戸田工業", code: "4100" }  # PBR0.86だが予想ROE5.5%<6%で品質フロア僅か割れ
  - { name: "日本坩堝", code: "5355" }
  # ---- 2026-08-04「成長継続軸」第1パスの未検証候補 ----
  - { name: "GMOペイメントゲートウェイ", code: "3769" }  # 25年連続増収増益。決済インフラ
  - { name: "ショーボンドホールディングス", code: "1414" }  # 12年連続。インフラ補修＝⑥と重複
'''


def _write(tmp_path, text=SAMPLE):
    path = tmp_path / "watchlist.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_entries_and_tickers_are_loaded(tmp_path):
    wl = watchlist.load(_write(tmp_path))
    assert wl.codes() == ["5186", "6623"]
    # 名証サフィックスが落ちないこと（.T に直してはいけない）。
    assert wl.by_code("6623")["ticker"] == "6623.N"


def test_lead_inline_comment_is_recovered(tmp_path):
    wl = watchlist.load(_write(tmp_path))
    lead = wl.lead_by_code("4100")
    assert lead.name == "戸田工業"
    assert "品質フロア" in lead.reason


def test_lead_without_comment_has_empty_reason(tmp_path):
    wl = watchlist.load(_write(tmp_path))
    assert wl.lead_by_code("5355").reason == ""


def test_section_comment_is_carried_to_following_leads(tmp_path):
    wl = watchlist.load(_write(tmp_path))
    gmo = wl.lead_by_code("3769")
    shobond = wl.lead_by_code("1414")
    assert "成長継続軸" in gmo.section
    # 節見出しは次のコメント塊が現れるまで持ち回す。
    assert gmo.section == shobond.section
    # 節見出しより前のリードには付かない。
    assert "成長継続軸" not in wl.lead_by_code("4100").section


def test_standalone_notes_outside_leads_are_kept(tmp_path):
    """watchlist セクション内の独立コメント（昇格の記録）も捨てない。"""
    wl = watchlist.load(_write(tmp_path))
    assert any("日本電子" in note for note in wl.standalone_notes)


def test_known_codes_covers_watchlist_and_leads(tmp_path):
    path = _write(tmp_path)
    codes = watchlist.known_codes(watchlist_path=path, holdings_path=tmp_path / "missing.yaml")
    assert {"5186", "6623", "4100", "3769"} <= codes
