"""Read the property schemas in the pinned, uncompressed USMAP v4."""

import struct
from pathlib import Path


def load_usmap(path):
    return parse_usmap(Path(path).read_bytes())


def parse_usmap(data):
    if data[:8] != bytes.fromhex("c430040000000000"):
        raise ValueError("Unsupported .usmap version")
    pos = 16

    def read(type_):
        nonlocal pos
        size = struct.calcsize(type_)
        result = struct.unpack_from(type_, data, pos)[0]
        pos += size
        return result

    names = []
    for _ in range(read("<I")):
        n = read("<H")
        names.append(data[pos : pos + n].decode())
        pos += n
    for _ in range(read("<I")):
        enum = read("<i")
        size = read("<H")
        pos += size * 12
    count = read("<I")

    def name():
        i = read("<i")
        return None if i == -1 else names[i]

    def prop():
        n = read("<B")
        if n == 26:
            return (n, prop(), name())
        if n == 9:
            return (n, name())
        if n in (8, 25, 28):
            return (n, prop())
        if n == 24:
            return (n, prop(), prop())
        return (n,)

    schemas = {}
    for _ in range(count):
        nm, super_ = name(), name()
        total, n = read("<H"), read("<H")
        fields = {}
        for _ in range(n):
            index, array_dim = read("<H"), read("<B")
            property_name = name()
            kind = prop()
            for i in range(array_dim):
                fields[index + i] = (property_name, kind)
        schemas[nm] = (super_, total, fields)
    return schemas
