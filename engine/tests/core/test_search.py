from maku.core.search import closeness, found, plain, words


def test_a_search_compares_names_however_they_are_written():
    assert plain("Café") == "cafe"
    full_width = "".join(chr(ord(letter) + 0xFEE0) for letter in "MOON")
    assert plain(full_width) == "moon"
    assert words("Signal:Zero - S01E02_v2") == ["signal", "zero", "s01e02", "v2"]
    assert words("星降り 物語") == ["星降り", "物語"]
    assert words(" - ") == []


def test_finds_what_has_every_word_in_any_of_its_texts():
    wanted = words("starfall lantern")

    assert found(wanted, "Starfall Academy", None, "Lanterns Over the Lake")
    assert not found(wanted, "Starfall Academy", "The First Night")
    assert found(words("glass 01"), "[Group] Glass_Orchard_-_01.mkv")


def test_the_closest_name_comes_first():
    wanted = words("starfall")

    assert [
        closeness(wanted, name)
        for name in ("Starfall", "Starfall Academy", "Tales of Starfall", "Midstarfall")
    ] == [0, 1, 2, 3]
