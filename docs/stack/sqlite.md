# SQLite (Maku's database)

Everything Maku knows lives in one [SQLite](https://sqlite.org) file, `maku.db`, in the data folder.
There is no database server: Python's built-in `sqlite3` module opens the file directly. One file is
easy to back up, export, move to another drive, and open with any SQLite tool.

## Files

| File | What it holds |
| --- | --- |
| `maku/db.py` | `connect()`, `migrate()`, `schema_version()` |
| `maku/migrations.py` | The schema, as an append-only list of SQL scripts |
| `maku/export.py` | The export zip, which includes a consistent copy of the database |

## Connecting

`db.connect(path)` opens the database the way Maku always uses it:

- `journal_mode = WAL`: readers keep working while a write happens, and a crash can't corrupt the
  file.
- `foreign_keys = ON`: relationships are enforced.
- `busy_timeout = 5000`: a writer waits up to five seconds for another instead of failing.
- Rows come back as `sqlite3.Row` (by name: `row["key"]`).

The API opens one connection per request (the `Database` dependency) and closes it afterwards.
Connections may move between threads but are never shared by two at once.

Write in transactions: `with conn: conn.execute(...)` commits on success and rolls back on error.
Always pass values as parameters (`?`), never with f-strings.

## Migrations

The schema version is SQLite's `PRAGMA user_version`. `migrations.py` holds `MIGRATIONS`, a tuple of
SQL scripts: script 1 takes a new database to version 1, script 2 to version 2, and so on.
`migrate()` runs the missing ones in order, each inside its own transaction, so a failure leaves the
database exactly as it was. A database newer than the running Maku is refused with a clear message
rather than touched.

To change the schema, append a script; never edit one that has shipped in a release. Use `STRICT`
tables, give every table a primary key, and add the new data to the export.

Maku began from Kura's schema as it stood at Kura 1.3.0, its migrations folded into one, with
what Kura kept of its other catalogue made TMDB's: migration 1 is all of it, and Maku's own
changes follow from 2.

## The tables

| Table | Holds |
| --- | --- |
| `settings` | Maku's preferences: one JSON value per key |
| `plans` | Plans of changes: a title, when each was made, applied and undone, and its kind (`tidy`, which deleting uses too, or `convert`) |
| `changes` | The undo journal: each plan's moves and quarantines in order, with their state (`planned`, `moving`, `done`, `failed`, `undoing`, `undone`), any problem, the folders each one created, and when what one set aside was cleared out of quarantine |
| `folders` | The library folders, unique whatever their case |
| `files` | Every video a scan found: its folder, path, size and time (to notice changes), when it was found, last seen and gone, and once read, ffprobe's JSON report with the duration, size and codec at a glance, or why it couldn't be read. Then what it is: its title, the TMDB show or film it matched (`entry_id`), its season and episode as TMDB numbers them, how sure Maku is (`sure`, `unsure`, `none`, `extra`, `ignored`) with the best guesses for review, and whether the owner pinned it; its sound's and subtitles' languages; when the owner marked it broken (a scan leaves it so till it changes); and when the health check last played it, with what went wrong |
| `scans` | Each scan: when it started and finished, its state (`running`, `paused`, `done`, `failed`), its stage (`finding`, `reading`, `identifying`, `checking`, `done`), any problem, a note on what it couldn't do though it finished (no TMDB key, say), and how many videos it found new and gone |
| `titles` | Each series and film in the library: its kind (`series` or `movie`), name, year and release date (lists sort by it), its TMDB show or film and the entry it was found by, whether it's airing, its poster and wide picture, what its About panel shows (synopsis, genres, network or company, where it stands, its last day, an episode's length), the poster the owner chose (`poster_choice`), and when its episode list was last asked for |
| `episodes` | Each show's episode list, from TMDB: season (0 for the specials), number, name, air date, length, what happens in it (TMDB's synopsis), and where TMDB's picture from it is (`still`), for the top of its details |
| `entries` | What TMDB says of every show and film tied to the library's, the library's or not: names, kind, where it stands, first day, episodes, cover, synopsis, genres, network or company, and a film's collection; when TMDB was last asked. An id is a show's TMDB number, or a film's negated |
| `entry_links` | How entries relate: a film and the others of its collection, before it (`PREQUEL`) and after it (`SEQUEL`). What ties a collection together |
| `jobs` | The queue: each file waiting, being worked on or done, in the owner's order, its kind (`convert`, `subtitles`, `merge`), its state (`queued`, `running`, `replacing`, `done`, `failed`, `skipped`, `restored`), the plan that put its result in place, what it takes to put the original back, what the result was, when Maku next tries to put in place a result that waits beside an original another app has open, and what ffmpeg said when it failed |
| `subtitle_batches` | Each batch of English subtitles asked for at once: what for ("The Harbour Line · Season 1"), at which quality, from which language's sound |
| `made_subtitles` | The English subtitles Maku made beside a video, as it wrote them (name, size, time), what Whisper heard there and from which track: only these, unchanged, are Maku's |
| `artwork_files` | The poster and background pictures Maku wrote next to a title, with their size: only these, unchanged, are Maku's to take away |
| `watched` | Where each video stopped, when it last played, and when it was watched |
| `aired_told` | The episodes the owner was told are out today, so each is told once |

## Backups and export

- Consistent copies use SQLite's backup API (`source.backup(copy)`), never a file copy of a database
  in use. The export does this, and so do the nightly backups (`backups/maku 2026-10-11 0300.db`,
  the last 7 kept), each checked with `PRAGMA integrity_check` before it's kept. Backups made by
  hand, before a restore and from an export are named so (`maku 2026-10-11 1015 by hand.db`) and
  kept 7 of each kind; two made in one minute are `(2)` apart, and none is renamed over another.
- Restoring a backup opens it read-only (`file:…?mode=ro`, so one that went is never made anew,
  empty), checks it, backs up the live records (kept even when they don't check out: they're what
  there was, and the backup being restored is never pruned), then copies it into `maku.db` the
  same way, as the engine starts and before anything else opens the database, and migrates it if
  an older Maku made it.
- As the engine starts, `maku/rescue.py` checks the records (`PRAGMA quick_check`): damaged ones
  (SQLite's `SQLITE_CORRUPT` or `SQLITE_NOTADB`, a disk that can't read them,
  `SQLITE_IOERR_READ` or `_SHORT_READ`, or a check that doesn't come back `ok`) can't be backed up
  with the backup API, so restoring over them renames them aside instead, `-wal` first, so a new
  `maku.db` never meets an old write-ahead log. For a read error the app offers Try again first
  (the drive may have been away a moment). Another program holding the file isn't damage
  (`SQLITE_BUSY`): the engine fails to start, saying why.
- The exported `maku.db` is switched to `journal_mode = DELETE`, so it is one self-contained file.

## Looking inside

```powershell
cd engine; uv run python -c "import sqlite3; print(sqlite3.connect('.dev-data/maku.db').execute('select * from settings').fetchall())"
```

Or open `maku.db` in any SQLite browser while Maku isn't writing.
