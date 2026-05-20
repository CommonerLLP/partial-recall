"""Tests for hardware detection module."""

from __future__ import annotations

from partial_recall.hardware import HardwareProfile, _tier, detect_hardware


def test_tier_minimal() -> None:
    assert _tier(4.0, False) == "minimal"


def test_tier_standard() -> None:
    assert _tier(8.0, False) == "standard"


def test_tier_powerful() -> None:
    assert _tier(16.0, False) == "powerful"


def test_tier_apple_silicon_16gb_is_powerful() -> None:
    # Apple Silicon unified memory is more efficient — 16 GB M-series = powerful
    assert _tier(16.0, True) == "powerful"


def test_tier_apple_silicon_8gb_is_standard() -> None:
    assert _tier(8.0, True) == "standard"


def test_tier_unknown_ram_defaults_to_standard() -> None:
    assert _tier(None, False) == "standard"


def test_detect_hardware_returns_profile() -> None:
    hw = detect_hardware()
    assert isinstance(hw, HardwareProfile)
    assert hw.tier in ("minimal", "standard", "powerful")


def test_hardware_profile_ram_label_unknown() -> None:
    hw = HardwareProfile(ram_gb=None, is_apple_silicon=False, tier="standard")
    assert hw.ram_label() == "unknown RAM"


def test_hardware_profile_ram_label_known() -> None:
    hw = HardwareProfile(ram_gb=8.0, is_apple_silicon=False, tier="standard")
    assert "8" in hw.ram_label()


def test_hardware_profile_chip_label_apple() -> None:
    hw = HardwareProfile(ram_gb=16.0, is_apple_silicon=True, tier="powerful")
    assert "Apple Silicon" in hw.chip_label()


def test_hardware_profile_chip_label_non_apple() -> None:
    hw = HardwareProfile(ram_gb=8.0, is_apple_silicon=False, tier="standard")
    assert hw.chip_label() == ""
