"""Generate a deterministic assignment plan from an extracted game catalog."""

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
import json


SCHEMA_VERSION = 1
WEAPON_CATEGORIES = frozenset({"main_weapon", "shadow_weapon"})
COLLECTIBLE_SOURCES = frozenset({"chest", "enemy_drop", "map_pickup", "quest"})
ITEM_POOLS = {
    "all": WEAPON_CATEGORIES | {"collectible"},
    "weapons": WEAPON_CATEGORIES,
    "main_weapons": {"main_weapon"},
    "shadow_weapons": {"shadow_weapon"},
    "collectibles": {"collectible"},
}


class RandomizerError(ValueError):
    """The catalog or configuration cannot produce a valid plan."""


@dataclass(frozen=True)
class Reward:
    id: str
    item: str
    source: str
    requires: frozenset[str]
    encounter: str | None
    compatibility: str | None


@dataclass(frozen=True)
class Encounter:
    id: str
    requires: frozenset[str]
    grants: frozenset[str]


def _string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise RandomizerError(f"{path} must be a nonempty string")
    return value


def _strings(value, path):
    if not isinstance(value, list):
        raise RandomizerError(f"{path} must be an array")
    values = frozenset(_string(entry, f"{path}[{index}]") for index, entry in enumerate(value))
    if len(values) != len(value):
        raise RandomizerError(f"{path} contains duplicate entries")
    return values


def _choice(value, options, path):
    value = _string(value, path)
    if value not in options:
        raise RandomizerError(f"{path} must be one of {', '.join(sorted(options))}")
    return value


def _rows(catalog, name, *, optional=False):
    rows = catalog.get(name, [] if optional else None)
    if not isinstance(rows, list):
        raise RandomizerError(f"catalog.{name} must be an array")
    by_id = {}
    for index, row in enumerate(rows):
        path = f"catalog.{name}[{index}]"
        if not isinstance(row, dict):
            raise RandomizerError(f"{path} must be an object")
        id_ = _string(row.get("id"), f"{path}.id")
        if id_ in by_id:
            raise RandomizerError(f"catalog.{name} contains duplicate ID {id_!r}")
        by_id[id_] = row
    return dict(sorted(by_id.items()))


def _known(values, known, path):
    unknown = set(values).difference(known)
    if unknown:
        raise RandomizerError(f"{path} contains unknown IDs: {', '.join(sorted(unknown))}")


def _read_world(catalog, items):
    encounters = {}
    grant_sources = {}
    for id_, row in _rows(catalog, "encounters", optional=True).items():
        path = f"catalog.encounters[{id_!r}]"
        requires = _strings(row.get("requires", []), f"{path}.requires")
        grants = _strings(row.get("grants", []), f"{path}.grants")
        for token in sorted(grants):
            if token in items or token in grant_sources:
                raise RandomizerError(f"{path}.grants reuses progression ID {token!r}")
            grant_sources[token] = id_
        encounters[id_] = Encounter(id_, requires, grants)

    start = _strings(catalog.get("start", []), "catalog.start")
    required = _strings(catalog.get("required", []), "catalog.required")
    known_tokens = start | items.keys() | grant_sources.keys()
    _known(required, known_tokens, "catalog.required")
    for encounter in encounters.values():
        _known(encounter.requires, known_tokens, f"catalog.encounters[{encounter.id!r}].requires")

    rewards = {}
    for id_, row in _rows(catalog, "rewards").items():
        path = f"catalog.rewards[{id_!r}]"
        item = _string(row.get("item"), f"{path}.item")
        _known([item], items, f"{path}.item")
        source = _string(row.get("source"), f"{path}.source")
        requires = _strings(row.get("requires", []), f"{path}.requires")
        _known(requires, known_tokens, f"{path}.requires")
        encounter = row.get("encounter")
        if encounter is not None or source == "boss":
            encounter = _string(encounter, f"{path}.encounter")
            _known([encounter], encounters, f"{path}.encounter")
        rewards[id_] = Reward(id_, item, source, requires, encounter, _compatibility(row, path))
    return rewards, encounters, start, required


