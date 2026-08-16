"""Closed-end fund universe and NAV ticker mapping."""

FUNDS: list[str] = [
    "ADX", "GAB", "RVT", "PDI", "PDO", "PTY", "PCN", "RQI",
    "UTF", "BST", "ETV", "ETY", "EOI", "HTD", "GDV", "USA",
    "GUT", "DNP", "EVT", "THQ", "BME", "BUI", "RNP", "JCE",
    "NIE", "SRV", "AWP", "IGR", "FFC", "HQH", "HQL", "GAM",
    "SOR", "CLM",
]


def nav_symbol(fund: str) -> str:
    """NAV ticker for a fund, per the Nasdaq X<ticker>X convention.

    Yahoo carries the NAV series under this convention, so storing NAV as an
    ordinary symbol lets the point-in-time machinery apply unchanged.
    """
    return f"X{fund.upper()}X"


def is_nav_symbol(symbol: str) -> bool:
    """True when a symbol looks like a NAV ticker.

    NAV series must never be tradeable, so this keeps them out of the
    selectable universe.
    """
    return (
        len(symbol) >= 3
        and symbol.startswith("X")
        and symbol.endswith("X")
    )


def all_symbols() -> list[str]:
    """Every symbol to download: each fund and its NAV series.

    Sorted so the download order is deterministic.
    """
    symbols = list(FUNDS)
    symbols.extend(nav_symbol(fund) for fund in FUNDS)
    return sorted(symbols)
