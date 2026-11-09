"""Reads the facts the linker and the engines act on out of wasm objects, archives and modules.

    python3 harness/wasmfile.py marks FILE...   the target_features verdict of every object
    python3 harness/wasmfile.py memory FILE     whether the module's memory is shared
"""

import sys


def leb(data, i):
    """Decodes the unsigned LEB128 at `i`, returning the value and the next offset."""
    value = shift = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, i


def name(data, i):
    """Decodes the length-prefixed UTF-8 name at `i`, returning it and the next offset."""
    length, i = leb(data, i)
    return data[i:i + length].decode(), i + length


def sections(data):
    """Yields the id and the payload bounds of every section of a wasm binary."""
    i = 8
    while i < len(data):
        section, i = data[i], i + 1
        size, i = leb(data, i)
        yield section, i, i + size
        i += size


def target_features(data):
    """The `target_features` entries of a wasm object such as `-shared-mem`, None for non-wasm data."""
    if data[:4] != b"\0asm":
        return None
    for section, start, _ in sections(data):
        if section != 0:
            continue
        title, i = name(data, start)
        if title != "target_features":
            continue
        count, i = leb(data, i)
        features = []
        for _ in range(count):
            prefix, i = chr(data[i]), i + 1
            feature, i = name(data, i)
            features.append(prefix + feature)
        return features
    return []


def members(data):
    """Yields the name and bytes of every member of an `ar` archive such as an rlib."""
    i, long_names = 8, b""
    while i + 60 <= len(data):
        header, i = data[i:i + 60], i + 60
        member = header[:16].decode().strip()
        size = int(header[48:58].decode().strip())
        body, i = data[i:i + size], i + size + (size & 1)
        if member == "//":
            long_names = body
            continue
        if member.startswith("/") and member[1:].isdigit():
            offset = int(member[1:])
            member = long_names[offset:long_names.index(b"\n", offset)].decode()
        yield member.rstrip("/"), body


def objects(path):
    """Yields the name and bytes of every wasm object in an archive or object file."""
    data = open(path, "rb").read()
    items = members(data) if data[:8] == b"!<arch>\n" else [(path, data)]
    for member, body in items:
        if member.endswith(".o") and body[:4] == b"\0asm":
            yield member, body


def mark(features):
    """How the linker treats an object in a module with shared memory."""
    if "-shared-mem" in features:
        return "-shared-mem"
    if "+atomics" in features:
        return "+atomics"
    return "unmarked"


def memory_limits_flags(data):
    """The limits flags byte of the module's memory, imported or defined, bit 1 meaning shared."""
    for section, start, _ in sections(data):
        if section == 2:
            count, i = leb(data, start)
            for _ in range(count):
                _, i = name(data, i)
                _, i = name(data, i)
                kind, i = data[i], i + 1
                if kind == 0:
                    _, i = leb(data, i)
                elif kind == 1:
                    flags, i = data[i + 1], i + 2
                    _, i = leb(data, i)
                    if flags & 1:
                        _, i = leb(data, i)
                elif kind == 2:
                    return data[i]
                elif kind == 3:
                    i += 2
                else:
                    raise ValueError(f"import kind {kind}")
        if section == 5:
            count, i = leb(data, start)
            if count:
                return data[i]
    return None


def main(argv):
    command, *paths = argv
    if command == "marks":
        for path in paths:
            for member, body in objects(path):
                print(mark(target_features(body)), member)
    elif command == "memory":
        flags = memory_limits_flags(open(paths[0], "rb").read())
        print("shared" if flags is not None and flags & 2 else "not shared")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
