"""Asking TMDB: the key, searches, whole shows with every season, films and posters."""

from datetime import date

import pytest

from maku.tmdb import API, IMAGES, Tmdb
from maku.web import Reply, WebError
from tests.fake_web import Asked, FakeWeb, reply
from tests.services import ASCENT, HARBOUR
from tests.tmdb_data import tv_details, tv_search

TOKEN = "maku-test-token.a-read-access-token.signature"
V3_KEY = "0123456789abcdef0123456789abcdef"


def test_a_read_access_token_goes_in_the_header():
    web = FakeWeb({f"GET {API}/authentication": {"success": True}})

    Tmdb(TOKEN, web).check()

    assert web.asked[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert "api_key" not in web.asked[0].query


def test_an_api_key_goes_in_the_address():
    web = FakeWeb({f"GET {API}/authentication": {"success": True}})

    Tmdb(f"  {V3_KEY}\n", web).check()  # pasted with spaces around it

    assert web.asked[0].query["api_key"] == V3_KEY
    assert "Authorization" not in web.asked[0].headers


def test_a_key_tmdb_refuses_says_so():
    refused = reply(
        {"status_code": 7, "status_message": "Invalid API key: You must be granted a valid key."},
        401,
    )
    web = FakeWeb({f"GET {API}/authentication": refused})

    with pytest.raises(WebError) as raised:
        Tmdb("wrong", web).check()

    assert raised.value.status == 401
    assert "didn't accept the key" in str(raised.value)


def test_a_search_for_shows_can_name_the_year():
    web = FakeWeb({f"GET {API}/search/tv": tv_search((4101, "The Harbour Line", date(2019, 3, 4)))})

    found = Tmdb(TOKEN, web).search("tv", "The Harbour Line", 2019)

    assert [hit.id for hit in found] == [4101]
    assert web.asked[0].query == {
        "query": "The Harbour Line",
        "include_adult": "false",
        "first_air_date_year": "2019",
    }


def test_a_film_search_uses_the_release_year():
    web = FakeWeb({f"GET {API}/search/movie": {"results": []}})

    Tmdb(TOKEN, web).search("movie", "Starfall: Ascent", 2015)

    assert web.asked[0].query["primary_release_year"] == "2015"


def test_a_show_comes_with_every_season_even_past_twenty():
    seasons = (24,) * 22  # a long show, such as a soap
    full = tv_details(4104, "Market Street", seasons, first_aired=date(1999, 10, 20), specials=3)

    def details(asked: Asked) -> object:
        wanted = asked.query.get("append_to_response")
        if wanted is None:
            return {key: value for key, value in full.items() if not key.startswith("season/")}
        return {**{"id": 4104}, **{key: full[key] for key in wanted.split(",")}}

    web = FakeWeb({f"GET {API}/tv/4104": details})

    market_street = Tmdb(TOKEN, web).show(4104)

    assert market_street is not None
    assert market_street.seasons == tuple(range(1, 23))
    assert len(market_street.season(0)) == 3
    assert len(market_street.episodes) == 22 * 24 + 3
    assert len(web.asked) == 3  # the show, then seasons 0-19, then 20-22


def test_a_show_tmdb_no_longer_has_is_none():
    web = FakeWeb()  # every address answers 404

    assert Tmdb(TOKEN, web).show(1) is None
    assert Tmdb(TOKEN, web).film(1) is None


def test_a_film():
    web = FakeWeb({f"GET {API}/movie/7103": ASCENT})

    ascent = Tmdb(TOKEN, web).film(7103)

    assert ascent is not None
    assert ascent.title == "Starfall: Ascent"


def test_a_poster_comes_from_the_image_server():
    web = FakeWeb({f"GET {IMAGES}/w342/poster-4101.jpg": Reply(200, {}, b"jpeg bytes")})

    assert Tmdb(TOKEN, web).poster(str(HARBOUR["poster_path"])) == b"jpeg bytes"
