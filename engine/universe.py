"""Stock universe for the stock-price backtest matrix.

Separate from the options universe (run_backtest.DEFAULT_SYMBOLS /
daily_signals.DEFAULT_SYMBOLS) so expanding the stock lab never changes the
options backtest or the daily options signal job.
"""

STOCK_SYMBOLS = [
    # mega tech
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "AMZN", "META", "GOOGL", "AVGO", "NFLX",
    # tech / semis
    "ORCL", "CRM", "ADBE", "INTC", "MU", "CSCO", "QCOM", "TXN", "ARM", "DELL",
    "TSM", "ASML", "AMAT", "LRCX", "MRVL", "ANET",
    # software / security / AI infra
    "CRWD", "PANW", "SNOW", "NET", "VRT", "APP", "TTD",
    # high-beta / retail favorites
    "PLTR", "SMCI", "COIN", "MSTR", "HOOD", "SOFI", "SNAP", "UBER", "SHOP", "PYPL",
    "GME", "IONQ", "RKLB",
    # healthcare
    "LLY", "NVO", "UNH", "ISRG", "PFE",
    # financial
    "JPM", "BAC", "V", "MA", "GS", "AXP",
    # consumer / industrial
    "F", "GM", "BA", "DIS", "NKE", "SBUX", "MCD", "WMT",
    "ABNB", "BKNG", "LULU", "RBLX", "DKNG",
    # energy
    "XOM", "CVX", "OXY", "SLB", "ENPH",
    # China ADR
    "BABA", "NIO", "RIVN", "LCID", "PDD", "JD", "XPEV",
    # index / macro ETFs
    "SPY", "QQQ", "IWM", "GLD", "TLT",
]
