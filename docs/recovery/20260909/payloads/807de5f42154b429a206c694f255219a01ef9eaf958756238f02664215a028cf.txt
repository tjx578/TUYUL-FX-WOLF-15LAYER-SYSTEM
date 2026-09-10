from news_engine import NewsEngine


def test_news_lock_returns_bool():
    engine = NewsEngine()
    result = engine.is_locked("EURUSD")
    assert isinstance(result, bool)
