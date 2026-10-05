"""An editable page plan with undo/redo — the model behind the organiser grid.

Edits are previewed in the grid and only written when the user saves
(:func:`pdfsoul.core.organise.apply_plan`).
"""

from __future__ import annotations

from collections.abc import Iterable

from pdfsoul.core.organise import A4, PageRef, identity_plan

UNDO_LIMIT = 200


class PageList:
    def __init__(self, page_count: int, sizes: list[tuple[float, float]] | None = None) -> None:
        """``sizes`` (points, per source page) lets inserted blanks match their neighbours."""
        if sizes and len(sizes) == page_count:
            self._pages: tuple[PageRef, ...] = tuple(
                PageRef(i, 0, w, h) for i, (w, h) in enumerate(sizes)
            )
        else:
            self._pages = tuple(identity_plan(page_count))
        self._saved = self._pages
        self._undo: list[tuple[PageRef, ...]] = []
        self._redo: list[tuple[PageRef, ...]] = []

    # -- state ---------------------------------------------------------------------------------

    @property
    def pages(self) -> tuple[PageRef, ...]:
        return self._pages

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int) -> PageRef:
        return self._pages[index]

    @property
    def dirty(self) -> bool:
        return self._pages != self._saved

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def mark_saved(self) -> None:
        self._saved = self._pages

    # -- edits (each one is a single undo step) ------------------------------------------------

    def rotate(self, indexes: Iterable[int], angle: int) -> None:
        chosen = set(indexes)
        self._commit(r.rotated(angle) if i in chosen and not r.is_blank else r
                     for i, r in enumerate(self._pages))

    def delete(self, indexes: Iterable[int]) -> None:
        chosen = set(indexes)
        remaining = [r for i, r in enumerate(self._pages) if i not in chosen]
        if remaining:
            self._commit(remaining)

    def duplicate(self, indexes: Iterable[int]) -> None:
        chosen = set(indexes)
        out: list[PageRef] = []
        for i, ref in enumerate(self._pages):
            out.append(ref)
            if i in chosen:
                out.append(ref)
        self._commit(out)

    def insert_blank(self, at: int, size: tuple[float, float] | None = None) -> None:
        """Insert a blank page before position ``at`` (``len(self)`` appends)."""
        at = max(0, min(at, len(self._pages)))
        if size is None:
            neighbour = self._pages[at - 1] if at > 0 else (self._pages[0] if self._pages else None)
            size = (neighbour.width, neighbour.height) if neighbour else A4
        out = list(self._pages)
        out.insert(at, PageRef(None, 0, *size))
        self._commit(out)

    def move(self, indexes: Iterable[int], to: int) -> list[int]:
        """Move the pages at ``indexes`` (kept in order) so they land before position ``to``.

        Returns the new positions of the moved pages.
        """
        chosen = sorted(set(indexes))
        if not chosen:
            return []
        moving = [self._pages[i] for i in chosen]
        to -= sum(1 for i in chosen if i < to)
        rest = [r for i, r in enumerate(self._pages) if i not in set(chosen)]
        to = max(0, min(to, len(rest)))
        self._commit(rest[:to] + moving + rest[to:])
        return list(range(to, to + len(moving)))

    # -- undo/redo -----------------------------------------------------------------------------

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._pages)
        self._pages = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._pages)
        self._pages = self._redo.pop()
        return True

    def _commit(self, pages: Iterable[PageRef]) -> None:
        new = tuple(pages)
        if new == self._pages:
            return
        self._undo.append(self._pages)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._pages = new
