"""The database schema, as an append-only list of migrations.

Migration N upgrades the database from version N-1 to N; the version lives in
SQLite's `PRAGMA user_version`. Never edit a migration once it has shipped in a
release: add a new one at the end instead.

Maku began from Kura's schema as it stood at Kura 1.3.0 (Kura's migrations in one), its entries
made TMDB's: an entry is a TMDB show or film (core/catalog.py).
"""

from typing import Final

MIGRATIONS: Final[tuple[str, ...]] = (
    # 1. Everything, as Kura's schema stood at 1.3.0.
    """
    -- Maku's preferences, one JSON value per key.
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL  -- JSON
    ) STRICT;

    -- Plans and their changes: the undo journal for every rename, move, quarantine and
    -- conversion.
    CREATE TABLE plans (
        id         INTEGER PRIMARY KEY,
        title      TEXT NOT NULL,
        created_at TEXT NOT NULL,
        applied_at TEXT,
        undone_at  TEXT,
        kind       TEXT NOT NULL DEFAULT 'tidy' CHECK (kind IN ('tidy', 'convert'))
    ) STRICT;

    CREATE TABLE changes (
        id           INTEGER PRIMARY KEY,
        plan_id      INTEGER NOT NULL REFERENCES plans (id),
        position     INTEGER NOT NULL,
        kind         TEXT NOT NULL CHECK (kind IN ('move', 'quarantine')),
        source       TEXT NOT NULL,
        target       TEXT NOT NULL,
        label        TEXT NOT NULL,
        reason       TEXT NOT NULL,
        state        TEXT NOT NULL DEFAULT 'planned'
                     CHECK (state IN ('planned', 'moving', 'done', 'failed', 'undoing', 'undone')),
        problem      TEXT,
        created_dirs TEXT NOT NULL DEFAULT '[]',  -- JSON: folders this change created
        cleared_at   TEXT,  -- when History stopped listing it
        UNIQUE (plan_id, position)
    ) STRICT;

    -- The library's folders, and every video found in them.
    CREATE TABLE folders (
        id       INTEGER PRIMARY KEY,
        path     TEXT NOT NULL UNIQUE COLLATE NOCASE,
        added_at TEXT NOT NULL
    ) STRICT;

    CREATE TABLE files (
        id             INTEGER PRIMARY KEY,
        folder_id      INTEGER NOT NULL REFERENCES folders (id) ON DELETE CASCADE,
        path           TEXT NOT NULL UNIQUE COLLATE NOCASE,
        size           INTEGER NOT NULL,
        modified       INTEGER NOT NULL,  -- nanoseconds since 1970, as Windows reports it
        found_at       TEXT NOT NULL,
        seen_at        TEXT NOT NULL,     -- the last scan that found it
        gone_at        TEXT,              -- a later scan didn't find it
        probed_at      TEXT,              -- when ffprobe read it; NULL while it's still to read
        probe          TEXT,              -- ffprobe's JSON report
        problem        TEXT,              -- why it couldn't be read, in words
        duration       REAL,              -- seconds
        width          INTEGER,
        height         INTEGER,
        codec          TEXT,              -- the picture's codec, such as hevc
        title_id       INTEGER REFERENCES titles (id) ON DELETE SET NULL,
        entry_id       INTEGER,           -- the TMDB show or film it was matched to
        season         INTEGER,
        episode        INTEGER,
        episode_end    INTEGER,
        matched        TEXT CHECK (matched IN ('sure', 'unsure', 'none', 'extra', 'ignored')),
        confidence     INTEGER,
        guesses        TEXT,              -- JSON: what the review screen offers
        pinned         INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),  -- the owner chose
        identified_at  TEXT,
        marked_at      TEXT,              -- when the owner marked it broken
        sound          TEXT,              -- JSON: its sound tracks' languages
        subtitles      TEXT,              -- JSON: its subtitles' languages
        health_at      TEXT,              -- when the overnight health check last played it
        health_problem TEXT
    ) STRICT;

    CREATE INDEX files_by_folder ON files (folder_id);
    CREATE INDEX files_by_title ON files (title_id);

    -- A show or film the library has, with what TMDB says of it.
    CREATE TABLE titles (
        id            INTEGER PRIMARY KEY,
        kind          TEXT NOT NULL CHECK (kind IN ('series', 'movie')),
        name          TEXT NOT NULL,
        year          INTEGER,
        released      TEXT,     -- first aired, or the film's release: lists sort by it
        tmdb_type     TEXT CHECK (tmdb_type IN ('tv', 'movie')),
        tmdb_id       INTEGER,
        entry_id      INTEGER,  -- the entry it was found by
        airing        INTEGER NOT NULL DEFAULT 0 CHECK (airing IN (0, 1)),
        poster        TEXT,     -- TMDB's image path
        checked_at    TEXT,     -- when its episode list was last asked for
        backdrop      TEXT,
        overview      TEXT,
        genres        TEXT,     -- JSON
        studio        TEXT,
        status        TEXT CHECK (
                          status IN ('finished', 'airing', 'coming', 'cancelled', 'paused')),
        ended         TEXT,
        minutes       INTEGER,
        poster_choice TEXT,     -- the poster the owner chose, over TMDB's
        UNIQUE (tmdb_type, tmdb_id)
    ) STRICT;

    CREATE TABLE episodes (
        title_id INTEGER NOT NULL REFERENCES titles (id) ON DELETE CASCADE,
        season   INTEGER NOT NULL,  -- 0 holds the specials
        number   INTEGER NOT NULL,
        name     TEXT,
        aired    TEXT,
        minutes  INTEGER,
        overview TEXT,
        still    TEXT,              -- a picture from it: a path on TMDB's image server
        PRIMARY KEY (title_id, season, number)
    ) STRICT, WITHOUT ROWID;

    CREATE TABLE scans (
        id          INTEGER PRIMARY KEY,
        started_at  TEXT NOT NULL,
        finished_at TEXT,
        state       TEXT NOT NULL CHECK (state IN ('running', 'paused', 'done', 'failed')),
        stage       TEXT NOT NULL CHECK (
                        stage IN ('finding', 'reading', 'identifying', 'checking', 'done')),
        problem     TEXT,
        note        TEXT,    -- what the scan couldn't do, though it finished
        added       INTEGER, -- videos it found new
        gone        INTEGER  -- videos gone since the scan before
    ) STRICT;

    -- How entries relate: a film and the others of its collection, before and after it.
    CREATE TABLE entry_links (
        entry_id   INTEGER NOT NULL,  -- an entry Maku matched files to
        related_id INTEGER NOT NULL,  -- an entry it relates to
        relation   TEXT NOT NULL,     -- PREQUEL or SEQUEL
        PRIMARY KEY (entry_id, related_id)
    ) STRICT, WITHOUT ROWID;

    -- What TMDB says of every entry tied to the library's, the library's or not: a franchise's
    -- page shows what the library lacks (maku/franchises.py).
    CREATE TABLE entries (
        id          INTEGER PRIMARY KEY,  -- a show's TMDB number, or a film's negated
        name        TEXT,     -- NULL once TMDB no longer has it
        names       TEXT,     -- JSON: every name it goes by
        kind        TEXT,     -- series or movie
        status      TEXT,     -- finished, airing, coming, cancelled or paused
        started     TEXT,
        episodes    INTEGER,
        cover       TEXT,     -- its poster's path on TMDB's image server
        checked_at  TEXT NOT NULL,  -- when TMDB was last asked about it
        description TEXT,
        genres      TEXT,     -- JSON
        studio      TEXT,
        ended       TEXT,
        minutes     INTEGER,
        collection  TEXT      -- a film's collection's name: "The Harbour Line Collection"
    ) STRICT;

    -- The queue: conversions, English subtitles to make, and English to add from another copy.
    CREATE TABLE subtitle_batches (
        id       INTEGER PRIMARY KEY,
        title    TEXT NOT NULL,  -- what they're for: "The Harbour Line · Season 1"
        quality  TEXT NOT NULL CHECK (quality IN ('best', 'fast')),
        language TEXT NOT NULL,  -- the sound they're made from: "fra"
        added_at TEXT NOT NULL
    ) STRICT;

    CREATE TABLE jobs (
        id              INTEGER PRIMARY KEY,
        file_id         INTEGER NOT NULL REFERENCES files (id) ON DELETE CASCADE,
        method          TEXT NOT NULL CHECK (method IN ('remux', 'reencode', 'fast', 'best')),
        position        INTEGER NOT NULL,  -- the order the queue takes them in
        state           TEXT NOT NULL DEFAULT 'queued' CHECK (
                            state IN ('queued', 'running', 'replacing', 'done', 'failed',
                                      'skipped', 'restored')),
        added_at        TEXT NOT NULL,
        started_at      TEXT,
        finished_at     TEXT,
        problem         TEXT,              -- why it failed, in words
        plan_id         INTEGER REFERENCES plans (id),  -- the original set aside, the result put
                                                        -- in its place
        source_size     INTEGER,           -- the original as it was, to put it back
        source_modified INTEGER,
        source_probe    TEXT,
        output_size     INTEGER,
        output_probe    TEXT,              -- the result, checked, waiting to take its place
        retry_at        TEXT,              -- when to try putting it in place again
        log             TEXT,              -- what ffmpeg said when it failed
        kind            TEXT NOT NULL DEFAULT 'convert'
                        CHECK (kind IN ('convert', 'subtitles', 'merge')),
        sound           INTEGER,           -- the sound track subtitles are made from
        batch_id        INTEGER REFERENCES subtitle_batches (id) ON DELETE SET NULL,
        other_id        INTEGER REFERENCES files (id) ON DELETE SET NULL  -- the other copy
    ) STRICT;

    CREATE INDEX jobs_by_state ON jobs (state, position);

    CREATE TABLE made_subtitles (
        file_id  INTEGER PRIMARY KEY REFERENCES files (id) ON DELETE CASCADE,
        name     TEXT NOT NULL,     -- after the video's own name: ".en.srt"
        batch_id INTEGER REFERENCES subtitle_batches (id) ON DELETE SET NULL,
        language TEXT NOT NULL,     -- what Whisper heard: "fr"
        size     INTEGER NOT NULL,  -- as Maku wrote them, in bytes
        modified INTEGER NOT NULL,  -- and when, in nanoseconds: an edit changes it
        made_at  TEXT NOT NULL,
        sound    INTEGER            -- the sound track they were made from
    ) STRICT;

    -- The poster and fanart Maku wrote next to a title's videos, for media servers.
    CREATE TABLE artwork_files (
        path       TEXT PRIMARY KEY,  -- poster.jpg or fanart.jpg next to a title's videos
        title_id   INTEGER NOT NULL REFERENCES titles (id) ON DELETE CASCADE,
        size       INTEGER NOT NULL,  -- as Maku wrote it
        written_at TEXT NOT NULL
    ) STRICT;

    -- What the owner has watched, and where each video stopped (maku/watched.py).
    CREATE TABLE watched (
        file_id    INTEGER PRIMARY KEY REFERENCES files (id) ON DELETE CASCADE,
        position   REAL NOT NULL,  -- seconds in, where it last stopped
        duration   REAL,           -- how long it plays, as the player had it
        played_at  TEXT,           -- when it last played (UTC); None: out of Continue watching
        watched_at TEXT            -- seen to its last tenth, or marked watched
    ) STRICT;

    -- The episodes the owner was told are out today (maku/coming.py), so each is told once.
    CREATE TABLE aired_told (
        title_id INTEGER NOT NULL REFERENCES titles (id) ON DELETE CASCADE,
        season   INTEGER NOT NULL,
        number   INTEGER NOT NULL,
        told_at  TEXT NOT NULL,
        PRIMARY KEY (title_id, season, number)
    ) STRICT;
    """,
)
