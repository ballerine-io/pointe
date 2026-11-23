"""null: starts the sessions and does nothing. The floor: every table has its row."""

from adapters.base import Base
from core.adapter import CAPABILITIES


class Null(Base):
    name = "null"
    kind = "null"
    capabilities = frozenset(CAPABILITIES)  # all, as no-ops

    def type(self, text, session=None):
        pass

    def key(self, name, session=None):
        pass
