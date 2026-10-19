"""Broker-aware symbol discovery.

Brokers rarely agree on symbol names. A gold contract can be ``XAUUSD``,
``XAUUSD.a``, ``XAUUSDm``, ``XAUUSD_SB`` or ``#XAUUSD`` depending on the
server. This module resolves the configured symbol against what the connected
terminal actually offers.

Non-negotiable safety rules
---------------------------
1. Only *variants of the requested instrument* are ever considered. A name is
   a variant only when it is the base name plus a short broker modifier
   (``XAUUSDm``, ``XAUUSD.a``, ``#XAUUSD``). Different instruments that merely
   share a stem - ``XAUEUR``, ``XAUAUD``, ``XAUG`` - are never auto-selected.
2. When two equally plausible candidates exist and no reliable choice can be
   made, discovery returns ``ambiguous`` and reports the candidates. The
   dashboard then requires an explicit ``MT5_SYMBOL`` value.
3. The exact configured symbol always wins when it is available.

All MetaTrader5 calls are made through the injected ``mt5`` module handle so
this module is fully unit-testable without a terminal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from ..logging_config import get_logger

logger = get_logger(__name__)

# A modifier longer than this is treated as a different instrument.
_MAX_MODIFIER_LENGTH = 8

# Currency / metal codes that, if they form the modifier, mean the name is a
# *different* pair (e.g. XAUEUR) rather than a broker variant of XAUUSD.
_INSTRUMENT_CODES = frozenset(
    {
        "EUR", "USD", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "CNH", "CNY",
        "HKD", "SGD", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RUB", "TRY",
        "ZAR", "MXN", "BRL", "INR", "KRW", "THB", "ILS", "RON", "XAU", "XAG",
        "XPT", "XPD", "BTC", "ETH", "OIL", "WTI", "BRENT",
    }
)


class SymbolResolutionStatus(str, Enum):
    """Outcome of a symbol discovery attempt."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class SymbolVariantKind(str, Enum):
    """How a candidate name relates to the requested base symbol."""

    EXACT = "exact"
    SUFFIX = "suffix"
    PREFIX = "prefix"


@dataclass(frozen=True)
class SymbolProperties:
    """Broker-provided contract specification for a symbol."""

    name: str
    digits: int
    point: float
    tick_size: float | None
    tick_value: float | None
    broker_spread_points: int | None
    currency_base: str | None = None
    currency_profit: str | None = None
    trade_mode: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "digits": self.digits,
            "point": self.point,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "broker_spread_points": self.broker_spread_points,
            "currency_base": self.currency_base,
            "currency_profit": self.currency_profit,
            "trade_mode": self.trade_mode,
        }


@dataclass
class SymbolDiscoveryResult:
    """Result of resolving the trading symbol against the terminal."""

    status: SymbolResolutionStatus
    requested_symbol: str
    symbol: str | None = None
    matched_by: SymbolVariantKind | None = None
    modifier: str | None = None
    candidates: list[str] = field(default_factory=list)
    considered: list[str] = field(default_factory=list)
    message: str = ""
    properties: SymbolProperties | None = None

    @property
    def resolved(self) -> bool:
        return self.status is SymbolResolutionStatus.RESOLVED and bool(self.symbol)

    @property
    def requires_configuration(self) -> bool:
        return self.status is SymbolResolutionStatus.AMBIGUOUS

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "requested_symbol": self.requested_symbol,
            "symbol": self.symbol,
            "matched_by": self.matched_by.value if self.matched_by else None,
            "modifier": self.modifier,
            "candidates": list(self.candidates),
            "considered": list(self.considered),
            "message": self.message,
            "properties": self.properties.as_dict() if self.properties else None,
            "requires_configuration": self.requires_configuration,
        }


