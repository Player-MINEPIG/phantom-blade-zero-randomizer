"""Resolve exact LevelLoot donor rows for a manually tracked playthrough."""

from dataclasses import dataclass

from . import loot


@dataclass(frozen=True)
class RewardLayout:
    remaining: dict[str, str]
    granted: dict[str, str]

    @property
    def origins(self):
        """Return the complete point-to-source map for the replacement package."""
        return self.granted | self.remaining


def _validate_permutation(permutation):
    if any(not isinstance(point, str) or not point for point in permutation):
        raise ValueError("Reward point IDs must be nonempty strings")
    if any(not isinstance(source, str) or not source for source in permutation.values()):
        raise ValueError("Reward source IDs must be nonempty strings")
    if permutation.keys() != set(permutation.values()):
        raise ValueError("Reward sources must be a permutation of the points")


def bind_plan(plan, prizes, aliases=None):
    """Read exact logical origins, recovering older item-only plans by their stock rule."""
    aliases = aliases or {}
    assignments = plan["rewards"]
    physical_by_point = {point: aliases.get(point, point) for point in assignments}
    point_by_physical = {row: point for point, row in physical_by_point.items()}
    if len(point_by_physical) != len(physical_by_point) or point_by_physical.keys() - prizes.keys():
        raise ValueError("Reward plan does not match the original loot rows")

    supplied = plan.get("reward_sources")
    if supplied is None:
        original = {row: prizes[row] for row in point_by_physical}
        physical = {row: assignments[point] for row, point in point_by_physical.items()}
        return {
            point_by_physical[row]: point_by_physical[donor]
            for row, donor in loot.reward_sources(original, physical).items()
        }

    _validate_permutation(supplied)
    if supplied.keys() - assignments.keys():
        raise ValueError("Reward source binding contains an unknown point")
    origins = {point: supplied.get(point, point) for point in assignments}
    for point, source in origins.items():
        if assignments[point] != prizes[physical_by_point[source]].item:
            raise ValueError(f"Reward source binding disagrees with the plan at {point}")
    return origins


def _remaining(permutation, granted, enabled):
    spent = {source: point for point, source in granted.items()}
    preferred = permutation if enabled else {point: point for point in permutation}
    remaining = {}
    for point in sorted(permutation.keys() - granted.keys()):
        source = preferred[point]
        # If the preferred source was already collected, carry its replacement
        # from the point that awarded it. A permutation keeps these paths disjoint.
        while source in spent:
            source = preferred[spent[source]]
        remaining[point] = source
    return remaining


def resolve_layout(permutation, *, enabled, vanilla_claimed=(), claims=(), protected=()):
    """Replay recorded claims against the mode active at each pickup."""
    _validate_permutation(permutation)
    if type(enabled) is not bool:
        raise ValueError("The requested reward mode must be boolean")
    fixed = {}
    for point in protected:
        if point not in permutation:
            raise ValueError(f"Unknown protected reward point: {point}")
        fixed[point] = point
    if fixed:
        permutation = _remaining(permutation, fixed, True) | fixed

    granted = {}
    for point in vanilla_claimed:
        if point not in permutation:
            raise ValueError(f"Unknown original reward point: {point}")
        if point in granted:
            raise ValueError(f"Reward point already recorded: {point}")
        granted[point] = point

    previous_mode = None
    remaining = {}
    for claim in claims:
        point = claim["point"]
        mode = claim["enabled"]
        if type(mode) is not bool:
            raise ValueError("Each reward claim must specify a boolean mode")
        if point not in permutation:
            raise ValueError(f"Unknown reward point: {point}")
        if point in granted:
            raise ValueError(f"Reward point already recorded: {point}")
        if previous_mode != mode:
            remaining = _remaining(permutation, granted, mode)
            previous_mode = mode
        source = remaining.pop(point)
        if "source" in claim and claim["source"] != source:
            raise ValueError(f"Reward source mismatch at {point}: the recorded mode gives {source}")
        granted[point] = source

    if previous_mode != enabled:
        remaining = _remaining(permutation, granted, enabled)
    return RewardLayout(remaining, granted)
