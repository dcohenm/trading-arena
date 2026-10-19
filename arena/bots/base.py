from __future__ import annotations

from ..core import Proposal


class Bot:
    """Un bot recibe el contexto (datos hasta ahora, sus posiciones, su capital) y devuelve
    una Proposal con pesos objetivo. No toca el broker ni el exchange: eso es del motor."""

    type = "base"

    def __init__(self, name: str, every: str = "1h", params: dict | None = None):
        self.name = name
        self.every = every
        self.params = params or {}

    STATE_ATTRS: tuple = ()          # atributos internos que hay que guardar para reanudar

    def decide(self, ctx) -> Proposal | None:  # pragma: no cover
        raise NotImplementedError

    def get_state(self) -> dict:
        return {k: getattr(self, k) for k in self.STATE_ATTRS}

    def set_state(self, d: dict) -> None:
        for k in self.STATE_ATTRS:
            if k in d:
                setattr(self, k, d[k])

    def spec(self) -> dict:
        """Cómo reconstruir este bot (para guardar la población que va evolucionando)."""
        return {"name": self.name, "type": self.type, "every": self.every, "params": self.params}
