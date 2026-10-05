"""Compare requested state with actual readback, accounting for Blender float storage."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Verification:
    expected: dict
    actual: dict
    differences: tuple[str, ...]
    absolute_tolerance: float = 1e-5
    relative_tolerance: float = 1e-6

    @property
    def matched(self) -> bool:
        return not self.differences

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "expected": self.expected,
            "actual": self.actual,
            "differences": list(self.differences),
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
        }


def compare(expected: dict, actual: dict) -> Verification:
    differences = []

    def visit(wanted, readback, path):
        if isinstance(wanted, dict):
            if not isinstance(readback, dict):
                differences.append(path)
                return
            for key, value in wanted.items():
                if key not in readback:
                    differences.append(f"{path}.{key}")
                else:
                    visit(value, readback[key], f"{path}.{key}")
        elif isinstance(wanted, (list, tuple)):
            if not isinstance(readback, (list, tuple)) or len(wanted) != len(readback):
                differences.append(path)
            else:
                for index, (value, received) in enumerate(zip(wanted, readback, strict=True)):
                    visit(value, received, f"{path}[{index}]")
        elif type(wanted) in (int, float):
            if type(readback) not in (int, float) or not math.isclose(
                wanted, readback, rel_tol=1e-6, abs_tol=1e-5
            ):
                differences.append(path)
        elif type(wanted) is not type(readback) or wanted != readback:
            differences.append(path)

    visit(expected, actual, "$")
    return Verification(expected, actual, tuple(differences))