def _default_whitelist(items, rewards):
    return {id_ for id_, item in items.items() if item["category"] in WEAPON_CATEGORIES} | {
        reward.item
        for reward in rewards.values()
        if items[reward.item]["category"] == "collectible" and reward.source in COLLECTIBLE_SOURCES
    }


def _read_config(config, items, rewards):
    if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
        raise RandomizerError("config must be an object with string keys")
    defaults = {
        "item_mode": "all",
        "weapon_mode": "off",
        "monster_mode": "off",
        "ambient_voices": True,
        "combat_voices": False,
    }
    _known(config, defaults.keys() | {"seed", "whitelist", "weapon_stats", "weapon_movesets"}, "config")
    seed = config.get("seed")
    if not (type(seed) is int or (isinstance(seed, str) and seed.strip())):
        raise RandomizerError("config.seed must be an integer or a nonempty string")

    settings = defaults | config
    _choice(settings["item_mode"], ITEM_POOLS, "config.item_mode")
    _choice(settings["weapon_mode"], {"off", "linked", "independent"}, "config.weapon_mode")
    _choice(settings["monster_mode"], {"off", "unit", "group"}, "config.monster_mode")

    default_whitelist = _default_whitelist(items, rewards)
    whitelist = _strings(config["whitelist"], "config.whitelist") if "whitelist" in config else default_whitelist
    _known(whitelist, default_whitelist, "config.whitelist")
    settings["whitelist"] = sorted(whitelist)

    weapons_on = settings["weapon_mode"] != "off"
    settings.setdefault("weapon_stats", weapons_on)
    settings.setdefault("weapon_movesets", weapons_on)
    for flag in ("weapon_stats", "weapon_movesets", "ambient_voices", "combat_voices"):
        if type(settings[flag]) is not bool:
            raise RandomizerError(f"config.{flag} must be a boolean")
    if not weapons_on and (settings["weapon_stats"] or settings["weapon_movesets"]):
        raise RandomizerError("config.weapon_mode must be linked or independent to randomize weapon data")
    return dict(sorted(settings.items()))


class _Progression:
    def __init__(self, rewards, encounters, start, required, original):
        self.rewards = tuple(rewards.values())
        self.encounters = tuple(encounters.values())
        self.start = start
        self.required = required
        self.waiting_for_token = defaultdict(list)
        self.waiting_for_victory = defaultdict(list)
        self.requirement_counts = []

        for index, location in enumerate((*self.rewards, *self.encounters)):
            self.requirement_counts.append(len(location.requires))
            for token in location.requires:
                self.waiting_for_token[token].append(index)
        for index, reward in enumerate(self.rewards):
            if reward.encounter is not None:
                self.waiting_for_victory[reward.encounter].append(index)
                self.requirement_counts[index] += 1

        self.influential_tokens = self.waiting_for_token.keys() | required
        self.original_locations, original_tokens = self._reachable(original)
        unreachable = required - original_tokens
        if unreachable:
            raise RandomizerError(f"original progression cannot reach: {', '.join(sorted(unreachable))}")

    def _reachable(self, assignments):
        remaining = self.requirement_counts.copy()
        ready = deque(index for index, count in enumerate(remaining) if count == 0)
        tokens = set()
        reached = set()
        reward_count = len(self.rewards)

        def unblock(locations):
            for index in locations:
                remaining[index] -= 1
                if remaining[index] == 0:
                    ready.append(index)

        events = self.start
        while True:
            for token in events:
                if token not in tokens:
                    tokens.add(token)
                    unblock(self.waiting_for_token.get(token, ()))
            if not ready:
                return reached, tokens
            index = ready.popleft()
            reached.add(index)
            if index < reward_count:
                events = (assignments[self.rewards[index].id],)
            else:
                encounter = self.encounters[index - reward_count]
                unblock(self.waiting_for_victory.get(encounter.id, ()))
                events = encounter.grants

    def preserves(self, assignments):
        reached, tokens = self._reachable(assignments)
        return self.original_locations <= reached and self.required <= tokens


