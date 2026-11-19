import struct
import unittest

from pbzmod.container import subset_header


MAGIC = 0x496F436E
VERSION = 5


def build_header(entries):
    """Serialize a small UE package store for an overlay regression test."""
    ids = sorted(entries)
    records = bytearray(len(ids) * 16)
    payloads = bytearray()
    for i, id_ in enumerate(ids):
        imports, shaders = entries[id_]
        for offset, count, payload in (
            (i * 16, len(imports), struct.pack(f"<{len(imports)}Q", *imports)),
            (i * 16 + 8, len(shaders), b"".join(shaders)),
        ):
            if count:
                struct.pack_into("<II", records, offset, count, len(records) + len(payloads) - offset)
                payloads.extend(payload)
    data = records + payloads
    return (
        struct.pack("<IIQI", MAGIC, VERSION, 91, len(ids))
        + struct.pack(f"<{len(ids)}Q", *ids)
        + struct.pack("<I", len(data))
        + data
    )


def read_dependencies(blob, row):
    row_offset = 16 * row
    imports_count, imports_offset, shader_count, shader_offset = struct.unpack_from("<IIII", blob, row_offset)
    imports = struct.unpack_from(f"<{imports_count}Q", blob, row_offset + imports_offset)
    first_shader = row_offset + 8 + shader_offset
    shaders = tuple(blob[pos:pos + 20] for pos in range(first_shader, first_shader + 20 * shader_count, 20))
    return imports, shaders


class ContainerHeaderTest(unittest.TestCase):
    def test_dependency_overrides_preserve_original_shader_arrays(self):
        alpha = bytes(range(20))
        beta = bytes(range(20, 40))
        gamma = bytes(range(40, 60))
        delta = bytes(range(60, 80))
        original = build_header({
            11: ((55,), (alpha,)),
            22: ((11, 88), (beta, gamma)),
            33: ((11, 22), (delta,)),
        })
        result = subset_header(original, [22, 33], 97, {22: [77, 99, 101], 11: [63]})
        self.assertEqual(struct.unpack_from("<IIQI", result), (MAGIC, VERSION, 97, 2))
        self.assertEqual(struct.unpack_from("<2Q", result, 20), (22, 33))
        blob_size, = struct.unpack_from("<I", result, 36)
        blob = result[40:40 + blob_size]
        self.assertEqual(read_dependencies(blob, 0), ((77, 99, 101), (beta, gamma)))
        self.assertEqual(read_dependencies(blob, 1), ((11, 22), (delta,)))
        self.assertNotIn(alpha, blob)

    def test_empty_dependency_override_preserves_shaders(self):
        shader = b"\xf0" * 20
        original = build_header({10: ((22, 33), (shader,))})
        result = subset_header(original, [10], 97, {10: []})
        blob_size, = struct.unpack_from("<I", result, 28)
        self.assertEqual(read_dependencies(result[32:32 + blob_size], 0), ((), (shader,)))


if __name__ == "__main__":
    unittest.main()
