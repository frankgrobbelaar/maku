"""Where Maku keeps its data."""

import os
from dataclasses import dataclass
from pathlib import Path

# In the home folder once Maku's data moved to another drive: where it went. The uninstaller
# reads it too (app/src-tauri/windows/hooks.nsh).
LOCATION = "location.txt"
NOTE_ENCODING = "utf-16-le"  # the uninstaller's FileReadUTF16LE reads it so


@dataclass(frozen=True)
class DataPaths:
    """Maku's data folder: the database, artwork, backups and logs. Entry files never go here."""

    root: Path

    @property
    def database(self) -> Path:
        return self.root / "maku.db"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def artwork(self) -> Path:
        """Posters and pictures from TMDB, downloaded once (see maku/artwork.py)."""
        return self.root / "artwork"

    @property
    def cache(self) -> Path:
        """Answers from TMDB, kept for a while (see maku/cache.py)."""
        return self.root / "cache"

    @property
    def tools(self) -> Path:
        """What Maku downloads to work with, such as ffmpeg (see downloads.json)."""
        return self.root / "tools"

    @classmethod
    def default(cls) -> DataPaths:
        """Maku's data folder: its home, or where the owner moved it since (the home's
        location.txt says where, even while that drive is unplugged)."""
        return cls.at(cls.home())

    @classmethod
    def at(cls, home: Path) -> DataPaths:
        """The data folder of this home: the home itself, or where its note says the data went.
        The note is UTF-16 (`NOTE_ENCODING`), which the uninstaller reads whatever the path's
        letters; an older one may be UTF-8."""
        try:
            note = (home / LOCATION).read_bytes()
        except OSError:
            return cls(home)
        try:
            moved = note.decode(NOTE_ENCODING if b"\x00" in note else "utf-8").strip()
        except UnicodeDecodeError:
            return cls(home)
        return cls(Path(moved)) if moved else cls(home)

    @classmethod
    def home(cls) -> Path:
        r"""Where Maku looks for its data first: %LOCALAPPDATA%\Maku, or the folder in
        MAKU_DATA_DIR when that is set."""
        if override := os.environ.get("MAKU_DATA_DIR"):
            return Path(os.path.normpath(override))
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "Maku"
