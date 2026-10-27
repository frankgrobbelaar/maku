"""What a PC can do for Maku, from its cards and what testing it found."""

from dataclasses import replace

import pytest

from maku.core.estimate import Speeds
from maku.core.hardware import (
    BEST_MEMORY,
    GIB,
    Card,
    Checked,
    abilities,
    best_card,
    best_wants,
    cards_from,
    driver_name,
    driver_problem,
    hearing_places,
    hour_seconds,
    is_integrated,
    maker_of,
    processor_name,
    why_not_converting,
)

GTX = Card("NVIDIA GeForce GTX 1660 SUPER", "nvidia", 6 * GIB, False, "617.42")
UHD = Card("Intel(R) UHD Graphics 620", "intel", 128 * 1024**2, True, "31.0.101.2111")
SMALL = Card("NVIDIA GeForce GTX 1050", "nvidia", 2 * GIB, False, "551.86")
CHECKED = Checked("nvenc", None, directml=True, at="2026-10-15T15:00:00+02:00")
NO_DIRECTX = Checked("nvenc", None, directml=False, at="")
DRIVER = "Driver does not support the required nvenc API version"


def test_a_cards_maker_is_known_by_its_vendor_or_its_name():
    assert maker_of("Some Card", "10de") == "nvidia"
    assert maker_of("AMD Radeon RX 6700 XT") == "amd"
    assert maker_of("Intel(R) UHD Graphics 620") == "intel"
    assert maker_of("Microsoft Basic Display Adapter") == "other"


def test_the_processors_graphics_have_little_memory_of_their_own():
    assert is_integrated("intel", 128 * 1024**2)
    assert is_integrated("amd", 512 * 1024**2)
    assert not is_integrated("amd", 12 * GIB)
    assert not is_integrated("intel", 8 * GIB)  # an Arc card
    assert not is_integrated("nvidia", None)


def test_drivers_and_processors_are_named_as_people_know_them():
    assert driver_name("32.0.16.1742", "nvidia") == "617.42"
    assert driver_name("31.0.101.2111", "intel") == "31.0.101.2111"
    assert processor_name("Intel(R) Core(TM) i5-9600K CPU @ 3.70GHz") == "Intel Core i5-9600K"
    assert processor_name("AMD Ryzen 7 5800X 8-Core Processor") == "AMD Ryzen 7 5800X 8-Core"


def test_maku_works_on_the_dedicated_card_with_the_most_memory():
    assert best_card([UHD, SMALL, GTX]) == GTX
    assert best_card([UHD]) == UHD
    assert best_card([]) is None


def test_subtitles_go_where_the_card_has_the_memory_for_them():
    assert hearing_places([GTX], CHECKED) == {"best": "card", "fast": "card"}
    assert hearing_places([SMALL], CHECKED) == {"best": None, "fast": "card"}
    assert hearing_places([UHD], CHECKED) == {"best": None, "fast": "processor"}
    assert hearing_places([GTX], NO_DIRECTX) == {"best": None, "fast": "processor"}
    assert hearing_places([], None) == {"best": "card", "fast": "card"}  # not tested yet
    unsaid = Card("NVIDIA GeForce RTX 4060", "nvidia", None, False, None)
    assert hearing_places([unsaid], CHECKED) == {"best": "card", "fast": "card"}  # as it was
    assert hearing_places([], CHECKED) == {"best": "card", "fast": "card"}


def test_an_hours_time_follows_the_pictures_size():
    owners = Speeds()

    full_hd = hour_seconds(owners, 1920, 1080)
    uhd = hour_seconds(owners, 3840, 2160)

    assert full_hd / 60 == pytest.approx(8.0, abs=0.2)  # 180 frames a second
    assert uhd == pytest.approx(full_hd * 4)


def test_the_owners_pc_does_everything():
    found = abilities([GTX], CHECKED, Speeds())

    assert [(each.part, each.state) for each in found] == [
        ("convert", "ready"),
        ("subtitles", "ready"),
        ("player", "ready"),
    ]
    convert = found[0]
    assert convert.how == "HEVC 10-bit on NVIDIA's encoder (NVENC)"
    assert convert.seconds == (
        hour_seconds(Speeds(), 1920, 1080),
        hour_seconds(Speeds(), 3840, 2160),
    )
    assert len(found[1].seconds) == 2  # Best's and Fast's


def test_a_laptop_says_what_runs_on_the_processor():
    laptop = Checked("qsv", None, directml=True, at="")

    found = abilities([UHD], laptop, Speeds(megapixels=90.0))

    convert, subtitles = found[0], found[1]
    assert convert.how == "HEVC 10-bit on Intel Quick Sync"
    assert convert.seconds[0] == pytest.approx(hour_seconds(Speeds(megapixels=90.0), 1920, 1080))
    assert (subtitles.state, subtitles.how) == ("limited", "Fast on the processor")
    assert subtitles.note == "Best wants a graphics card with 4 GB of memory of its own."


