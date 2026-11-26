"""Shipping a session's transcript over a link, by this machine's byte offsets: what a node does for its hub (node.py)
and a machine for each person's voice (guests.py). Where each link is in a file (Tail), the next bytes to ship from
there, and where to go on from when the other side says where its mirror ends. Standard library only: a node imports
this, and loads no model and no vendor SDK."""

import os
from dataclasses import dataclass, field

READ_MAX = 4 << 20  # bytes read from one transcript per poll: a long backlog ships over several polls


@dataclass
class Tail:
    path: str
    gen: int = 0
    offset: int | None = None  # next byte to ship; None until the other side says where it is (welcome, resume)
    files: list[str] = field(default_factory=list)


def size(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def _line_end(f, read: int, read_max: int) -> int | None:
    """Bytes from the read's start to the end of the line it is in, with `read` bytes already read and no newline in
    them; None when the file ends before the line does."""
    while True:
        chunk = f.read(read_max)
        if not chunk:
            return None
        i = chunk.find(b"\n")
        if i >= 0:
            return read + i + 1
        read += len(chunk)


def read_new(path: str, offset: int, size: int, read_max: int = READ_MAX) -> tuple[bytes, int] | None:
    """The next bytes to ship from `offset`, and how many bytes before them are a line not shipped: one longer than a
    read (a pasted screenshot), which every poll would otherwise read again and never pass. None when that line is
    not written to its end yet."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(min(size - offset, read_max))
        skipped = 0
        if len(data) == read_max and b"\n" not in data:
            skipped = _line_end(f, len(data), read_max)
            if skipped is None:
                return None
            f.seek(offset + skipped)
            data = f.read(max(0, min(size - offset - skipped, read_max)))
    return data, skipped


def resume_to(tail: Tail, at: dict, size: int) -> bool:
    """Reseek `tail` to where the other side's mirror ends (`at`: {gen, offset}). False when it goes on in the same
    file. True when the other side is on another file, or past this one's end (it was replaced): a new gen from 0,
    which re-ships a file that already happened, so the caller says `transcript.repointed` with `history`."""
    if at["gen"] == tail.gen and at["offset"] <= size:
        tail.offset = at["offset"]
        return False
    tail.gen = max(tail.gen, at["gen"]) + (0 if at["gen"] < tail.gen else 1)
    tail.offset = 0
    return True