def _core(name: str) -> str:
    """Uppercase with every non-alphanumeric character removed."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def classify_symbol_variant(name: str, base: str) -> tuple[SymbolVariantKind, str] | None:
    """Classify ``name`` as a variant of ``base``.

    Returns ``(kind, modifier)`` when ``name`` is the base symbol with a short
    broker modifier, else ``None``.

    ``EXACT`` means the name *is* the base (case-insensitively). Anything else
    must carry a short broker modifier, so ``XAUUSD.`` and ``#XAUUSD`` are
    reported as variants rather than being quietly treated as the plain name.

    Examples (base ``XAUUSD``)::

        XAUUSD        -> (EXACT,  "")
        xauusd        -> (EXACT,  "")
        XAUUSD.       -> (SUFFIX, ".")
        XAUUSDm       -> (SUFFIX, "M")
        XAUUSD.a      -> (SUFFIX, ".A")
        #XAUUSD       -> (PREFIX, "#")
        XAUEUR        -> None    # different instrument
        XAUG          -> None    # different instrument
        XAUUSDXAUUSD  -> None    # nonsense, too long
    """
    if not name or not base:
        return None

    base_core = _core(base)
    if not base_core:
        return None

    upper_name = name.strip().upper()
    base_upper = base.strip().upper()

    if upper_name == base_upper:
        return SymbolVariantKind.EXACT, ""

    candidates: list[tuple[SymbolVariantKind, str]] = []
    if upper_name.startswith(base_upper):
        candidates.append((SymbolVariantKind.SUFFIX, upper_name[len(base_upper):]))
    if upper_name.endswith(base_upper):
        candidates.append((SymbolVariantKind.PREFIX, upper_name[: -len(base_upper)]))

    for kind, modifier in candidates:
        if not modifier or len(modifier) > _MAX_MODIFIER_LENGTH:
            continue

        modifier_core = _core(modifier)
        # The modifier must not turn the name into a different instrument.
        if len(modifier_core) >= 3 and modifier_core in _INSTRUMENT_CODES:
            continue
        if modifier_core.endswith(base_core):
            continue

        return kind, modifier

    return None


def _rank(kind: SymbolVariantKind) -> int:
    return {
        SymbolVariantKind.EXACT: 0,
        SymbolVariantKind.SUFFIX: 2,
        SymbolVariantKind.PREFIX: 3,
    }[kind]


def _candidate_sort_key(
    entry: tuple[str, SymbolVariantKind, str],
) -> tuple[int, int, str]:
    name, kind, modifier = entry
    return (_rank(kind), len(modifier), name)


def _candidate_tiebreak_key(
    entry: tuple[str, SymbolVariantKind, str],
) -> tuple[int, int]:
    """Everything that decides whether one candidate beats another.

    Deliberately excludes the symbol *name*: two variants that differ only by
    name are equally plausible and must be reported as ambiguous instead of
    one being picked alphabetically.
    """
    _, kind, modifier = entry
    return (_rank(kind), len(modifier))


def _available_symbol_names(mt5: Any, base: str) -> tuple[list[str], list[str]]:
    """Return ``(considered, available)`` symbol names from the terminal.

    ``available`` is always a superset-filtered list of names worth ranking;
    ``considered`` records everything we looked at for diagnostics.
    """
    considered: list[str] = []
    collected: list[str] = []

    masks = [f"*{base}*", f"*{_core(base)[:3]}*"] if len(_core(base)) >= 3 else [f"*{base}*"]
    seen_masks: set[str] = set()

    for mask in masks:
        if mask in seen_masks:
            continue
        seen_masks.add(mask)
        try:
            group = mt5.symbols_get(mask)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("symbols_get(%r) failed: %s", mask, exc)
            group = None

        if group:
            names = [symbol.name for symbol in group]
            considered.extend(names)
            collected.extend(names)
            if collected:
                break

    if not collected:
        try:
            group = mt5.symbols_get()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("symbols_get() failed: %s", exc)
            group = None
        if group:
            names = [symbol.name for symbol in group]
            considered.extend(names)
            collected.extend(names)

    # De-duplicate while preserving order.
    return considered, list(dict.fromkeys(collected))


def discover_symbol(
    mt5: Any,
    requested_symbol: str,
    candidates: Iterable[str] | None = None,
    *,
    strict: bool = True,
) -> SymbolDiscoveryResult:
    """Resolve the trading symbol for the connected terminal.

    Resolution order:

    1. The configured ``requested_symbol`` when the terminal offers it exactly.
    2. Broker variants of the requested symbol discovered from the terminal,
       preferring the shortest modifier (the variant closest to the plain
       name).
    3. Names listed in ``candidates`` (``MT5_SYMBOL_CANDIDATES``) are *probed*
       as extra possibilities, but only when the terminal really offers them.

    The candidate list is a search hint, not a priority order: it never breaks
    a tie between two equally plausible variants. Ties are reported as
    ``ambiguous`` and the operator pins the choice with ``MT5_SYMBOL``.

    Never auto-selects a *different* instrument and never guesses between two
    equally plausible candidates.
    """
    requested = (requested_symbol or "").strip()
    if not requested:
        return SymbolDiscoveryResult(
            status=SymbolResolutionStatus.NOT_FOUND,
            requested_symbol=requested,
            message="No symbol configured. Set MT5_SYMBOL in backend/.env.",
        )

    configured = [name.strip() for name in (candidates or []) if name and name.strip()]

    considered, available_names = _available_symbol_names(mt5, requested)
    available_upper = {name.upper(): name for name in available_names}

    # The group mask may miss the configured symbol on unusual broker symbol
    # trees, so verify it directly rather than assuming it is present.
    if requested.upper() not in available_upper:
        try:
            if mt5.symbol_info(requested) is not None:
                available_upper[requested.upper()] = requested
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("symbol_info(%r) probe failed: %s", requested, exc)

    ranking: list[tuple[str, SymbolVariantKind, str]] = []

    for actual_name in available_upper.values():
        classified = classify_symbol_variant(actual_name, requested)
        if classified is None:
            continue
        kind, modifier = classified
        ranking.append((actual_name, kind, modifier))

    # Explicit fallback candidates are only honoured when the terminal really
    # offers them - a name in the configuration file is not proof that the
    # broker has that symbol.
    known_upper = {entry[0].upper() for entry in ranking}
    for name in configured:
        if name.upper() in known_upper:
            continue
        classified = classify_symbol_variant(name, requested)
        if classified is None:
            continue
        try:
            exists = mt5.symbol_info(name) is not None
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("symbol_info(%r) probe failed: %s", name, exc)
            exists = False
        if not exists:
            continue
        kind, modifier = classified
        ranking.append((name, kind, modifier))
        known_upper.add(name.upper())

    if not ranking:
        message = (
            f"No symbol matching {requested!r} was found on the connected "
            f"terminal. Checked {len(considered)} terminal symbols. "
            "Set MT5_SYMBOL to the exact broker symbol name."
        )
        logger.error("Symbol discovery failed: %s", message)
        return SymbolDiscoveryResult(
            status=SymbolResolutionStatus.NOT_FOUND,
            requested_symbol=requested,
            considered=sorted(set(considered)),
            message=message,
        )

    ranking.sort(key=_candidate_sort_key)
    best_tiebreak = _candidate_tiebreak_key(ranking[0])
    best = [entry for entry in ranking if _candidate_tiebreak_key(entry) == best_tiebreak]

    if len(best) > 1:
        names = sorted(entry[0] for entry in best)
        message = (
            f"Ambiguous symbol discovery for {requested!r}: multiple equally "
            f"plausible candidates were found ({', '.join(names)}). Set "
            f"MT5_SYMBOL to the exact name you want to use."
        )
        logger.error("%s", message)
        return SymbolDiscoveryResult(
            status=SymbolResolutionStatus.AMBIGUOUS,
            requested_symbol=requested,
            candidates=names,
            considered=sorted(set(considered)),
            message=message,
        )

    name, kind, modifier = best[0]
    properties = read_symbol_properties(mt5, name)
    if properties is None:
        message = (
            f"Symbol {name!r} was found but the terminal returned no symbol "
            "information for it. The symbol may be disabled on this account."
        )
        logger.error("%s", message)
        return SymbolDiscoveryResult(
            status=SymbolResolutionStatus.UNAVAILABLE,
            requested_symbol=requested,
            symbol=name,
            matched_by=kind,
            modifier=modifier,
            candidates=[name],
            considered=sorted(set(considered)),
            message=message,
        )

    if kind is SymbolVariantKind.EXACT:
        message = f"Symbol {name!r} resolved exactly as configured."
    else:
        message = (
            f"Symbol {name!r} resolved as a broker variant of {requested!r} "
            f"({kind.value} modifier {modifier!r}). Set MT5_SYMBOL={name} to "
            "pin this choice explicitly."
        )

    logger.info("%s", message)
    return SymbolDiscoveryResult(
        status=SymbolResolutionStatus.RESOLVED,
        requested_symbol=requested,
        symbol=name,
        matched_by=kind,
        modifier=modifier,
        candidates=[name],
        considered=sorted(set(considered)),
        message=message,
        properties=properties,
    )


def read_symbol_properties(mt5: Any, name: str) -> SymbolProperties | None:
    """Return the contract specification for ``name`` or ``None``."""
    try:
        info = mt5.symbol_info(name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("symbol_info(%r) failed: %s", name, exc)
        return None

    if info is None:
        return None

    def _get(attribute: str) -> Any:
        return getattr(info, attribute, None)

    digits = _get("digits")
    point = _get("point")
    if digits is None or not point:
        return None

    tick_size = _get("trade_tick_size")
    # MT5 reports 0.0 for "unspecified"; treat that as unavailable.
    tick_size = float(tick_size) if tick_size else None

    tick_value = _get("trade_tick_value")
    tick_value = float(tick_value) if tick_value else None

    broker_spread = _get("spread")

    return SymbolProperties(
        name=name,
        digits=int(digits),
        point=float(point),
        tick_size=tick_size,
        tick_value=tick_value,
        broker_spread_points=int(broker_spread) if broker_spread is not None else None,
        currency_base=_get("currency_base"),
        currency_profit=_get("currency_profit"),
        trade_mode=_get("trade_mode"),
    )


def ensure_symbol_selected(mt5: Any, name: str) -> bool:
    """Make sure ``name`` is visible in Market Watch so ticks can be read.

    Returns ``True`` when the symbol is selectable and reports information.
    """
    try:
        info = mt5.symbol_info(name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("symbol_info(%r) failed while selecting: %s", name, exc)
        return False

    if info is None:
        logger.error("Symbol %r is unknown to the terminal.", name)
        return False

    if not getattr(info, "visible", False):
        try:
            selected = mt5.symbol_select(name, True)
        except Exception as exc:
            logger.error("symbol_select(%r, True) raised: %s", name, exc)
            return False
        if not selected:
            logger.error(
                "Could not add %r to Market Watch (last_error=%s).",
                name,
                getattr(mt5, "last_error", lambda: None)(),
            )
            return False
        logger.info("Added %r to Market Watch.", name)

    return True
