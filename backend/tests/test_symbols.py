"""Symbol discovery and ambiguity handling.

The connected terminal used during development offers six gold symbols
(``XAUUSD``, ``XAUEUR``, ``XAUAUD``, ``XAUCHF``, ``XAUGBP``, ``XAUG``). The
discovery logic must lock onto ``XAUUSD`` and must never silently drift to a
different instrument.
"""

from __future__ import annotations

import pytest

from app.mt5.symbols import (
    SymbolResolutionStatus,
    SymbolVariantKind,
    classify_symbol_variant,
    discover_symbol,
    ensure_symbol_selected,
    read_symbol_properties,
)
from tests.fakes import FakeMT5, FakeSymbolInfo

GOLD_FAMILY = ["XAUUSD", "XAUEUR", "XAUAUD", "XAUCHF", "XAUGBP", "XAUG"]


def fake_with(names: list[str], **kwargs) -> FakeMT5:
    return FakeMT5(symbols=[FakeSymbolInfo(name) for name in names], **kwargs)


class TestClassifyVariant:
    @pytest.mark.parametrize(
        "name,expected_kind",
        [
            ("XAUUSD", SymbolVariantKind.EXACT),
            ("xauusd", SymbolVariantKind.EXACT),
            ("  XAUUSD  ", SymbolVariantKind.EXACT),
            ("XAUUSD.", SymbolVariantKind.SUFFIX),
            ("XAUUSDm", SymbolVariantKind.SUFFIX),
            ("XAUUSD.a", SymbolVariantKind.SUFFIX),
            ("XAUUSD_SB", SymbolVariantKind.SUFFIX),
            ("XAUUSDc", SymbolVariantKind.SUFFIX),
            ("XAUUSD1", SymbolVariantKind.SUFFIX),
            ("#XAUUSD", SymbolVariantKind.PREFIX),
            ("XAUUSD.G", SymbolVariantKind.SUFFIX),
        ],
    )
    def test_recognises_broker_variants(self, name, expected_kind):
        result = classify_symbol_variant(name, "XAUUSD")
        assert result is not None
        assert result[0] is expected_kind

    @pytest.mark.parametrize(
        "name",
        [
            "XAUEUR",
            "XAUAUD",
            "XAUCHF",
            "XAUGBP",
            "XAUG",
            "XAGUSD",
            "EURUSD",
            "XAUUSDXAUUSD",
            "GOLD",
            "US30",
        ],
    )
    def test_never_treats_a_different_instrument_as_a_variant(self, name):
        assert classify_symbol_variant(name, "XAUUSD") is None

    def test_handles_empty_inputs(self):
        assert classify_symbol_variant("", "XAUUSD") is None
        assert classify_symbol_variant("XAUUSD", "") is None


class TestExactResolution:
    def test_exact_configured_symbol_wins(self):
        mt5 = fake_with(GOLD_FAMILY)
        result = discover_symbol(mt5, "XAUUSD", ["XAUUSD"])

        assert result.status is SymbolResolutionStatus.RESOLVED
        assert result.symbol == "XAUUSD"
        assert result.matched_by is SymbolVariantKind.EXACT
        assert result.properties is not None
        assert result.properties.digits == 2
        assert result.properties.point == 0.01

    def test_case_insensitive_configured_symbol(self):
        mt5 = fake_with(GOLD_FAMILY)
        result = discover_symbol(mt5, "xauusd", [])

        assert result.resolved is True
        assert result.symbol == "XAUUSD"


class TestBrokerVariants:
    def test_finds_suffix_variant_when_plain_name_is_absent(self):
        mt5 = fake_with(["XAUEUR", "XAUUSD.a", "XAUG"])
        result = discover_symbol(mt5, "XAUUSD", [])

        assert result.status is SymbolResolutionStatus.RESOLVED
        assert result.symbol == "XAUUSD.a"
        assert result.matched_by is SymbolVariantKind.SUFFIX
        assert "MT5_SYMBOL=XAUUSD.a" in result.message

    def test_finds_prefix_variant(self):
        mt5 = fake_with(["XAUEUR", "#XAUUSD"])
        result = discover_symbol(mt5, "XAUUSD", [])

        assert result.status is SymbolResolutionStatus.RESOLVED
        assert result.symbol == "#XAUUSD"
        assert result.matched_by is SymbolVariantKind.PREFIX

    def test_configured_candidate_is_used_when_present(self):
        mt5 = fake_with(["XAUUSDm", "XAUEUR"])
        result = discover_symbol(mt5, "XAUUSD", ["XAUUSD", "XAUUSDm"])

        assert result.status is SymbolResolutionStatus.RESOLVED
        assert result.symbol == "XAUUSDm"


