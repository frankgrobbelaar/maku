"""Tidying up: where every identified file should go, as a list of proposed changes.

Nothing moves here. A plan is shown for review first, then applied, logged and undoable
(see maku/changes.py). Duplicates go to a quarantine folder on the same drive, never straight
to deletion, and no file is ever overwritten.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import PurePath

from maku.core.copies import Copy, choose_copy
from maku.core.extensions import is_subtitle, is_video
from maku.core.library import QUARANTINE_FOLDER, skipped_folder
from maku.core.naming import MAX_PATH, PathTooLongError, episode_path, movie_path, unique_path

_TOO_LONG = "The new name would be too long for Windows"
DELETED = "Deleted"  # the reason of a change that set a video aside because the owner deleted it
KEPT_BOTH = "A file with this name is already there; both are kept"  # how a "(2)" is explained


@dataclass(frozen=True)
class EpisodeOf:
    show: str
    year: int | None
    season: int
    episode: int
    last_episode: int | None = None
    title: str | None = None
    title_id: int | None = None  # the library's title, when known: two shows of one name differ


@dataclass(frozen=True)
class MovieOf:
    title: str
    year: int | None
    part: int | None = None  # one part of a film that comes in several files (CD1, CD2)
    title_id: int | None = None


type Identity = EpisodeOf | MovieOf


@dataclass(frozen=True)
class PlacedFile:
    """A file and what it was identified as."""

    copy: Copy
    identity: Identity
    sidecars: tuple[PurePath, ...] = ()  # subtitles beside it, named after it (see sidecars_of)
    root: PurePath | None = None  # its library folder, which it's filed under (else plan_tidy's)


def sidecars_of(video: PurePath, names: Iterable[str]) -> tuple[PurePath, ...]:
    """The subtitle files among `names` (a folder's contents) named after `video`.

    `Episode 1.en.srt` belongs to `Episode 1.mkv`, and `Episode 10.en.srt` doesn't. When two
    videos' names both fit (`Show - 12` and `Show - 12.5`), the longer one gets it.
    """
    listed = list(names)
    own = video.stem.casefold()
    stems = {own} | {PurePath(name).stem.casefold() for name in listed if is_video(name)}
    found: list[PurePath] = []
    for name in listed:
        if not is_subtitle(name):
            continue
        fits = [stem for stem in stems if name.casefold().startswith(stem + ".")]
        if fits and max(fits, key=len) == own:
            found.append(video.parent / name)
    return tuple(sorted(found, key=lambda path: path.name.casefold()))


class ChangeKind(StrEnum):
    MOVE = "move"  # rename or move into the library's layout
    QUARANTINE = "quarantine"  # set aside, kept for a while, then deleted


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    source: PurePath
    target: PurePath
    label: str  # "Glass Orchard · S01E07", "Starfall: Ascent"
    reason: str
    # For subtitles, the video they go with: two copies of an episode can share a name, and so
    # their subtitles, which go with the one kept. Not saved: the journal knows by name.
    of: PurePath | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Plan:
    changes: tuple[Change, ...]
    skipped: tuple[tuple[PurePath, str], ...] = ()  # files left where they are, and why


def plan_tidy(
    files: Sequence[PlacedFile],
    library: PurePath,
    *,
    day: date,
    taken: Iterable[str] = (),
    keep: Iterable[PurePath] = (),
    keep_names: bool = False,
) -> Plan:
    """The changes that put `files` in Plex's layout under their library folder (`library`, unless
    a file names its own).

    `taken` holds the paths already in use on disk. Every file's current path counts as taken
    too, so a new name never lands on a file that is still there. `keep` holds copies the owner
    chose to keep over the others of the same episode or movie. With `keep_names`, files go into
    the same folders under the names they have.
    """
    chosen = {str(path).casefold() for path in keep}
    used = {path.casefold() for path in taken} | {str(f.copy.path).casefold() for f in files}
    groups: dict[tuple[object, ...], list[PlacedFile]] = {}
    for placed in files:  # copies of the same episode or movie, whatever their format
        groups.setdefault(copy_key(placed.identity), []).append(placed)

    quarantines: list[Change] = []
    moves: list[Change] = []
    skipped: list[tuple[PurePath, str]] = []
    claimed: set[str] = set()  # subtitles going with a video: each goes with one only
    for group in groups.values():
        kept, reason = group[0], ""
        if len(group) > 1:
            choice = choose_copy([placed.copy for placed in group])
            kept = next(placed for placed in group if placed.copy is choice.keep)
            why = _lowercase_first(choice.reason)
            if owners := [p for p in group if str(p.copy.path).casefold() in chosen]:
                kept, why = owners[0], "you chose it"
            reason = f"Kept {kept.copy.path.name} instead: {why}"
        own = _claim(kept.sidecars, claimed)  # first, though a dropped copy's name fits them too
        for dropped in group:
            if dropped is not kept:
                place = unique_path(quarantine_place(dropped.copy.path, day), used)
                used.add(str(place).casefold())
                label = f"{_label(dropped.identity)} · duplicate"
                quarantines.append(
                    Change(ChangeKind.QUARANTINE, dropped.copy.path, place, label, reason)
                )
                theirs = _claim(dropped.sidecars, claimed)
                quarantines.extend(
                    _with_it(
                        dropped.copy.path,
                        _label(dropped.identity),
                        theirs,
                        place,
                        used,
                        ChangeKind.QUARANTINE,
                        reason,
                    )
                )
        root = kept.root or library
        try:
            target = _target(kept, root)
            if keep_names:
                target = target.with_name(kept.copy.path.stem + target.suffix)
        except PathTooLongError:
            skipped.append((kept.copy.path, _TOO_LONG))
            continue
        if _hidden(target, root):
            skipped.append((kept.copy.path, "Scans never look in a folder named so"))
            continue
        move = _move(kept, target, used)
        place = move.target if move else kept.copy.path
        followers = _with_it(
            kept.copy.path,
            _label(kept.identity),
            own,
            place,
            used,
            ChangeKind.MOVE,
            "Follows its video",
        )
        going = [change for change in (move, *followers) if change is not None]
        if any(len(str(change.target)) > MAX_PATH for change in going):
            skipped.append((kept.copy.path, _TOO_LONG))
            continue
        moves.extend(going)
    moves.sort(key=lambda change: str(change.target).casefold())
    return Plan(tuple(quarantines + moves), tuple(skipped))


def _hidden(target: PurePath, root: PurePath) -> bool:
    """Whether a new place is inside a folder scans never look into (a dot at the start of a
    show's name, say), where a filed video would seem to have gone."""
    try:
        folders = target.relative_to(root).parts[:-1]
    except ValueError:
        return False
    return any(skipped_folder(folder) for folder in folders)


def _move(placed: PlacedFile, target: PurePath, used: set[str]) -> Change | None:
    source = placed.copy.path
    if str(source) == str(target):
        return None  # already exactly right
    if str(source).casefold() == str(target).casefold():
        place = target  # only the case changes: the name is its own
    else:
        place = unique_path(target, used)
        used.add(str(place).casefold())
    reason = "Named and filed"
    if place != target:
        reason += f". {KEPT_BOTH}"
    return Change(ChangeKind.MOVE, source, place, _label(placed.identity), reason)


def _claim(sidecars: Iterable[PurePath], claimed: set[str]) -> list[PurePath]:
    """The subtitles no other video has taken, taken now."""
    mine = [sidecar for sidecar in sidecars if str(sidecar).casefold() not in claimed]
    claimed.update(str(sidecar).casefold() for sidecar in mine)
    return mine


def plan_set_aside(
    files: Sequence[tuple[PurePath, str, Sequence[PurePath]]],
    *,
    day: date,
    taken: Iterable[str] = (),
    reason: str = DELETED,
) -> Plan:
    """The changes that delete videos the way Maku deletes: each video (its path, its label and
    the subtitles named after it) to the quarantine folder on its own drive, under a name nothing
    there has (`taken` holds what's there already), until the quarantine is cleared out. Each
    says why (`reason`): the owner deleted it, unless told otherwise."""
    used = {path.casefold() for path in taken}
    changes: list[Change] = []
    for video, label, sidecars in files:
        place = unique_path(quarantine_place(video, day), used)
        used.add(str(place).casefold())
        changes.append(Change(ChangeKind.QUARANTINE, video, place, label, reason))
        changes += _with_it(video, label, sidecars, place, used, ChangeKind.QUARANTINE, reason)
    return Plan(tuple(changes))


def _with_it(
    video: PurePath,
    label: str,
    sidecars: Iterable[PurePath],
    place: PurePath,
    used: set[str],
    kind: ChangeKind,
    reason: str,
) -> list[Change]:
    """Moves for a video's subtitles, renamed to match where the video itself goes."""
    changes: list[Change] = []
    for sidecar in sidecars:
        tail = sidecar.name[len(video.stem) :]  # ".en.srt"
        target = place.with_name(place.stem + tail)
        if str(sidecar) == str(target):
            continue  # already right
        if str(sidecar).casefold() == str(target).casefold():
            spot = target  # only the case changes: the name is its own
        else:
            spot = unique_path(target, used)
            used.add(str(spot).casefold())
        changes.append(Change(kind, sidecar, spot, f"{label} · subtitles", reason, of=video))
    return changes


def _target(placed: PlacedFile, library: PurePath) -> PurePath:
    extension = placed.copy.path.suffix.lower()
    match placed.identity:
        case EpisodeOf() as episode:
            return episode_path(
                library,
                episode.show,
                episode.year,
                season=episode.season,
                episode=episode.episode,
                last_episode=episode.last_episode,
                title=episode.title,
                extension=extension,
            )
        case MovieOf() as movie:
            return movie_path(
                library, movie.title, movie.year, extension=extension, part=movie.part
            )


def copy_key(identity: Identity) -> tuple[object, ...]:
    """What makes two files copies of each other: the same episode, or the same movie (or the
    same part of it). Files with one key are copies."""
    match identity:
        case EpisodeOf() as episode:
            return (
                "episode",
                episode.title_id or episode.show.casefold(),
                episode.year,
                episode.season,
                episode.episode,
                episode.last_episode,  # a file holding two episodes isn't a copy of one
            )
        case MovieOf() as movie:
            return ("movie", movie.title_id or movie.title.casefold(), movie.year, movie.part)


def quarantine_place(source: PurePath, day: date) -> PurePath:
    r"""D:\Maku quarantine\2026-10-10\name.mkv: on the file's own drive, so moving is instant."""
    return type(source)(source.anchor) / QUARANTINE_FOLDER / day.isoformat() / source.name


def in_quarantine(path: PurePath) -> bool:
    """Whether a path is a file set aside, in one day's folder of the quarantine on its drive
    (quarantine_place): only such a file is the clear-out's to delete, whatever a record says."""
    day, quarantine = path.parent, path.parent.parent
    if path.name in ("", ".", "..") or quarantine.parent != type(path)(path.anchor):
        return False
    try:
        date.fromisoformat(day.name)
    except ValueError:
        return False
    return quarantine.name.casefold() == QUARANTINE_FOLDER.casefold()


def _label(identity: Identity) -> str:
    match identity:
        case EpisodeOf() as episode:
            code = f"S{episode.season:02d}E{episode.episode:02d}"
            if episode.last_episode is not None:
                code += f"-E{episode.last_episode:02d}"
            return f"{episode.show} · {code}"
        case MovieOf() as movie:
            return f"{movie.title} · part {movie.part}" if movie.part else movie.title


def _lowercase_first(text: str) -> str:
    return text[:1].lower() + text[1:]
