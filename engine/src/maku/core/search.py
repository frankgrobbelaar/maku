"""Searching the library by what the owner types: every word of it, however a name is written
("cafe etoile" finds "Café Étoile", "signal zero" finds "Signal:Zero"), the closest first."""

import re
import unicodedata
from collections.abc import Iterable

_NOT_WORD = re.compile(r"[\W_]+")


def plain(text: str) -> str:
    """Text as a search looks through it: lower case, without accents, and full-width letters as
    plain ones. Most names are plain ASCII already, and need only lower case."""
    if text.isascii():
        return text.lower()
    unmarked = unicodedata.normalize("NFKD", text)
    return "".join(char for char in unmarked if not unicodedata.combining(char)).casefold()


def words(query: str) -> list[str]:
    """The words of what was typed, as a search compares them; none for an empty search."""
    return _NOT_WORD.sub(" ", plain(query)).split()


def found(wanted: Iterable[str], *texts: str | None) -> bool:
    """Whether every word wanted (`words`) is in one of `texts`: a name, a file's, a code."""
    there = " ".join(plain(text) for text in texts if text)
    return all(word in there for word in wanted)


def closeness(wanted: list[str], name: str) -> int:
    """How close a name is to what was typed, the closest lowest: the name itself, then one that
    starts with it, then one with a word that does, then any other."""
    name = " ".join(words(name))
    typed = " ".join(wanted)
    if name == typed:
        return 0
    if name.startswith(typed):
        return 1
    if f" {typed}" in f" {name}":
        return 2
    return 3
