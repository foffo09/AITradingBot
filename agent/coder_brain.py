from __future__ import annotations

import ast
from pathlib import Path

from core.state import Market
from src.strategy.moving_average import MovingAverageStrategy


class BaseStrategy(MovingAverageStrategy):
    """Trusted repo implementation; generated source can only select MA windows."""


class CoderBrain:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate(source: str) -> tuple[int, int]:
        if len(source) > 1024:
            raise ValueError("Strategy source too long")
        tree = ast.parse(source)
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.ClassDef):
            raise ValueError("Exactly one strategy class required")
        cls = tree.body[0]
        if (cls.name != "GeneratedStrategy" or cls.decorator_list or cls.keywords
                or getattr(cls, "type_params", []) or len(cls.bases) != 1
                or not isinstance(cls.bases[0], ast.Name) or cls.bases[0].id != "BaseStrategy"
                or len(cls.body) != 2):
            raise ValueError("Only the bounded BaseStrategy template is accepted")
        values: dict[str, int] = {}
        for node in cls.body:
            if (not isinstance(node, ast.Assign) or len(node.targets) != 1
                    or not isinstance(node.targets[0], ast.Name)
                    or node.targets[0].id not in {"short_window", "long_window"}
                    or not isinstance(node.value, ast.Constant) or type(node.value.value) is not int):
                raise ValueError("Only integer window assignments are accepted")
            if node.targets[0].id in values:
                raise ValueError("Duplicate window assignment")
            values[node.targets[0].id] = node.value.value
        short, long = values["short_window"], values["long_window"]
        if not 2 <= short < long <= 100:
            raise ValueError("Invalid strategy windows")
        return short, long

    def generate(self, market: Market, short: int, long: int) -> tuple[str, BaseStrategy]:
        source = f"class GeneratedStrategy(BaseStrategy):\n    short_window = {short}\n    long_window = {long}\n"
        windows = self.validate(source)
        path = self.directory / f"{market.lower()}.py"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(source, encoding="utf-8")
        temporary.replace(path)
        # Parse into trusted parameters: no exec/import of untrusted Python is needed.
        return source, BaseStrategy(*windows)

    @staticmethod
    def candidates(volatility: float) -> tuple[tuple[int, int], ...]:
        return ((2, 8), (3, 12), (5, 20)) if volatility > 0.03 else ((5, 15), (10, 30), (15, 45))
