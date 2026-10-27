"""Results Maku made and no conversion is waiting with any more: a file skipped while its drive
was away, put back under another name by undoing a tidy-up, or held open a moment as it was
thrown away. A scan finds them beside the videos (their names end in .maku-converting) and takes
them away, so none stays on a drive for good.
"""

import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from maku.core.library import work_of

log = logging.getLogger(__name__)


def sweep(conn: sqlite3.Connection, found: Iterable[Path]) -> int:
    """Takes away the results found that no job is making, putting in place, or waiting with.
    Returns how many went."""
    wanted = {
        str(work_of(Path(row["path"]))).casefold()
        for row in conn.execute(
            """SELECT f.path FROM jobs AS j JOIN files AS f ON f.id = j.file_id
               WHERE j.state IN ('running', 'replacing')
                  OR (j.state = 'queued' AND j.retry_at IS NOT NULL)"""
        )
    }
    gone = 0
    for result in found:
        if str(result).casefold() in wanted:
            continue
        try:
            result.unlink(missing_ok=True)
        except OSError:
            log.warning("Couldn't remove %s; the next scan tries again", result)
            continue
        gone += 1
    if gone:
        log.info("Took away %d results no conversion was waiting with", gone)
    return gone
