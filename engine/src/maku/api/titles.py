"""The library's titles: every series and film with its kind, release date, files and gaps, one
title in full with its seasons, the episodes it's missing, and its videos, and the franchises they
make (a collection's films together, and the ones it lacks)."""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from maku import artwork, franchises, titles, watched
from maku.api.common import ApiModel, Database, Paths, Web
from maku.core.catalog import Episode, TitleKind, tmdb_of
from maku.core.franchise import Member
from maku.core.languages import heard_in, listed
from maku.core.report import GAP_ANALYSIS_FILE
from maku.languages import beside
from maku.preferences import library_standard
from maku.reports import own_folder
from maku.subtitles import is_made
from maku.titles import Order, State, Title

router = APIRouter()


class SeasonCount(ApiModel):
    season: int
    present: int
    aired: int
    total: int  # with the episodes still to air


class EpisodeRef(ApiModel):
    season: int
    number: int
    name: str | None
    aired: str | None


class TitleSummary(ApiModel):
    id: int
    kind: TitleKind
    name: str
    year: int | None
    released: str | None  # the first episode, or the film's release (lists sort by it)
    airing: bool
    has_poster: bool
    files: int  # videos in the library
    added: str | None  # when the first of them was found
    aired: int  # numbered episodes out so far; 0 for a film
    present: int  # of those, the ones the library holds
    missing: int
    specials_missing: int  # specials, listed apart: never counted as missing
    upcoming: int  # episodes still to air


class TitleFile(ApiModel):
    id: int
    path: str
    size: int  # bytes
    season: int | None
    episode: int | None
    episode_end: int | None
    problem: str | None  # why it couldn't be read
    height: int | None
    codec: str | None
    duration: float | None
    # The languages it can be heard and read in: its sound tracks', and its subtitles' in it and
    # beside it ("jpn", "en"; "" for one that doesn't say), each once.
    sound: list[str]
    subtitles: list[str]
    # What Whisper heard ("ja") in a sound track that doesn't say its language, when Maku made
    # English subtitles from it: that track's language in `sound`.
    heard: str | None
    made: bool  # English subtitles Maku made are beside it
    # In the queue for English subtitles ("queued"), or having them made ("running").
    subtitles_job: Literal["queued", "running"] | None
    watched: bool  # seen to its last tenth, or marked watched
    resume: float | None  # where Play picks it up, in seconds; None for from the top


class EpisodeState(ApiModel):
    """One episode and how it stands, for the episode map: status by shape."""

    season: int  # 0 for the specials
    number: int
    name: str | None
    aired: str | None
    state: State
    file_id: int | None


class FranchiseRef(ApiModel):
    id: int
    name: str


class KindCounts(ApiModel):
    series: int
    movie: int


class FranchiseSummary(ApiModel):
    """Titles that go together: the films of one TMDB collection. A title on its own is a
    franchise of one."""

    id: int  # its lead title's: the first series to air, or else the first title
    name: str
    released: str | None  # its first release
    kinds: KindCounts
    has_poster: bool  # its lead's
    airing: bool  # any of it
    files: int
    added: str | None  # when its newest title's first video was found
    aired: int
    present: int
    missing: int
    specials_missing: int
    upcoming: int
    titles: list[TitleSummary]  # in the order asked for


class MissingTitle(ApiModel):
    """A film of a franchise's collection that the library has no part of, as TMDB knows it."""

    entry_id: int
    kind: TitleKind
    name: str
    year: int | None
    released: str | None  # its first episode, or the film's release
    episodes: int | None  # None while TMDB doesn't say how many
    coming: bool  # not out yet
    airing: bool  # out, with more of it still to come
    cover: str | None  # its poster's path on TMDB's image server (shown through /artwork)
    overview: str | None  # its synopsis
    genres: list[str]
    studio: str | None  # the first company TMDB names for it
    tmdb_type: Literal["tv", "movie"]  # its page on TMDB
    tmdb_id: int


class TitleAbout(ApiModel):
    """What a title's About panel says (maku/core/about.py), and where to read more of it."""

    overview: str | None
    genres: list[str]
    studio: str | None
    status: Literal["finished", "airing", "coming", "cancelled", "paused"] | None
    started: str | None  # its first episode, or the film's release
    ended: str | None  # its latest episode so far; None for a film, or while unknown
    minutes: int | None  # an episode's usual length, or the film's
    tmdb_type: Literal["tv", "movie"] | None  # its page on TMDB
    tmdb_id: int | None


class FranchiseMissing(ApiModel):
    titles: list[MissingTitle]  # oldest release first
    looking: bool  # some of the franchise is still to be looked up on TMDB


class TitleDetail(TitleSummary):
    franchise: FranchiseRef | None  # when the title is one of several
    folder: str | None  # its own folder, when its videos have one
    seasons: list[SeasonCount]
    missing_episodes: list[EpisodeRef]
    missing_specials: list[EpisodeRef]
    upcoming_episodes: list[EpisodeRef]
    episodes: list[EpisodeState]  # every episode with its state, specials included
    videos: list[TitleFile]
    about: TitleAbout


