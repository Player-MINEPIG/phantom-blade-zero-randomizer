"""Read the unversioned properties of the supported ProjectPBZ weapon packages."""

from dataclasses import dataclass
from struct import calcsize, pack_into, unpack_from


@dataclass(frozen=True)
class Field:
    value: object
    start: int
    end: int


def name_batch(data, start=60):
    count, size = unpack_from("<II", data, start)
    if not 0 < count < 200000:
        raise ValueError("Unsupported Zen name batch size")
    headers = start + 16 + count * 8
    first = position = headers + count * 2
    names = []
    for index in range(count):
        header, = unpack_from(">H", data, headers + index * 2)
        wide = bool(header & 0x8000)
        width = (header & 0x7fff) * (2 if wide else 1)
        next_position = position + width
        names.append(data[position:next_position].decode("utf-16le" if wide else "utf-8"))
        position = next_position
    if position - first != size or position > len(data):
        raise ValueError("Inconsistent Zen name batch length")
    return names, position


class SingleExport:
    def __init__(self, data):
        unversioned, self.start = unpack_from("<II", data)
        self.entry, bundle = unpack_from("<II", data, 32)
        payload_offset, size = unpack_from("<QQ", data, self.entry)
        if (
            unversioned != 0
            or bundle - self.entry != 72
            or payload_offset != 0
            or self.start + size != len(data)
        ):
            raise ValueError("Expected one UE5.7 unversioned export spanning the rest of the package")
        self.data = data
        self.names, _ = name_batch(data)

    def reader(self, schemas):
        return AssetReader(self.data, self.names, schemas, self.start, len(self.data))

    def replace(self, replacements):
        result = bytearray(self.data)
        previous = len(result)
        for field, payload in sorted(replacements, key=lambda replacement: replacement[0].start, reverse=True):
            if not self.start <= field.start < field.end <= previous:
                raise ValueError("Overlapping fields or empty replacement field")
            result[field.start:field.end] = payload
            previous = field.start
        pack_into("<Q", result, self.entry + 8, len(result) - self.start)
        return bytes(result)


class AssetReader:
    # EPropertyType codes in the game build's USMAP.
    SCALARS = {0: "B", 1: "B", 2: "i", 3: "f", 4: "i", 7: "d", 14: "i", 18: "Q", 19: "I", 20: "H", 21: "q", 22: "h", 23: "b"}
    NATIVE_STRUCTS = {"LinearColor": "4f", "Vector": "3d", "Vector2D": "2d", "Rotator": "3d", "Transform": "10d", "Quat": "4d"}

    def __init__(self, data, names, schemas, start, end):
        self.data = data
        self.names = names
        self.schemas = schemas
        self.position = start
        self.end = end

    def read(self, fmt):
        size = calcsize("<" + fmt)
        if self.position + size > self.end:
            raise ValueError(f"Unexpected end of asset at {self.position:#x}")
        values = unpack_from("<" + fmt, self.data, self.position)
        self.position += size
        return values[0] if len(values) == 1 else values

    def count(self):
        value = self.read("i")
        if not 0 <= value <= self.end - self.position:
            raise ValueError(f"Invalid entry count {value} at {self.position - 4:#x}")
        return value

    def string(self):
        length = self.read("i")
        if length == 0:
            return ""
        raw = self.read(f"{abs(length) * (2 if length < 0 else 1)}s")
        return raw.decode("utf-16le" if length < 0 else "utf-8").rstrip("\0")

    def name(self):
        index, number = self.read("II")
        if index >= len(self.names):
            raise ValueError(f"Invalid name index {index} at {self.position - 8:#x}")
        name = self.names[index]
        return name if number == 0 else f"{name}_{number - 1}"

    def _text(self):
        _, history = self.read("IB")
        if history == 0:
            return self.string(), self.string(), self.string()
        if history == 255:
            if self.read("I") == 0:
                return None
            return self.string()
        raise ValueError(f"Unsupported FText history {history} at {self.position - 1:#x}")

    def read_value(self, kind):
        type_id = kind[0]
        if type_id in self.SCALARS:
            return self.read(self.SCALARS[type_id])
        if type_id == 5:
            return self.name()
        if type_id == 8:
            return [self.read_value(kind[1]) for _ in range(self.count())]
        if type_id == 9:
            struct_name = kind[1]
            if struct_name == "GameplayTagContainer":
                return [self.name() for _ in range(self.count())]
            if struct_name in self.NATIVE_STRUCTS:
                return self.read(self.NATIVE_STRUCTS[struct_name])
            return self.properties(struct_name)
        if type_id == 10:
            return self.string()
        if type_id == 11:
            return self._text()
        if type_id == 17:
            return self.name(), self.name(), self.string()
        if type_id == 24:
            removed = [self.read_value(kind[1]) for _ in range(self.count())]
            entries = [(self.read_value(kind[1]), self.read_value(kind[2])) for _ in range(self.count())]
            return removed, entries
        if type_id == 25:
            removed = [self.read_value(kind[1]) for _ in range(self.count())]
            entries = [self.read_value(kind[1]) for _ in range(self.count())]
            return removed, entries
        if type_id == 26:
            return self.read_value(kind[1])
        raise ValueError(f"Unsupported property type {kind!r} at {self.position:#x}")

    def _property_slots(self):
        slots = []
        index, mask_bits = 0, 0
        while True:
            packed = self.read("H")
            index += packed & 127
            count = packed >> 9
            masked = bool(packed & 128)
            slots.extend((index + offset, mask_bits + offset if masked else None) for offset in range(count))
            index += count
            if masked:
                mask_bits += count
            if packed & 256:
                break
        mask_size = (mask_bits + 7) // 8
        if mask_size > 2:
            mask_size = 4 * ((mask_bits + 31) // 32)
        mask = int.from_bytes(self.read(f"{mask_size}s"), "little") if mask_size else 0
        return [(index, bit is not None and bool(mask & (1 << bit))) for index, bit in slots]

    def _schema(self, name):
        fields = {}
        offset = 0
        while name is not None:
            if name not in self.schemas:
                raise ValueError(f"Missing schema for {name!r}")
            name, total, own_fields = self.schemas[name]
            fields.update((offset + index, field) for index, field in own_fields.items())
            offset += total
        return fields

    def properties(self, name):
        fields = {}
        slots = self._property_slots()
        schema = self._schema(name)
        for index, is_zero in slots:
            if index not in schema:
                raise ValueError(f"Unknown property {name}[{index}] at {self.position:#x}")
            field, kind = schema[index]
            start = self.position
            try:
                value = None if is_zero else self.read_value(kind)
            except (ValueError, KeyError) as error:
                raise ValueError(f"{name}.{field} at {start:#x}: {error}") from error
            fields[field] = Field(value, start, self.position)
        return fields
