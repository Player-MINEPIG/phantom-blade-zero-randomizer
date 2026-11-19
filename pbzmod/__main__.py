"""Build a playable seed package from the local retail installation."""

import argparse
from dataclasses import dataclass
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
from zipfile import ZipFile, ZIP_DEFLATED

from integrations.grants import flow_weapons, pooled
from integrations import pickup_visuals
from integrations.monsters import zen_spawners
from integrations.voices import zen_dialogue, zen_combat
from integrations.weapons import movesets, stats
from randomizer import generate
from randomizer.engine import ITEM_POOLS, WEAPON_CATEGORIES
from . import loot, pickup_sources
from .reward_layout import bind_plan
from .reward_receipts import receipt_locations
from .reward_rows import read_text_items
from .container import pack
from .usmap import load_usmap

ROOT = Path(__file__).resolve().parent.parent
NAME = "z_PBZSeedRandomizer_P"
VERSION = "steam-26367565-r2"


@dataclass
class SeedBuild:
    assets: dict
    dependencies: dict
    plan: dict
    catalog: dict
    recipe: dict


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def readers(tools):
    pkg = ModuleType("pbz_readers")
    pkg.__path__ = [str(tools.resolve())]
    sys.modules[pkg.__name__] = pkg
    return tuple(
        importlib.import_module(f"pbz_readers.{m}")
        for m in ("resources_reader", "pak_reader")
    )


def assemble(store, pak, helpers, schemas, config):
    allowed = {
        x["id"]
        for x in read_json(
            ROOT / "integrations/archipelago/catalog.upstream-v0.9.2.json"
        )["items"]
    }
    original = store.read_file(loot.PATH)
    texts = read_text_items(store, schemas)
    base_prizes = loot.select(
        original, helpers.name_batch(original)[0], allowed, text_items=texts
    )
    original_rows = loot.read_table(original, helpers.name_batch(original)[0])
    sources = pickup_sources.scan(store, schemas, original_rows)
    extra = read_json(ROOT / "integrations/grants/level_sources.json")
    for row, info in extra.items():
        if row in base_prizes and row not in sources:
            sources[row] = info
    selection = {row: base_prizes[row] for row in sources if row in base_prizes}
    items = {p.item: {"id": p.item, "category": p.category} for p in selection.values()}
    rewards = [
        {
            "id": row,
            "item": p.item,
            "source": sources[row]["source"],
            "compatibility": "level_loot",
            "original_kind": (
                "currency"
                if p.item.startswith("dust:")
                else "text" if p.item in texts else p.category
            ),
        }
        for row, p in selection.items()
    ]
    grants = flow_weapons.scan(store, exclude_items=set(items))
    for grant in grants.values():
        items[grant.item] = {"id": grant.item, "category": grant.category}
        rewards.append(
            grant.reward()
            | {"compatibility": "level_loot", "original_kind": grant.category}
        )
    expanded = pooled.extend_table(store, original, grants)
    names = helpers.name_batch(expanded)[0]
    prizes = loot.select(expanded, names, allowed, text_items=texts)
    aliases = pooled.physical_rows(grants)
    weapons = stats.read_weapons(store, schemas)
    for id_, weapon in weapons.items():
        items[id_] = {
            "id": id_,
            "category": weapon.category,
            "weapon_compatibility": weapon.compatibility,
            "stats": weapon.base,
            "moveset": weapon.base,
            "moveset_supported": id_ in movesets.SUPPORTED,
        }
    for item in items.values():
        if (
            item["category"] in {"main_weapon", "shadow_weapon"}
            and item["id"] not in weapons
        ):
            item.update(stats_supported=False, moveset_supported=False)

    voices = []
    adapters = []
    for module, enabled in (
        (zen_dialogue, config.get("ambient_voices", True)),
        (zen_combat, config.get("combat_voices", False)),
    ):
        if enabled:
            slots, originals = module.scan(store, pak, helpers)
            voices.extend(module.catalog_rows(slots))
            adapters.append((module, slots, originals))
    monsters = zen_spawners.catalog_monsters(store.read_file)
    catalog = {
        "version": VERSION,
        "items": list(items.values()),
        "rewards": rewards,
        "encounters": [{"id": g.encounter, "grants": []} for g in grants.values()],
        "monsters": monsters,
        "voices": voices,
    }
    plan = generate(catalog, config)
    patches, dependencies = {}, {}
    physical = {aliases.get(id_, id_): item for id_, item in plan["rewards"].items()}
    if plan["config"]["monster_mode"] != "off":
        patches.update(
            zen_spawners.patch_monsters(
                store.read_file, plan["monsters"], plan["config"]["monster_mode"]
            )
        )
    for module, slots, originals in adapters:
        local = {s.id: plan["voices"][s.id] for s in slots}
        patches.update(module.apply(originals, slots, local, helpers))
    weapon_patches, weapon_dependencies = movesets.build_patches(
        store, schemas, plan["weapon_stats"], plan["weapon_movesets"]
    )
    patches.update(weapon_patches)
    dependencies.update(weapon_dependencies)
    extras, extra_dependencies = patches.copy(), dependencies.copy()
    permutation = bind_plan(plan, prizes, aliases)
    plan["reward_sources"] = permutation
    quest_patches, quest_dependencies = pooled.rewrite_changed(store, grants, plan["rewards"])
    patches.update(quest_patches)
    dependencies.update(quest_dependencies)
    moved = {row for row, item in physical.items() if prizes[row].item != item}
    modified = loot.apply_reviewed(
        expanded, names, allowed, {row: prizes[row] for row in physical}, physical, text_items=texts,
    )
    settings = plan["config"]
    whitelist = set(settings["whitelist"])
    categories = ITEM_POOLS[settings["item_mode"]]
    visual_rows = {
        row for row, item in physical.items()
        if item in whitelist and items[item]["category"] in categories
    }
    if categories & WEAPON_CATEGORIES:
        # Fixed progression weapons retain their location and get the same key glow.
        for row in sources.keys() & original_rows.keys():
            levels = original_rows[row][1].get(1, [])
            if len(levels) == 1 and len(levels[0].get(3, [])) == 1:
                visual_rows.add(row)
    visuals, visual_dependencies, report = pickup_visuals.apply(
        store, schemas, modified, sources, patches, visual_rows
    )
    patches.update(visuals)
    dependencies.update(visual_dependencies)
    aligned = pickup_visuals.align_table(modified, report)
    if moved or aligned != modified:
        patches[loot.PATH] = aligned
    plan["pickup_visuals"] = report
    recipe = dict(
        permutation=permutation, aliases=aliases, grants=grants, expanded=expanded,
        allowed=sorted(allowed), texts=sorted(texts), visualRows=sorted(visual_rows),
        sources={row: data for row, data in sources.items() if row in visual_rows and data["source"] == "map_pickup"},
        extras=extras, extraDeps=extra_dependencies, receipts=receipt_locations(rewards, sources),
    )
    from .point_labels import describe_points
    recipe["points"] = describe_points(store, pak, helpers, schemas, rewards, sources, expanded, aliases)
    return SeedBuild(patches, dependencies, plan, catalog, recipe)