Sort = Annotated[Order, Query(description="released (the default), name, added or missing")]


@router.get("/titles")
def list_titles(conn: Database, sort: Sort = "released") -> list[TitleSummary]:
    """Every series and film in the library, oldest release first unless asked otherwise."""
    return [_summary(found) for found in titles.titles(conn, _today(), sort)]


@router.get("/franchises")
def list_franchises(conn: Database, sort: Sort = "released") -> list[FranchiseSummary]:
    """Every franchise with its titles, oldest release first unless asked otherwise: Home's
    shelf. A title on its own is a franchise of one."""
    return [_franchise(found) for found in titles.franchises(conn, _today(), sort)]


@router.get("/franchises/{title_id}")
def one_franchise(title_id: int, conn: Database, sort: Sort = "released") -> FranchiseSummary:
    """The franchise a title belongs to, found by any of its titles."""
    found = titles.franchise_of(conn, title_id, _today(), sort)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no such franchise.")
    return _franchise(found)


@router.get("/franchises/{title_id}/missing")
def franchise_missing(title_id: int, conn: Database) -> FranchiseMissing:
    """The films of the franchise's collection that the library has no part of. Maku looks the
    franchise up in the background, a few entries at a time."""
    found = titles.franchise_of(conn, title_id, _today())
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no such franchise.")
    rest = franchises.rest(conn, found)
    return FranchiseMissing(
        titles=[_missing(entry, kind) for entry in rest.titles if (kind := entry.kind)],
        looking=rest.looking,
    )


@router.get("/titles/{title_id}")
def one_title(title_id: int, conn: Database) -> TitleDetail:
    found = titles.title(conn, title_id, _today())
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no such title.")
    group = titles.franchise_of(conn, title_id, _today())
    gaps = found.gaps
    videos = conn.execute(
        """SELECT f.id, f.path, f.size, f.season, f.episode, f.episode_end, f.problem, f.height,
                  f.codec, f.duration, f.sound, f.subtitles, m.name AS made, m.size AS made_size,
                  m.modified AS made_modified, m.sound AS heard_track, m.language AS heard,
                  (SELECT j.state FROM jobs AS j
                   WHERE j.file_id = f.id AND j.kind = 'subtitles'
                     AND j.state IN ('queued', 'running')
                   ORDER BY j.state = 'running' DESC LIMIT 1) AS subtitles_job
           FROM files AS f LEFT JOIN made_subtitles AS m ON m.file_id = f.id
           WHERE f.title_id = ? AND f.gone_at IS NULL
           ORDER BY f.season, f.episode, f.path""",
        (title_id,),
    ).fetchall()
    subtitled = beside(Path(row["path"]) for row in videos)
    seen = watched.of_title(conn, title_id)
    show = titles.show_of(conn, title_id)
    statuses = (
        titles.episode_statuses(conn, title_id, show, library_standard(conn), _today())
        if show
        else []
    )
    roots = [Path(row["path"]) for row in conn.execute("SELECT path FROM folders")]
    own = own_folder(conn, title_id, roots)
    return TitleDetail(
        **_summary(found).model_dump(by_alias=False),
        franchise=FranchiseRef(id=group.id, name=group.name)
        if group and len(group.titles) > 1
        else None,
        folder=str(own) if own else None,
        episodes=[
            EpisodeState(
                season=s.episode.season,
                number=s.episode.number,
                name=s.episode.title,
                aired=s.episode.aired.isoformat() if s.episode.aired else None,
                state=s.state,
                file_id=s.file_id,
            )
            for s in statuses
        ],
        seasons=[
            SeasonCount(season=s.season, present=s.present, aired=s.aired, total=s.total)
            for s in (gaps.seasons if gaps else ())
        ],
        missing_episodes=[_episode(e) for e in (gaps.missing if gaps else ())],
        missing_specials=[_episode(e) for e in (gaps.specials_missing if gaps else ())],
        upcoming_episodes=[_episode(e) for e in (gaps.upcoming if gaps else ())],
        videos=[_video(row, subtitled[Path(row["path"])], seen) for row in videos],
        about=_about(conn, found),
    )


@router.get("/titles/{title_id}/about")
def title_about(title_id: int, conn: Database) -> TitleAbout:
    """A title's About panel alone: a franchise's page shows its lead's."""
    found = titles.title(conn, title_id, _today())
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no such title.")
    return _about(conn, found)


def _about(conn: Database, found: Title) -> TitleAbout:
    said = titles.about(conn, found.id)
    media, _, number = (found.tmdb or "").partition("/")
    return TitleAbout(
        overview=said.overview if said else None,
        genres=list(said.genres) if said else [],
        studio=said.studio if said else None,
        status=said.status if said else None,
        started=said.started.isoformat() if said and said.started else None,
        ended=said.ended.isoformat() if said and said.ended else None,
        minutes=said.minutes if said else None,
        tmdb_type="tv" if media == "tv" else "movie" if media == "movie" else None,
        tmdb_id=int(number) if number.isdigit() else None,
    )


