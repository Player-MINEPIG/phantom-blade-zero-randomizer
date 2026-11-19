"""Swap native attack multipliers without replacing weapon meshes or abilities."""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from struct import pack

from .zen import SingleExport


DATA_TABLES = {
    "WeaponData": "574ae39c66ca3666ddcb24aa663b031931075dc39e2c328b0f9d4c9fc8bf8f66",
    "ShaqiWeaponData": "a9b3a7f0795975bab7e7ed339f4da6a555594bc633f3ec30ca463b7b5b940be4",
}
TABLE_FOLDER = "ProjectPBZ/Content/PBZContent/DataTable/UI/"
COMBAT_ROOT = "ProjectPBZ/Plugins/Secret/PBZCombatAsset/Content/"
CONFIG_SCHEMA = {"WeaponData": "PBZ_MainWeaponConfig_C", "ShaqiWeaponData": "PBZ_SubWeaponConfig_C"}
FORMS = {"WeaponData": "WeaponSnapSoulData", "ShaqiWeaponData": "ShaChiWeaponSnapSoulData"}
CATEGORY = {"WeaponData": "main_weapon", "ShaqiWeaponData": "shadow_weapon"}
EXCLUDED_ITEMS = frozenset({
    # Story and tutorial variants, traversal weapons, and placeholder items.
    "WoodenSword", "WoodenSwordHun", "Tang", "Tang_HorseCartCombat", "TangPrologue",
    "HeiMoShang", "HeiMoShangPrologue", "XieHuo", "MoQie", "ZhuGuangBaoQi",
    "BrutalAxe", "ShachiHook", "JinGua", "LionHead", "YouLongTou", "YouLongCha", "TigerCannon",
    "BaWangLianQiu", "MoShou", "NiTouChe", "UnnamedBow",
    # The tempered configuration omits the normalized multiplier map.
    "CaoOuSiXian",
})
MULTIPLIER_MAPS = ("Weapon Attack Multipliers", "Weapon Attack Multipliers Normalized")
DAMAGE_TAGS = tuple(
    "Damage.Attack.Target." + name for name in ("PhysicalDamage", "AngerDamage", "DeflectAngerDamage")
)


@dataclass(frozen=True)
class Weapon:
    category: str
    config_schema: str
    base: str
    tempered: str | None
    compatibility: str


def read_weapons(store, schemas):
    """Resolve overlapping vanilla rows to their cooked battle configuration paths."""
    inventory = {}
    other_paths = Counter()
    paths = {
        ("/PBZCombatAsset/" + path.removeprefix(COMBAT_ROOT).removesuffix(".uasset")).casefold(): path
        for path in store.files
        if path.startswith(COMBAT_ROOT) and path.endswith(".uasset")
    }
    for schema, digest in DATA_TABLES.items():
        path = f"{TABLE_FOLDER}DT_{schema}.uasset"
        data = store.read_file(path)
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"Unsupported weapon table build: {path}")
        package = SingleExport(data)
        reader = package.reader(schemas)
        if reader.read("10s") != bytes.fromhex("0003f9ffffff00000000"):
            raise ValueError(f"Unrecognized weapon table layout: {path}")
        for _ in range(reader.count()):
            reader.name()
            row = reader.properties(schema)
            weapon_id = row["ItemId"].value
            base = row["WeaponConfig"].value[0].casefold()
            new_form = row[FORMS[schema]].value["WeaponConfig"].value[0].casefold()
            if base not in paths or (new_form != "none" and new_form not in paths):
                raise ValueError(f"Unresolved weapon configuration path for {weapon_id}")
            family = row["WeaponType" if schema == "WeaponData" else "ShaChiWeaponType"].value or 0
            weapon = Weapon(
                CATEGORY[schema], CONFIG_SCHEMA[schema], paths[base], paths.get(new_form),
                f"{CATEGORY[schema]}:{family}",
            )
            if weapon_id in inventory and inventory[weapon_id] != weapon:
                raise ValueError(f"Conflicting weapon table entries for {weapon_id}")
            if weapon_id in EXCLUDED_ITEMS:
                other_paths.update([weapon.base, weapon.tempered])
            else:
                inventory[weapon_id] = weapon
        if reader.position != reader.end:
            raise ValueError(f"Trailing data in weapon table: {path}")
    path_counts = Counter(path for w in inventory.values() for path in (w.base, w.tempered) if path)
    return {
        id_: weapon for id_, weapon in inventory.items()
        if all(path is None or (path_counts[path] == 1 and not other_paths[path]) for path in (weapon.base, weapon.tempered))
    }