def _json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode("ascii")


def _permutation(ids, seed_key, *domain):
    salt = sha256(seed_key + _json_bytes(domain)).digest()
    return sorted(ids, key=lambda id_: (sha256(salt + _json_bytes(id_)).digest(), id_))


def _shuffle_rewards(rewards, encounters, start, required, items, config, seed_key):
    original = {id_: reward.item for id_, reward in rewards.items()}
    progression = _Progression(rewards, encounters, start, required, original)
    pool = ITEM_POOLS[config["item_mode"]]
    whitelist = set(config["whitelist"])
    pools = defaultdict(list)
    for id_, reward in rewards.items():
        category = items[reward.item]["category"]
        if category not in pool or reward.item not in whitelist:
            continue
        if category == "collectible" and reward.source not in COLLECTIBLE_SOURCES:
            continue
        suffix = () if reward.compatibility is None else (reward.compatibility,)
        pools[suffix].append(id_)

    for attempt in range(4):
        candidate = original.copy()
        for suffix, slots in pools.items():
            sources = _permutation(slots, seed_key, "rewards", attempt, *suffix)
            candidate.update((slot, original[source]) for slot, source in zip(slots, sources))
        if progression.preserves(candidate):
            return candidate

    # A full shuffle can misplace a required item. Start from the original layout
    # and retain only swaps that preserve the validated progression.
    assignments = original.copy()
    for attempt in range(3):
        for suffix, slots in pools.items():
            order = _permutation(slots, seed_key, "reward-swaps", attempt, *suffix)
            for left, right in zip(order, order[1:]):
                first, second = assignments[left], assignments[right]
                if first == second:
                    continue
                assignments[left], assignments[right] = second, first
                needs_check = first in progression.influential_tokens or second in progression.influential_tokens
                if needs_check and not progression.preserves(assignments):
                    assignments[left], assignments[right] = first, second
    return assignments


def _shuffle_weapons(items, config, seed_key):
    weapons = [id_ for id_, item in items.items() if item["category"] in WEAPON_CATEGORIES]
    whitelist = set(config["whitelist"])
    features = {"stats": "weapon_stats", "moveset": "weapon_movesets"}
    active = {
        field: {id_ for id_ in weapons if id_ in whitelist and items[id_].get(f"{field}_supported", True)}
        for field, flag in features.items() if config[flag]
    }
    linked = config["weapon_mode"] == "linked"
    if linked and len(active) == 2:
        common = active["stats"] & active["moveset"]
        active = dict.fromkeys(active, common)

    mappings = []
    for field, flag in features.items():
        assignments = dict(zip(weapons, weapons))
        pools = defaultdict(list)
        for id_ in sorted(active.get(field, ())):
            if items[id_].get(field) is None:
                raise RandomizerError(f"catalog.items[{id_!r}].{field} is required by config.{flag}")
            compatibility = items[id_].get("weapon_compatibility")
            suffix = () if compatibility is None else (compatibility,)
            pools[suffix].append(id_)
        domain = "linked" if linked else field
        for suffix, selected in pools.items():
            assignments.update(zip(selected, _permutation(selected, seed_key, "weapons", domain, *suffix)))
        mappings.append(assignments)
    return tuple(mappings)


def _compatibility(row, path):
    value = row.get("compatibility")
    return None if value is None else _string(value, f"{path}.compatibility")


