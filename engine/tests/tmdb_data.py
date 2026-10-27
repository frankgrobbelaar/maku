"""TMDB's answers, built the way TMDB shapes them, for tests (there is no key in the repo).

Air dates run weekly from the first episode, across seasons, so a show's episodes keep their
order in time the way real ones do.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from maku.core.fields import Json

DRAMA = 18


def tv_details(
    show_id: int,
    name: str,
    seasons: Sequence[int],
    *,
    first_aired: date,
    specials: int = 0,
    status: str = "Ended",
    titles: Mapping[tuple[int, int], str] | None = None,
    special_dates: Sequence[date] = (),
    aired: Mapping[tuple[int, int], date] | None = None,
    minutes: int = 45,
) -> dict[str, object]:
    """/tv/{id} with every season appended: `seasons` are the sizes of seasons 1, 2, …

    Episodes air weekly; `aired` sets an episode's date, and the weeks run on from there."""
    named = titles or {}
    dated = aired or {}
    answer: dict[str, object] = {
        "id": show_id,
        "name": name,
        "original_name": name,
        "first_air_date": first_aired.isoformat(),
        "status": status,
        "in_production": status == "Returning Series",
        "number_of_episodes": sum(seasons),
        "episode_run_time": [minutes],
        "poster_path": f"/poster-{show_id}.jpg",
        "backdrop_path": f"/backdrop-{show_id}.jpg",
        "seasons": [
            {"season_number": number, "episode_count": size}
            for number, size in enumerate([specials, *seasons])
            if number > 0 or specials
        ],
    }
    day = first_aired
    for number, size in enumerate(seasons, start=1):
        episodes: list[Json] = []
        for episode in range(1, size + 1):
            day = dated.get((number, episode), day)
            episodes.append(
                _episode(show_id, number, episode, day, named.get((number, episode)), minutes)
            )
            day += timedelta(days=7)
        answer[f"season/{number}"] = {"season_number": number, "episodes": episodes}
    answer["last_air_date"] = (day - timedelta(days=7)).isoformat()
    if specials:
        days = list(special_dates) or [first_aired] * specials
        answer["season/0"] = {
            "season_number": 0,
            "episodes": [
                _episode(show_id, 0, n, days[min(n - 1, len(days) - 1)], named.get((0, n)), minutes)
                for n in range(1, specials + 1)
            ],
        }
    return answer


def movie_details(
    movie_id: int,
    title: str,
    released: date,
    minutes: int,
    *,
    collection: tuple[int, str] | None = None,
    status: str = "Released",
) -> dict[str, object]:
    """/movie/{id}: a film, in its collection when it's in one."""
    return {
        "id": movie_id,
        "title": title,
        "original_title": title,
        "release_date": released.isoformat(),
        "runtime": minutes,
        "status": status,
        "poster_path": f"/poster-movie-{movie_id}.jpg",
        "backdrop_path": f"/backdrop-movie-{movie_id}.jpg",
        "belongs_to_collection": (
            {"id": collection[0], "name": collection[1]} if collection else None
        ),
    }


def collection(collection_id: int, name: str, *films: Mapping[str, object]) -> dict[str, object]:
    """/collection/{id}: its films, as /movie/{id} gives them."""
    return {
        "id": collection_id,
        "name": name,
        "parts": [
            {key: film[key] for key in ("id", "title", "original_title", "release_date")}
            for film in films
        ],
    }


def tv_search(*results: tuple[int, str, date | None]) -> dict[str, object]:
    """/search/tv: (id, name, first aired) of each show found."""
    return {
        "page": 1,
        "results": [
            {
                "id": show_id,
                "name": name,
                "original_name": name,
                "first_air_date": aired.isoformat() if aired else "",
                "genre_ids": [DRAMA],
                "origin_country": ["GB"],
                "original_language": "en",
                "popularity": 100.0 - index,
            }
            for index, (show_id, name, aired) in enumerate(results)
        ],
    }


def movie_search(*results: tuple[int, str, date | None]) -> dict[str, object]:
    """/search/movie: (id, title, released) of each film found."""
    return {
        "page": 1,
        "results": [
            {
                "id": movie_id,
                "title": title,
                "original_title": title,
                "release_date": released.isoformat() if released else "",
                "genre_ids": [DRAMA],
                "original_language": "en",
                "popularity": 50.0 - index,
            }
            for index, (movie_id, title, released) in enumerate(results)
        ],
    }


def _episode(
    show_id: int, season: int, number: int, aired: date, title: str | None, minutes: int
) -> Json:
    return {
        "season_number": season,
        "episode_number": number,
        "name": title or f"Episode {number}",
        "air_date": aired.isoformat(),
        "runtime": minutes,
        "still_path": f"/still-{show_id}-{season}-{number}.jpg",
    }