class TestDifferentInstrumentSafety:
    def test_other_gold_pairs_are_never_selected(self):
        """XAUUSD is absent; only other gold instruments exist."""
        mt5 = fake_with(["XAUEUR", "XAUAUD", "XAUCHF", "XAUGBP", "XAUG"])
        result = discover_symbol(
            mt5,
            "XAUUSD",
            ["XAUUSD", "XAUUSD.", "XAUUSDm", "XAUUSD.a", "XAUUSD_SB", "#XAUUSD"],
        )

        assert result.status is SymbolResolutionStatus.NOT_FOUND
        assert result.symbol is None
        assert "MT5_SYMBOL" in result.message

    def test_fallback_candidate_that_the_terminal_lacks_is_not_invented(self):
        """A name in the config file is not proof the broker has it."""
        mt5 = fake_with(["XAUUSDm"])
        result = discover_symbol(mt5, "XAUUSD", ["XAUUSD", "XAUUSD_SB", "XAUUSDm"])

        assert result.status is SymbolResolutionStatus.RESOLVED
        assert result.symbol == "XAUUSDm"

    def test_silver_is_never_a_gold_variant(self):
        mt5 = fake_with(["XAGUSD", "EURUSD"])
        result = discover_symbol(mt5, "XAUUSD", [])
        assert result.status is SymbolResolutionStatus.NOT_FOUND


class TestAmbiguity:
    def test_two_equally_plausible_variants_report_ambiguity(self):
        mt5 = fake_with(["XAUUSDm", "XAUUSDc"])
        result = discover_symbol(mt5, "XAUUSD", [])

        assert result.status is SymbolResolutionStatus.AMBIGUOUS
        assert result.symbol is None
        assert result.requires_configuration is True
        assert sorted(result.candidates) == ["XAUUSDc", "XAUUSDm"]
        assert "Ambiguous" in result.message

    def test_same_length_variants_do_not_get_silently_picked(self):
        mt5 = fake_with(["XAUUSD.ab", "XAUUSD.cd"])
        result = discover_symbol(mt5, "XAUUSD", [])

        assert result.status is SymbolResolutionStatus.AMBIGUOUS
        assert len(result.candidates) == 2

    def test_exact_match_breaks_a_tie(self):
        mt5 = fake_with(["XAUUSD", "XAUUSDm", "XAUUSDc"])
        result = discover_symbol(mt5, "XAUUSD", ["XAUUSD"])

        assert result.status is SymbolResolutionStatus.RESOLVED
        assert result.symbol == "XAUUSD"

    def test_ambiguity_dict_marks_that_configuration_is_required(self):
        mt5 = fake_with(["XAUUSDm", "XAUUSDc"])
        payload = discover_symbol(mt5, "XAUUSD", []).as_dict()

        assert payload["status"] == "ambiguous"
        assert payload["requires_configuration"] is True
        assert payload["symbol"] is None


class TestFailureModes:
    def test_empty_requested_symbol(self):
        result = discover_symbol(fake_with(GOLD_FAMILY), "", [])
        assert result.status is SymbolResolutionStatus.NOT_FOUND
        assert "MT5_SYMBOL" in result.message

    def test_terminal_with_no_matching_symbols(self):
        result = discover_symbol(fake_with(["EURUSD", "GBPUSD"]), "XAUUSD", [])
        assert result.status is SymbolResolutionStatus.NOT_FOUND

    def test_symbol_found_but_no_symbol_information(self):
        class NoInfoMT5(FakeMT5):
            def symbol_info(self, name):  # noqa: D102
                self._record("symbol_info", name)
                return None

        mt5 = NoInfoMT5(symbols=[FakeSymbolInfo("XAUUSDm")])
        result = discover_symbol(mt5, "XAUUSD", [])

        assert result.status is SymbolResolutionStatus.UNAVAILABLE
        assert result.symbol == "XAUUSDm"

    def test_read_symbol_properties_returns_none_for_unknown(self):
        assert read_symbol_properties(fake_with(GOLD_FAMILY), "NOPE") is None

    def test_read_symbol_properties_treats_zero_tick_size_as_unavailable(self):
        mt5 = fake_with([])
        mt5.symbols.append(FakeSymbolInfo("XAUUSD", trade_tick_size=0.0, trade_tick_value=0.0))
        properties = read_symbol_properties(mt5, "XAUUSD")

        assert properties is not None
        assert properties.tick_size is None
        assert properties.tick_value is None


class TestMarketWatchSelection:
    def test_symbol_is_added_to_market_watch_when_not_visible(self):
        mt5 = fake_with([])
        mt5.symbols.append(FakeSymbolInfo("XAUUSD", visible=False))

        assert ensure_symbol_selected(mt5, "XAUUSD") is True
        assert "XAUUSD" in mt5.selected

    def test_already_visible_symbol_is_not_reselected(self):
        mt5 = fake_with(["XAUUSD"])
        assert ensure_symbol_selected(mt5, "XAUUSD") is True
        assert "symbol_select" not in mt5.call_names()

    def test_unknown_symbol_is_reported_not_selected(self):
        mt5 = fake_with(["XAUUSD"])
        assert ensure_symbol_selected(mt5, "NOPE") is False

    def test_selection_failure_is_surfaced(self):
        class RejectingMT5(FakeMT5):
            def symbol_select(self, name, enable=True):  # noqa: D102
                self._record("symbol_select", name, enable)
                return False

        mt5 = RejectingMT5(symbols=[FakeSymbolInfo("XAUUSD", visible=False)])
        assert ensure_symbol_selected(mt5, "XAUUSD") is False
