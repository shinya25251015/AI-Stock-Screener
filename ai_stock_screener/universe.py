"""Default screening universe: major Tokyo Stock Exchange (Prime) stocks.

Ticker codes are 4-digit TSE securities codes. Yahoo Finance symbols are
formed by appending ".T" (e.g. 7203 -> "7203.T").
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseEntry:
    code: str
    name: str
    sector: str

    @property
    def yahoo_symbol(self) -> str:
        return f"{self.code}.T"


DEFAULT_UNIVERSE: list[UniverseEntry] = [
    UniverseEntry("7203", "トヨタ自動車", "輸送用機器"),
    UniverseEntry("6758", "ソニーグループ", "電気機器"),
    UniverseEntry("9984", "ソフトバンクグループ", "情報・通信業"),
    UniverseEntry("6861", "キーエンス", "電気機器"),
    UniverseEntry("8306", "三菱UFJフィナンシャル・グループ", "銀行業"),
    UniverseEntry("9432", "日本電信電話", "情報・通信業"),
    UniverseEntry("4063", "信越化学工業", "化学"),
    UniverseEntry("6501", "日立製作所", "電気機器"),
    UniverseEntry("7974", "任天堂", "その他製品"),
    UniverseEntry("9983", "ファーストリテイリング", "小売業"),
    UniverseEntry("8035", "東京エレクトロン", "電気機器"),
    UniverseEntry("4502", "武田薬品工業", "医薬品"),
    UniverseEntry("6902", "デンソー", "輸送用機器"),
    UniverseEntry("8058", "三菱商事", "卸売業"),
    UniverseEntry("8001", "伊藤忠商事", "卸売業"),
    UniverseEntry("8031", "三井物産", "卸売業"),
    UniverseEntry("4519", "中外製薬", "医薬品"),
    UniverseEntry("6367", "ダイキン工業", "機械"),
    UniverseEntry("6981", "村田製作所", "電気機器"),
    UniverseEntry("7741", "HOYA", "精密機器"),
    UniverseEntry("4568", "第一三共", "医薬品"),
    UniverseEntry("9433", "KDDI", "情報・通信業"),
    UniverseEntry("2914", "日本たばこ産業", "食料品"),
    UniverseEntry("8766", "東京海上ホールディングス", "保険業"),
    UniverseEntry("6098", "リクルートホールディングス", "サービス業"),
    UniverseEntry("6594", "ニデック", "電気機器"),
    UniverseEntry("7267", "本田技研工業", "輸送用機器"),
    UniverseEntry("7751", "キヤノン", "電気機器"),
    UniverseEntry("5108", "ブリヂストン", "ゴム製品"),
    UniverseEntry("4901", "富士フイルムホールディングス", "化学"),
]