def main():
    from .paths import resolve_paths

    parser = argparse.ArgumentParser(description="影之刃零 · 原生随机周目构建器")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--out", type=Path, required=True, help="新输出目录")
    parser.add_argument("--game", type=Path)
    parser.add_argument("--ue", type=Path)
    parser.add_argument("--tools", type=Path, default=ROOT / ".work")
    parser.add_argument("--player-runtime", type=Path, help="复用已发布包内的 Tools/Python 运行时")
    parser.add_argument("--static", action="store_true", help="仅生成开发用的全局静态对照包")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error(f"输出目录已存在，请选择新目录：{out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    game, unrealpak, oodle = resolve_paths(args.game, args.ue)
    base = game / "ProjectPBZ/Content/Paks"
    helpers, pak_reader = readers(args.tools)
    codec = helpers.OodleReader(oodle)
    store = helpers.IoStore(base / "ProjectPBZ-Windows.utoc", codec)
    pak = pak_reader.PakReader(base / "ProjectPBZ-Windows.pak", codec)
    config = read_json(args.config)
    schemas = load_usmap(args.tools / "pbz.usmap")
    build = assemble(store, pak, helpers, schemas, config)
    with TemporaryDirectory(dir=out.parent) as tmp:
        stage = Path(tmp) / "release"
        stage.mkdir()
        info = {"catalog": VERSION, "seed": build.plan["seed"]}
        def write_native(assets, deps, paks):
            paks.mkdir(parents=True)
            pack(store, assets, paks / (NAME + ".utoc"), args.tools / "retoc/retoc.exe",
                 helpers, unrealpak, info, deps)

        if args.static:
            write_native(build.assets, build.dependencies, stage / "ProjectPBZ/Content/Paks/~mods")
        else:
            from .profile_package import seed_id, write_profile
            identifier = seed_id(build.plan["seed"])
            seed = stage / "Seeds" / identifier
            write_native(build.assets, build.dependencies, seed / "Saved/Paks")
            vanilla = seed.with_name(identifier + "-vanilla")
            write_native({loot.PATH: store.read_file(loot.PATH)}, {}, vanilla / "Saved/Paks")
            write_profile(stage, seed, vanilla, store, build, args.tools, args.player_runtime)
        files = sorted(p for p in stage.rglob("*") if p.is_file())
        for name, data in (("plan", build.plan), ("catalog", build.catalog), ("config", config)):
            (stage / f"{name}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        hashes = {(p.name if args.static else p.relative_to(stage).as_posix()):
                  sha256(p.read_bytes()).hexdigest() for p in files}
        (stage / "SHA256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf8")
        with ZipFile(stage / "PBZ-Randomizer.zip", "w", ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(stage).as_posix())
            if not args.static:
                archive.write(stage / "SHA256.json", "SHA256.json")
        os.rename(stage, out)
    print(f"{len(build.assets)} 个随机资产已生成并回读：{out}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, ImportError) as exc:
        sys.exit(str(exc))
