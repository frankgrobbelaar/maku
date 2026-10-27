"""One video in full, for its details: what it holds, where it is, the episode it is, and what
converting it to the standard does; and an episode's own details, the library's or not. Each with
a picture for the top of its details."""

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from maku import artwork, pictures
from maku.api.common import ApiModel, Database, Paths, Toolbox, Web
from maku.core.languages import beside_language
from maku.core.media import MediaInfo, media_from_ffprobe
from maku.core.plan import sidecars_of
from maku.core.standard import Method, decide
from maku.preferences import library_standard
from maku.subtitles import is_made

router = APIRouter()

# Whether a picture is from the episode or its show's (the app reads it, so CORS lets it through).
PICTURE_HEADER = "Maku-Picture"


class PictureFacts(ApiModel):
    codec: str
    width: int
    height: int
    bit_depth: int
    frame_rate: float | None  # frames a second


class SoundFacts(ApiModel):
    language: str | None  # "jpn"; None when the track doesn't say
    codec: str
    channels: int
    lossless: bool
    # The language is the one Whisper heard ("ja"), in a track that doesn't say its own, as Maku
    # made English subtitles from it.
    heard: bool


class SubtitleFacts(ApiModel):
    language: str | None
    codec: str | None  # None for a file beside the video, whose kind its name says
    text: bool  # words (ASS, SRT) rather than pictures (PGS, DVD)
    forced: bool  # signs and songs only
    beside: bool  # a file beside the video rather than a track in it
    made: bool  # English subtitles Maku made


class Converting(ApiModel):
    """What converting the video to the library's standard does."""

    state: Literal["ready", "to convert", "broken"]
    method: Literal["rename", "remux", "reencode", "skip"] | None
    reasons: list[str]  # in words: "4K HDR: brought down to 1080p, HDR kept"


class FileDetails(ApiModel):
    id: int
    path: str
    size: int  # bytes
    found_at: str  # when Maku first found it
    duration: float | None  # seconds
    problem: str | None  # why it can't be read
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    episode_end: int | None
    episode_name: str | None  # the (first) episode it holds, as TMDB names it
    aired: str | None
    overview: str | None  # what happens in it: a spoiler, so the app shows it on asking
    picture: PictureFacts | None
    sound: list[SoundFacts]
    subtitles: list[SubtitleFacts]
    chapters: int
    converted: bool  # Maku made it: its tag is inside
    converting: Converting


class EpisodeDetails(ApiModel):
    """One episode as TMDB lists it, whether the library has it or not."""

    season: int
    number: int
    name: str | None
    aired: str | None
    overview: str | None
    minutes: int | None
    file_id: int | None  # its video, when the library has it


