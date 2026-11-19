"""Copy cooked FNames together with their engine-provided hash and encoding."""

from struct import pack
from integrations.weapons.zen import name_batch


class NamePool:
    def __init__(self, data, start=60):
        self.names, self.end = name_batch(data, start)
        self.version = data[start + 8 : start + 16]
        hashes = start + 16
        headers = hashes + 8 * len(self.names)
        pos = headers + 2 * len(self.names)
        self.entries = []
        for index in range(len(self.names)):
            hashed = data[hashes + 8 * index : hashes + 8 * index + 8]
            header = data[headers + 2 * index : headers + 2 * index + 2]
            size = int.from_bytes(header, "big")
            width = (size & 0x7FFF) * (2 if size & 0x8000 else 1)
            self.entries.append((hashed, header, data[pos : pos + width]))
            pos += width

    def append_from(self, source, index):
        name = source.names[index]
        if name in self.names:
            return self.names.index(name)
        if source.version != self.version:
            raise ValueError("Incompatible Zen name hashes")
        self.names.append(name)
        self.entries.append(source.entries[index])
        return len(self.names) - 1

    def copy(self, source, name, *, replace=None):
        index = source.names.index(name)
        if replace is None:
            return self.append_from(source, index)
        if self.version != source.version:
            raise ValueError("Incompatible Zen name hashes")
        target = self.names.index(replace)
        self.names[target] = name
        self.entries[target] = source.entries[index]
        return target

    def serialize(self):
        hashes, headers, texts = (
            b"".join(part) for part in zip(*self.entries, strict=True)
        )
        return (
            pack("<II", len(self.entries), len(texts))
            + self.version
            + hashes
            + headers
            + texts
        )
