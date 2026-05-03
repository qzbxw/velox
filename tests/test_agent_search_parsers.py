from bot.agent.tools.brave_search_tool import parse_brave_results
from bot.agent.tools.duckduckgo_search_tool import parse_duckduckgo_results, unwrap_duckduckgo_url


def test_brave_html_sample_returns_title_url_snippet():
    html = """
    <div class="snippet">
      <a href="https://example.com/news">BTC ETF flows today</a>
      <div class="snippet-description">Flows rose sharply.</div>
    </div>
    """
    results = parse_brave_results(html, query="btc")
    assert results[0].title == "BTC ETF flows today"
    assert results[0].url == "https://example.com/news"
    assert results[0].snippet == "Flows rose sharply."


def test_duckduckgo_html_sample_returns_title_url_snippet_and_unwraps_redirect():
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Feth"
    html = f"""
    <div class="result">
      <a class="result__a" href="{wrapped}">ETH ETF update</a>
      <a class="result__snippet">Ethereum flows improve.</a>
    </div>
    """
    results = parse_duckduckgo_results(html, query="eth")
    assert unwrap_duckduckgo_url(wrapped) == "https://example.com/eth"
    assert results[0].title == "ETH ETF update"
    assert results[0].url == "https://example.com/eth"
    assert results[0].snippet == "Ethereum flows improve."