def _shuffle_monsters(catalog, config, seed_key):
    rows = _rows(catalog, "monsters", optional=True)
    groups = defaultdict(list)
    unit_pools = defaultdict(list)
    for id_, row in rows.items():
        path = f"catalog.monsters[{id_!r}]"
        _string(row.get("actor"), f"{path}.actor")
        compatibility = _compatibility(row, path)
        unit_pools[compatibility].append(id_)
        group = row.get("group")
        if group is not None:
            groups[_string(group, f"{path}.group")].append((compatibility, id_))

    assignments = dict(zip(rows, rows))
    mode = config["monster_mode"]
    if mode == "unit":
        if not rows:
            raise RandomizerError("config.monster_mode unit requires monster slots")
        for compatibility, slots in unit_pools.items():
            assignments.update(zip(slots, _permutation(slots, seed_key, "monsters", "unit", compatibility)))
    elif mode == "group":
        if not groups:
            raise RandomizerError("config.monster_mode group requires catalog monster groups")
        group_pools = defaultdict(list)
        for group, members in groups.items():
            members.sort(key=lambda member: (member[0] or "", member[1]))
            group_pools[tuple(compatibility for compatibility, _ in members)].append(group)
        for signature, destinations in group_pools.items():
            destinations.sort()
            sources = _permutation(destinations, seed_key, "monsters", "group", signature)
            for destination, source in zip(destinations, sources):
                assignments.update(
                    (target_slot, source_slot)
                    for (_, target_slot), (_, source_slot) in zip(groups[destination], groups[source])
                )
    return assignments


def _shuffle_voices(catalog, config, seed_key):
    rows = _rows(catalog, "voices", optional=True)
    pools = defaultdict(list)
    for id_, row in rows.items():
        path = f"catalog.voices[{id_!r}]"
        kind = _choice(row.get("kind"), {"ambient", "combat", "cutscene"}, f"{path}.kind")
        _string(row.get("audio"), f"{path}.audio")
        if "subtitle" not in row:
            raise RandomizerError(f"{path}.subtitle is required (use null for an unsubtitled line)")
        compatibility = _compatibility(row, path)
        if kind != "cutscene" and config[f"{kind}_voices"]:
            pools[kind, compatibility].append(id_)

    assignments = dict(zip(rows, rows))
    for (kind, compatibility), slots in pools.items():
        assignments.update(zip(slots, _permutation(slots, seed_key, "voices", kind, compatibility)))
    return assignments


def generate(catalog, config):
    """Return a JSON-compatible assignment plan without modifying the inputs."""
    if not isinstance(catalog, dict):
        raise RandomizerError("catalog must be an object")
    version = _string(catalog.get("version"), "catalog.version")
    items = _rows(catalog, "items")
    for id_, item in items.items():
        path = f"catalog.items[{id_!r}]"
        _choice(item.get("category"), ITEM_POOLS["all"] | {"other"}, f"{path}.category")
        if item.get("weapon_compatibility") is not None:
            _string(item["weapon_compatibility"], f"{path}.weapon_compatibility")
        for flag in ("stats_supported", "moveset_supported"):
            if flag in item and type(item[flag]) is not bool:
                raise RandomizerError(f"{path}.{flag} must be a boolean")
    rewards, encounters, start, required = _read_world(catalog, items)
    config = _read_config(config, items, rewards)
    seed_key = sha256(_json_bytes([SCHEMA_VERSION, version, config["seed"]])).digest()
    reward_assignments = _shuffle_rewards(rewards, encounters, start, required, items, config, seed_key)
    weapon_stats, weapon_movesets = _shuffle_weapons(items, config, seed_key)
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_version": version,
        "seed": config["seed"],
        "config": config,
        "rewards": reward_assignments,
        "abilities": {id_: sorted(encounter.grants) for id_, encounter in encounters.items() if encounter.grants},
        "weapon_stats": weapon_stats,
        "weapon_movesets": weapon_movesets,
        "monsters": _shuffle_monsters(catalog, config, seed_key),
        "voices": _shuffle_voices(catalog, config, seed_key),
    }
