# watchdog (noticing changes in the library folders)

[watchdog](https://github.com/gorakhargosh/watchdog) 6.0 (Apache-2.0) tells Maku when a file in a
library folder is added, removed, renamed or written, the moment Windows knows
(`ReadDirectoryChangesW`), without walking the folders on a timer. Walking every few minutes would
keep sleeping disks awake; being told costs nothing.

## How Maku uses it

[maku/watch.py](../../engine/src/maku/watch.py) runs inside `maku serve` (`create_app(...,
watch=True)`; tests leave it off):

- **At start** it catches up: a scan for whatever changed while Maku was closed, once setup is done
  and there are folders, unless a scan is running or the owner paused one.
- **Watching**: one watchdog observer per library folder that's there (`recursive=True`), followed
  as folders are added and forgotten. Windows stops telling about a folder once it goes (deleted,
  or its drive unplugged), so its observer is dropped then and a new one starts when it's back,
  with a scan for what changed meanwhile. Videos (by extension) count when they come, go, change
  or are renamed; folders when they come or are renamed, or go while the library has videos in
  them. Something written inside a folder doesn't count (the files tell for themselves), so Maku
  writing a gap report starts no scan. When something changed, a scan starts once the folder has
  been quiet for 5 seconds (`QUIET`), so a season still copying waits until it's done. A scan the
  owner paused stays paused.
- **Refreshing**: while no scan runs, episode lists that are due are asked for again (hourly for
  shows still airing, weekly for finished ones), and films weekly, for the titles the library
  holds a video of, and the gap reports follow. Offline or refused, every list waits an hour; a
  show or film TMDB no longer has waits until it's due again.
- **Collections and Coming up**: the films of the library's collections are asked about a few at a
  time (`maku/franchises.py`, see [tmdb.md](tmdb.md#collections)), and the owner is told of an
  episode that airs today (`maku/coming.py`).

It looks around every 15 seconds. Anything that goes wrong in one look is logged, and the next
look carries on.

## Notes

- Windows takes a moment after an observer starts before it reports changes; the catch-up scan at
  start covers anything that happens in that moment.
- A file write raises "created" and then "modified": both count as the same change, and the quiet
  period runs from the last one.
- A folder moved out of a watched folder, or deleted, comes as a "deleted" event that says it's a
  file (the folder is gone, so Windows can't tell); Maku asks its database whether it held videos
  there.
- watchdog 6.0 closes a folder's handle itself when the folder goes, and again when the observer
  is stopped. Windows may have given that number to another of Maku's files by then (the
  database's), and closing it crashed the engine, so Maku's observer uses its own emitter
  (`_Emitter` in maku/watch.py) that closes the handle once only.
- PyInstaller bundles watchdog without help; `tests/test_cli.py` (with `MAKU_ENGINE_EXE`) starts
  the bundled engine, which imports it.