@router.get("/files/{file_id}")
def file_details(file_id: int, conn: Database) -> FileDetails:
    """A video in the library, in full."""
    row = conn.execute(
        """SELECT f.*, t.name AS title, m.name AS made, m.size AS made_size,
                  m.modified AS made_modified, m.sound AS heard_track, m.language AS heard
           FROM files AS f LEFT JOIN titles AS t ON t.id = f.title_id
           LEFT JOIN made_subtitles AS m ON m.file_id = f.id
           WHERE f.id = ? AND f.gone_at IS NULL""",
        (file_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That video isn't in the library any more.")
    episode = (
        conn.execute(
            """SELECT name, aired, overview FROM episodes
               WHERE title_id = ? AND season = ? AND number = ?""",
            (row["title_id"], row["season"], row["episode"]),
        ).fetchone()
        if row["title_id"] is not None and row["episode"] is not None
        else None
    )
    video = Path(row["path"])
    made = (
        video.stem + row["made"]
        if row["made"] and is_made(video, row["made"], row["made_size"], row["made_modified"])
        else None
    )
    media = media_from_ffprobe(json.loads(row["probe"])) if row["probe"] else None
    subtitles = [
        SubtitleFacts(
            language=each.language,
            codec=each.codec,
            text=each.text,
            forced=each.forced,
            beside=False,
            made=False,
        )
        for each in (media.subtitles if media else ())
    ]
    subtitles += [
        SubtitleFacts(
            language=beside_language(each, video) or None,
            codec=None,
            text=True,
            forced=False,
            beside=True,
            made=each.name == made,
        )
        for each in _beside(video)
    ]
    return FileDetails(
        id=row["id"],
        path=row["path"],
        size=row["size"],
        found_at=row["found_at"],
        duration=row["duration"],
        problem=row["problem"],
        title_id=row["title_id"],
        title=row["title"],
        season=row["season"],
        episode=row["episode"],
        episode_end=row["episode_end"],
        episode_name=episode["name"] if episode else None,
        aired=episode["aired"] if episode else None,
        overview=episode["overview"] if episode else None,
        picture=PictureFacts(
            codec=media.video.codec,
            width=media.video.width,
            height=media.video.height,
            bit_depth=media.video.bit_depth,
            frame_rate=float(media.video.frame_rate) if media.video.frame_rate else None,
        )
        if media and media.video
        else None,
        sound=[
            SoundFacts(
                language=each.language or (row["heard"] if heard else None),
                codec=each.codec,
                channels=each.channels,
                lossless=each.lossless,
                heard=heard,
            )
            for number, each in enumerate(media.audio if media else ())
            for heard in [not each.language and number == row["heard_track"] and bool(row["heard"])]
        ],
        subtitles=subtitles,
        chapters=media.chapters if media else 0,
        converted=bool(media and media.maku_tag),
        converting=_converting(conn, row["problem"], media),
    )


@router.get("/titles/{title_id}/episodes/{season}/{number}")
def episode_details(title_id: int, season: int, number: int, conn: Database) -> EpisodeDetails:
    """One of a title's episodes as TMDB lists it, and its video when the library has it."""
    row = conn.execute(
        """SELECT name, aired, overview, minutes FROM episodes
           WHERE title_id = ? AND season = ? AND number = ?""",
        (title_id, season, number),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no such episode.")
    video = conn.execute(
        """SELECT id FROM files
           WHERE title_id = ? AND season = ? AND gone_at IS NULL
             AND ? BETWEEN episode AND COALESCE(episode_end, episode)
           ORDER BY problem IS NOT NULL, id LIMIT 1""",
        (title_id, season, number),
    ).fetchone()
    return EpisodeDetails(
        season=season,
        number=number,
        name=row["name"],
        aired=row["aired"],
        overview=row["overview"],
        minutes=row["minutes"],
        file_id=video["id"] if video else None,
    )


@router.get(
    "/files/{file_id}/picture",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def file_picture(
    file_id: int, conn: Database, paths: Paths, web: Web, toolbox: Toolbox
) -> FileResponse:
    """A picture for the top of a video's details: TMDB's from its episode, a frame from the
    file, or its show's wide picture. Fetched or taken once, then kept. `Maku-Picture` says
    which: `episode` or `show`."""
    found = pictures.of_file(conn, paths, web, toolbox.path("ffmpeg"), file_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no picture of this video yet.")
    return _fresh(found)


@router.get(
    "/titles/{title_id}/episodes/{season}/{number}/picture",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def episode_picture(
    title_id: int, season: int, number: int, conn: Database, paths: Paths, web: Web
) -> FileResponse:
    """A picture for the top of an episode's details, the library's or not: TMDB's from the
    episode, or its show's wide picture. Fetched once, then kept. `Maku-Picture` says which:
    `episode` or `show`."""
    found = pictures.of_episode(conn, paths, web, title_id, season, number)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no picture of this episode yet.")
    return _fresh(found)


def _fresh(found: pictures.Picture) -> FileResponse:
    """A picture the window asks for again each time (the one behind an address changes, as a
    match changes or TMDB's picture comes in place of a frame), saying whether it's from the
    episode, which the window blurs till asked for an episode not yet watched."""
    return FileResponse(
        found.path,
        media_type=artwork.media_type(found.path),
        headers={
            "Cache-Control": "no-cache",
            PICTURE_HEADER: "episode" if found.from_episode else "show",
        },
    )


def _beside(video: Path) -> list[Path]:
    """The subtitle files beside a video, named after it; none when its folder can't be read."""
    try:
        names = [each.name for each in video.parent.iterdir()]
    except OSError:
        return []
    return [video.with_name(each.name) for each in sorted(sidecars_of(video, names))]


def _converting(conn: Database, problem: str | None, media: MediaInfo | None) -> Converting:
    if problem or media is None:
        return Converting(state="broken", method=None, reasons=[])
    decision = decide(media, library_standard(conn))
    ready = decision.method is Method.RENAME
    return Converting(
        state="ready" if ready else "to convert",
        method=decision.method.value,
        reasons=list(decision.reasons),
    )