def _video(row: sqlite3.Row, beside_it: list[str], seen: dict[int, watched.Watch]) -> TitleFile:
    """A title's video, with the languages of the subtitle files beside it (`beside_it`), and how
    far it has been watched (from `seen`, by its id)."""
    sound: list[str] = json.loads(row["sound"] or "[]")
    filled = heard_in(sound, row["heard_track"], row["heard"])
    watch = seen.get(row["id"])
    return TitleFile.model_validate(
        {
            **dict(row),
            "watched": watch.watched if watch else False,
            "resume": watch.resume if watch else None,
            "sound": listed(filled),
            "subtitles": listed([*json.loads(row["subtitles"] or "[]"), *beside_it]),
            "made": is_made(Path(row["path"]), row["made"], row["made_size"], row["made_modified"]),
            "heard": row["heard"] if filled != sound else None,
        }
    )


class Report(ApiModel):
    path: str
    text: str


@router.get("/titles/{title_id}/report")
def title_report(title_id: int, conn: Database) -> Report:
    """The gap analysis Maku wrote next to the title, as it is on disk."""
    roots = [Path(row["path"]) for row in conn.execute("SELECT path FROM folders")]
    folder = own_folder(conn, title_id, roots)
    report = folder / GAP_ANALYSIS_FILE if folder else None
    try:
        text = report.read_text(encoding="utf-8") if report else None
    except OSError:
        text = None
    if report is None or text is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "There's no gap analysis for this title yet: it gets one once its videos have a "
            "folder of their own.",
        )
    return Report(path=str(report), text=text)


@router.get(
    "/titles/{title_id}/poster",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def title_poster(title_id: int, conn: Database, paths: Paths, web: Web) -> FileResponse:
    """The title's poster, fetched once from TMDB and then kept."""
    row = conn.execute(
        "SELECT COALESCE(poster_choice, poster) AS poster FROM titles WHERE id = ?", (title_id,)
    ).fetchone()
    kept = artwork.poster(paths, row["poster"], web) if row is not None else None
    if kept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This title has no poster yet.")
    # The owner can choose another at any time: the window asks again rather than keep one.
    return FileResponse(
        kept, media_type=artwork.media_type(kept), headers={"Cache-Control": "no-cache"}
    )


@router.get(
    "/artwork",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def artwork_at(address: str, paths: Paths, web: Web) -> FileResponse:
    """A picture from TMDB's image server, such as a guess's poster, fetched once and kept. Any
    other address is refused."""
    kept = artwork.poster(paths, address, web)
    if kept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no picture at that address.")
    return FileResponse(kept, media_type=artwork.media_type(kept))


def _summary(found: Title) -> TitleSummary:
    gaps = found.gaps
    return TitleSummary(
        id=found.id,
        kind=found.kind,
        name=found.name,
        year=found.year,
        released=found.released.isoformat() if found.released else None,
        airing=found.airing,
        has_poster=artwork.poster_address(found.poster) is not None,
        files=found.files,
        added=found.added,
        aired=gaps.aired if gaps else 0,
        present=gaps.present if gaps else 0,
        missing=len(gaps.missing) if gaps else 0,
        specials_missing=len(gaps.specials_missing) if gaps else 0,
        upcoming=len(gaps.upcoming) if gaps else 0,
    )


def _franchise(found: titles.Franchise) -> FranchiseSummary:
    members = [_summary(title) for title in found.titles]
    lead = next(member for member in members if member.id == found.id)
    kinds = {kind: sum(1 for m in members if m.kind is kind) for kind in TitleKind}
    return FranchiseSummary(
        id=found.id,
        name=found.name,
        released=found.released.isoformat() if found.released else None,
        kinds=KindCounts(**{kind.value: count for kind, count in kinds.items()}),
        has_poster=lead.has_poster,
        airing=any(m.airing for m in members),
        files=sum(m.files for m in members),
        added=max((m.added for m in members if m.added), default=None),
        aired=sum(m.aired for m in members),
        present=sum(m.present for m in members),
        missing=sum(m.missing for m in members),
        specials_missing=sum(m.specials_missing for m in members),
        upcoming=sum(m.upcoming for m in members),
        titles=members,
    )


def _missing(entry: Member, kind: TitleKind) -> MissingTitle:
    media, number = tmdb_of(entry.id)
    return MissingTitle(
        entry_id=entry.id,
        kind=kind,
        name=entry.name,
        year=entry.start.year if entry.start else None,
        released=entry.start.isoformat() if entry.start else None,
        episodes=entry.episodes,
        coming=entry.coming,
        airing=entry.airing,
        cover=entry.cover if artwork.poster_address(entry.cover) else None,
        overview=entry.description,
        genres=list(entry.genres),
        studio=entry.studio,
        tmdb_type=media,
        tmdb_id=number,
    )


def _episode(episode: Episode) -> EpisodeRef:
    return EpisodeRef(
        season=episode.season,
        number=episode.number,
        name=episode.title,
        aired=episode.aired.isoformat() if episode.aired else None,
    )


def _today() -> date:
    return datetime.now().astimezone().date()