def read_config(package, schemas, schema):
    reader = package.reader(schemas)
    fields = reader.properties(schema)
    if reader.read("I") != 0 or reader.position != reader.end:
        raise ValueError("Unexpected data after the weapon configuration properties")
    return fields


def _read_maps(package, schemas, schema):
    fields = read_config(package, schemas, schema)
    result = {}
    for key in MULTIPLIER_MAPS:
        field = fields.get(key)
        if field is None or field.value is None:
            raise ValueError(f"Missing combat multiplier field {key!r}")
        removed, entries = field.value
        multipliers = {tag["TagName"].value: value for tag, value in entries}
        if (
            removed or len(entries) != len(multipliers)
            or any(not isfinite(value) for value in multipliers.values())
        ):
            raise ValueError(f"Unexpected combat multiplier map {key!r}")
        result[key] = field, multipliers
    return result


def _stat_patch(package, schemas, destination_schema, source_maps):
    target_maps = _read_maps(package, schemas, destination_schema)
    name_index = {name: index for index, name in enumerate(package.names)}
    replacements = []
    expected = {}
    for key, (field, original) in target_maps.items():
        _, donor = source_maps[key]
        updated = {tag: value for tag, value in original.items() if tag not in DAMAGE_TAGS}
        updated.update((tag, donor[tag]) for tag in DAMAGE_TAGS if tag in donor)
        expected[key] = updated
        if updated == original:
            continue
        try:
            # No removed keys. Each key is an unversioned GameplayTag struct
            # with only TagName present, followed by the float64 multiplier.
            packed = pack("<ii", 0, len(updated)) + b"".join(
                pack("<HIId", 0x0300, name_index[tag], 0, value) for tag, value in updated.items()
            )
        except KeyError as error:
            raise ValueError(f"Weapon configuration lacks damage tag {error.args[0]}") from error
        replacements.append((field, packed))
    if not replacements:
        return package.data
    result = package.replace(replacements)
    check = _read_maps(SingleExport(result), schemas, destination_schema)
    if any(actual != expected[key] for key, (_, actual) in check.items()):
        raise ValueError("Re-read weapon multipliers differ from the assigned profile")
    return result


def _config_paths(weapon):
    if weapon.tempered is not None:
        return weapon.base, weapon.tempered
    return (weapon.base,)


def patch_stats(store, schemas, assignments):
    """Return an original cooked path → patched bytes for each changed config."""
    changed = {target: source for target, source in assignments.items() if target != source}
    if not changed:
        return {}
    weapons = read_weapons(store, schemas)
    missing = (changed.keys() | changed.values()) - weapons.keys()
    if missing:
        raise ValueError(f"Unverified weapon stat sources: {', '.join(sorted(missing))}")
    for target, source in changed.items():
        if weapons[target].compatibility != weapons[source].compatibility:
            raise ValueError(f"Incompatible weapon types: {target} and {source}")
    originals = {
        path: SingleExport(store.read_file(path))
        for id_ in changed.keys() | changed.values()
        for path in _config_paths(weapons[id_])
    }
    patches = {}
    for target, source in changed.items():
        destination, donor = weapons[target], weapons[source]
        for position, path in enumerate(_config_paths(destination)):
            source_path = (donor.tempered or donor.base) if position else donor.base
            source_maps = _read_maps(originals[source_path], schemas, donor.config_schema)
            result = _stat_patch(originals[path], schemas, destination.config_schema, source_maps)
            if result != originals[path].data:
                patches[path] = result
    return patches