def test_a_pc_with_no_encoder_says_why_and_what_stopped_its_own_cards():
    stopped = Checked(None, DRIVER, directml=True, at="")

    found = abilities([GTX], stopped, Speeds())

    convert = found[0]
    assert (convert.state, convert.how) == ("no", "Not on this PC")
    assert convert.note == f"NVIDIA's encoder (NVENC) didn't start: {DRIVER}"
    assert found[2].state == "ready"  # the player plays on any PC


def test_another_encoder_converts_while_the_cards_own_needs_its_driver():
    other = Checked("qsv", f"{DRIVER}.", directml=True, at="")

    convert = abilities([GTX, UHD], other, Speeds())[0]

    assert (convert.state, convert.how) == ("ready", "HEVC 10-bit on Intel Quick Sync")
    assert convert.note == f"NVIDIA's encoder (NVENC) didn't start: {DRIVER}."


def test_cards_are_what_windows_lists_on_the_pcs_bus():
    listed: list[dict[str, object]] = [
        {
            "Name": "NVIDIA GeForce GTX 1660 SUPER",
            "PNPDeviceID": r"PCI\VEN_10DE&DEV_21C4&SUBSYS_00000000",
            "DriverVersion": "32.0.16.1742",
            "AdapterRAM": 4293918720,  # Windows' listing stops at 4 GB
        },
        {
            "Name": "Intel(R) UHD Graphics 630",
            "PNPDeviceID": r"PCI\VEN_8086&DEV_3E92",
            "DriverVersion": "31.0.101.2111",
            "AdapterRAM": 1073741824,
        },
        {"Name": "Microsoft Remote Display Adapter", "PNPDeviceID": r"SWD\REMOTEDISPLAYENUM"},
        {"Name": "", "PNPDeviceID": r"PCI\VEN_1002"},
    ]

    cards = cards_from(listed, {"NVIDIA GeForce GTX 1660 SUPER": 6 * GIB})

    assert cards == (
        Card("NVIDIA GeForce GTX 1660 SUPER", "nvidia", 6 * GIB, False, "617.42"),
        Card("Intel(R) UHD Graphics 630", "intel", GIB, True, "31.0.101.2111"),
    )


def test_only_words_about_its_driver_send_the_owner_for_a_newer_one():
    assert driver_problem(f"{DRIVER}.")
    assert driver_problem("DLL amfrt64.dll failed to open.")
    assert not driver_problem("Error creating a MFX session: -9.")
    assert not driver_problem("No capable devices found.")
    assert not driver_problem(None)

    old = Checked(None, "No capable devices found.", directml=True, at="")
    convert = abilities([GTX], old, Speeds())[0]

    assert convert.note == "Its graphics card has no encoder for HEVC 10-bit."


def test_windows_listing_a_card_at_its_cap_has_four_gb_or_more():
    listed: list[dict[str, object]] = [
        {
            "Name": "NVIDIA GeForce RTX 3060",
            "PNPDeviceID": r"PCI\VEN_10DE&DEV_2504",
            "AdapterRAM": 4293918720,  # Windows' most, for any card of 4 GB or more
        }
    ]

    [card] = cards_from(listed, {})  # the registry didn't say

    assert card.memory is not None
    assert card.memory >= BEST_MEMORY
    assert hearing_places([card], CHECKED)["best"] == "card"


def test_best_names_what_this_pc_lacks_for_it():
    assert best_wants(NO_DIRECTX) == "Best wants a graphics card that runs DirectX 12."
    assert best_wants(CHECKED) == "Best wants a graphics card with 4 GB of memory of its own."
    subtitles = abilities([GTX], NO_DIRECTX, Speeds())[1]
    assert subtitles.note == "Best wants a graphics card that runs DirectX 12."


def test_the_queue_says_why_this_pc_cant_convert():
    stopped = Checked(None, f"{DRIVER}.", directml=True, at="")
    none = Checked(None, "No capable devices found.", directml=True, at="")

    assert why_not_converting([GTX], stopped).startswith("NVIDIA's encoder (NVENC) didn't start")
    assert why_not_converting([GTX], none) == (
        "This PC can't convert to your standard: its graphics card has no encoder for HEVC 10-bit."
    )


def test_the_player_is_what_its_check_found():
    windows_n = replace(CHECKED, player="h264_nvenc")
    nothing = replace(CHECKED, player=None)

    assert abilities([GTX], CHECKED, Speeds())[2].how == "Windows' own video encoder"
    assert abilities([GTX], windows_n, Speeds())[2].how == "NVIDIA's encoder (NVENC)"
    player = abilities([GTX], nothing, Speeds())[2]
    assert (player.state, player.how) == ("no", "Not on this PC")
    assert player.note is not None
    assert "Media Feature Pack" in player.note
