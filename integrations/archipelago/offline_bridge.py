"""Play a local reward plan through the PBZArchipelago v0.9.2 file bridge."""

import argparse
from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl


DIRECTORY = Path(__file__).resolve().parent
STATE = "pbz-randomizer-session.json"
LOCK = "pbz-randomizer.lock"
INPUT_FILES = {"active.txt", "goal_ids.txt", "inbox.txt", "session.txt", STATE}
OUTPUT_FILES = {"alive.txt", "goal.txt", "notify.txt", "outbox.txt"}


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional(path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _write_atomic(path, content):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


@contextmanager
def _lock_bridge(directory):
    with (directory / LOCK).open("a+b") as lock:
        if os.name == "nt":
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _check_directory(directory, allowed):
    for entry in directory.iterdir():
        if entry.name not in allowed or entry.is_symlink() or not entry.is_file():
            raise ValueError(f"Unexpected entry in the dedicated bridge directory: {entry.name}")


def _check_new_save_dir(save_dir):
    if save_dir is None:
        raise ValueError("A new bridge session requires --new-save-dir for a fresh Steam profile")
    path = save_dir.resolve()
    parents = tuple(parent.name.casefold() for parent in path.parents[:4])
    if not re.fullmatch(r"\d{17}", path.name) or parents != ("steam", "savegames", "saved", "projectpbz"):
        raise ValueError("--new-save-dir must be the game's ProjectPBZ/Saved/SaveGames/Steam/<SteamID64> directory")
    if not path.parents[3].is_dir():
        raise ValueError("--new-save-dir must point to an existing ProjectPBZ installation")
    if path.exists() and not path.is_dir():
        raise ValueError("--new-save-dir is not a directory")
    if any(entry.suffix.casefold() == ".sav" for entry in path.rglob("*")):
        raise ValueError("The game save directory already contains a save. Start with a fresh Steam profile")


def _assignments(plan):
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("An assignment plan with schema version 1 is required")
    mapping = _read_json(DIRECTORY / "bridge-map.upstream-v0.9.2.json")
    catalog = _read_json(DIRECTORY / "catalog.upstream-v0.9.2.json")
    if plan.get("catalog_version") != mapping["version"]:
        raise ValueError(f"The plan must use the {mapping['version']} catalog")
    if any(plan.get(key) for key in ("abilities", "weapon_stats", "weapon_movesets", "monsters", "voices")):
        raise ValueError("The file bridge supports the reward-only plan")
    rewards = plan.get("rewards")
    original = {reward["id"]: reward["item"] for reward in catalog["rewards"]}
    if (
        not isinstance(rewards, dict)
        or rewards.keys() != original.keys()
        or any(not isinstance(cid, str) for cid in rewards.values())
        or Counter(rewards.values()) != Counter(original.values())
    ):
        raise ValueError("The plan must preserve the reward locations and item counts from the catalog")
    return {
        mapping["checks"][reward_id]: (cid, mapping["items"][cid])
        for reward_id, cid in rewards.items()
        if cid != original[reward_id]
    }


class OfflineBridge:
    def __init__(self, directory, plan, run_id, new_save_dir=None):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", run_id):
            raise ValueError("--run-id must be 1 to 40 lowercase ASCII letters, digits, underscores, or hyphens")
        self.directory = directory
        self.assignments = _assignments(plan)
        if not self.assignments:
            raise ValueError("The plan has no changed rewards to send to the bridge")
        fingerprint = sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        self.session = f"pbz_{run_id}_{fingerprint}"
        self.state = directory / STATE
        self.active = "".join(f"{number}\n" for number in sorted(self.assignments))
        saved = _read_optional(self.state)
        if saved is None:
            _check_directory(directory, {".keep", LOCK})
            _check_new_save_dir(new_save_dir)
            self.queue = []
            self._save_queue()
        else:
            self.queue = self._resume(json.loads(saved))
        _write_atomic(directory / "active.txt", self.active)
        _write_atomic(directory / "goal_ids.txt", "")
        self._publish_queue()
        _write_atomic(directory / "session.txt", self.session + "\n")

    def _resume(self, state):
        if not isinstance(state, dict) or state.get("session") != self.session:
            raise ValueError("This bridge directory belongs to a different plan or run ID")
        session_files = {f"{prefix}_{self.session}.txt" for prefix in ("applied", "granted", "kills")}
        files = INPUT_FILES | OUTPUT_FILES | session_files
        _check_directory(self.directory, {".keep", LOCK} | files | {name + ".tmp" for name in files})
        existing_session = _read_optional(self.directory / "session.txt")
        if existing_session is not None and existing_session.strip() != self.session:
            raise ValueError("The bridge session has changed since this run was initialized")
        existing_active = _read_optional(self.directory / "active.txt")
        if existing_active is not None and existing_active != self.active:
            raise ValueError("The bridge check IDs have changed since this run was initialized")
        queue = state.get("queue")
        if (
            not isinstance(queue, list)
            or any(type(check_id) is not int or check_id not in self.assignments for check_id in queue)
            or len(set(queue)) != len(queue)
        ):
            raise ValueError("Invalid saved bridge queue")
        return queue

    def _save_queue(self):
        _write_atomic(self.state, json.dumps({"session": self.session, "queue": self.queue}) + "\n")

    def _publish_queue(self):
        lines = [self.session]
        for check_id in self.queue:
            cid, data = self.assignments[check_id]
            lines.append(f"{data['grant']}\t{cid}\t{data['name']}\t")
        content = "\n".join(lines) + "\n"
        path = self.directory / "inbox.txt"
        if _read_optional(path) != content:
            _write_atomic(path, content)

    def poll(self):
        heartbeat = _read_optional(self.directory / "alive.txt")
        if not heartbeat:
            return 0
        heartbeat_fields = heartbeat.splitlines()
        if len(heartbeat_fields) < 2 or heartbeat_fields[1] != "0.9.2":
            raise ValueError("The bridge heartbeat must come from PBZArchipelago 0.9.2")
        if len(heartbeat_fields) < 3 or not heartbeat_fields[2]:
            return 0
        if heartbeat_fields[2] != self.session:
            raise ValueError("The game is reporting a different bridge session")
        snapshot = _read_optional(self.directory / "outbox.txt")
        if not snapshot:
            return 0
        checks = {int(check_id) for check_id in snapshot.split()}
        if checks - self.assignments.keys():
            raise ValueError("The game reported an unexpected reward check")
        new_checks = sorted(checks.difference(self.queue))
        if new_checks:
            self.queue.extend(new_checks)
            self._save_queue()
        self._publish_queue()
        return len(new_checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("bridge", type=Path, help="dedicated PBZArchipelago bridge directory")
    parser.add_argument("--run-id", required=True, help="stable identifier for one game run")
    parser.add_argument("--new-save-dir", type=Path, help="unplayed SteamID64 save directory, required to start a run")
    parser.add_argument("--once", action="store_true", help="check for new rewards once and exit")
    args = parser.parse_args()
    try:
        if (args.bridge / LOCK).is_symlink() or (args.bridge / STATE).is_symlink():
            raise ValueError("The dedicated bridge directory contains a linked state or lock file")
        if not (args.bridge / STATE).exists():
            _check_directory(args.bridge, {".keep", LOCK})
            _check_new_save_dir(args.new_save_dir)
        with _lock_bridge(args.bridge):
            bridge = OfflineBridge(args.bridge, _read_json(args.plan), args.run_id, args.new_save_dir)
            print(f"Bridge ready for {len(bridge.assignments)} changed checks. Ctrl+C stops the bridge.", flush=True)
            while True:
                count = bridge.poll()
                if count:
                    print(f"Queued {count} replacements, {len(bridge.queue)} in this run.", flush=True)
                if args.once:
                    return
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("Bridge stopped. Keep these files with the same save and run ID.")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
