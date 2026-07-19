from ai_stock_screener.data import StockMetrics, load_csv
from ai_stock_screener.scoring import NEUTRAL, percentile_ranks, score_stocks


def make_stock(code="0000", **kwargs):
    return StockMetrics(code=code, name=f"銘柄{code}", sector="テスト", **kwargs)


class TestPercentileRanks:
    def test_higher_is_better(self):
        assert percentile_ranks([1.0, 2.0, 3.0]) == [0.0, 0.5, 1.0]

    def test_lower_is_better(self):
        assert percentile_ranks([1.0, 2.0, 3.0], higher_is_better=False) == [1.0, 0.5, 0.0]

    def test_none_gets_neutral(self):
        ranks = percentile_ranks([1.0, None, 3.0])
        assert ranks[1] == NEUTRAL
        assert ranks[0] == 0.0 and ranks[2] == 1.0

    def test_single_value_is_neutral(self):
        assert percentile_ranks([5.0, None]) == [NEUTRAL, NEUTRAL]

    def test_empty(self):
        assert percentile_ranks([]) == []


class TestScoreStocks:
    def test_cheap_profitable_rising_stock_ranks_first(self):
        good = make_stock("1111", per=8.0, pbr=0.8, dividend_yield=0.04,
                          roe=0.15, profit_margin=0.2, return_3m=0.1, return_6m=0.2)
        bad = make_stock("2222", per=40.0, pbr=5.0, dividend_yield=0.001,
                         roe=0.02, profit_margin=0.01, return_3m=-0.1, return_6m=-0.2)
        scored = score_stocks([bad, good])
        assert scored[0].metrics.code == "1111"
        assert scored[0].composite > scored[1].composite

    def test_scores_bounded(self):
        stocks = load_csv()
        for s in score_stocks(stocks):
            for v in (s.value, s.quality, s.momentum, s.composite):
                assert 0.0 <= v <= 1.0

    def test_missing_data_is_neutral(self):
        empty = make_stock("3333")
        good = make_stock("1111", per=8.0, roe=0.15, return_3m=0.1)
        bad = make_stock("2222", per=40.0, roe=0.02, return_3m=-0.1)
        scored = score_stocks([empty, good, bad])
        by_code = {s.metrics.code: s for s in scored}
        assert by_code["3333"].composite == NEUTRAL
        assert by_code["1111"].composite > NEUTRAL > by_code["2222"].composite

    def test_sample_csv_loads_all_stocks(self):
        stocks = load_csv()
        assert len(stocks) == 30
        assert all(s.code and s.name for s in stocks)
