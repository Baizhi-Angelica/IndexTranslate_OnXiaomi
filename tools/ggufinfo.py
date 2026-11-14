#!/usr/bin/env python3
"""Dump GGUF header metadata (no dependencies)."""
import struct
import sys

FMT = {0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2), 4: ("I", 4),
       5: ("i", 4), 6: ("f", 4), 7: ("?", 1), 10: ("Q", 8), 11: ("q", 8),
       12: ("d", 8)}


def rd(f, n):
    b = f.read(n)
    if len(b) != n:
        raise EOFError
    return b


def r_u32(f):
    return struct.unpack("<I", rd(f, 4))[0]


def r_u64(f):
    return struct.unpack("<Q", rd(f, 8))[0]


def r_str(f):
    n = r_u64(f)
    return rd(f, n).decode("utf-8", "replace")


def r_val(f, t):
    if t in FMT:
        fmt, sz = FMT[t]
        return struct.unpack("<" + fmt, rd(f, sz))[0]
    if t == 8:
        return r_str(f)
    if t == 9:
        et = r_u32(f)
        n = r_u64(f)
        if n > 100000:
            return f"<array of {n} type {et} (skipped)>"
        return [r_val(f, et) for _ in range(n)]
    raise ValueError(f"unknown type {t}")


def main(path):
    with open(path, "rb") as f:
        if rd(f, 4) != b"GGUF":
            print("not a gguf file")
            return 1
        ver = r_u32(f)
        n_tensors = r_u64(f)
        n_kv = r_u64(f)
        print(f"# file={path} version={ver} tensors={n_tensors} kv={n_kv}")
        for _ in range(n_kv):
            k = r_str(f)
            t = r_u32(f)
            v = r_val(f, t)
            if isinstance(v, str) and len(v) > 300:
                v = v[:300] + "..."
            print(f"{k} = {v!r}")
        names = []
        for _ in range(n_tensors):
            name = r_str(f)
            nd = r_u32(f)
            dims = [r_u64(f) for _ in range(nd)]
            tt = r_u32(f)
            off = r_u64(f)
            names.append((name, dims, tt, off))
        print(f"# tensor names ({len(names)}):")
        for n, d, tt, off in names[:80]:
            print(f"  {n} dims={d} type={tt}")
        if len(names) > 80:
            print(f"  ... and {len(names)-80} more")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
