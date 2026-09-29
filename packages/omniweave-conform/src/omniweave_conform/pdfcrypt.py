"""PDF encryption for the paired-damage suite's `encrypt` Injector. ADR-15 D15.6.

13:1283's `encrypt` *"applies owner-password encryption"*, and nothing in this workspace can:
pypdfium2 reads encrypted files and writes none, and pypdf and pikepdf are not dependencies (the
kit is `omniweave-core`, `omniweave-ports` and `pytest`). So this module writes it, from ISO 32000-1
§7.6.3's standard security handler, with nothing but `hashlib`:

- **revision 3, RC4 with a 128-bit key** (`/V 2 /R 3 /Length 128`): Algorithm 2 for the file key,
  3 for `/O`, 5 for `/U`, and 1 for each object's key. The oldest handler pdfium still opens, and
  the only one whose cipher the standard library can express, since AES is not in it;
- **every stream and every string of every object** is encrypted under its object's key, as
  §7.6.2 requires. A document whose strings stayed clear would still open, and would be a document
  no real encrypting producer writes;
- **both passwords.** A user password makes the file unreadable without it, which is what the
  Injector needs. An empty one gives an owner-password-only file, which opens with none: that is
  ADR-15 D15.2's case, the permission-restricted PDF the build must go on reading with no setup.

**The shape it takes is the shape it refuses.** A classic xref table, objects in the body and not
in object streams, no cross-reference stream: the reference-corpus generator's PDFs and the
`omniweave-pdf` fixtures. Anything else raises `ValueError` naming what it found, because an
encryptor that guessed at a compressed object's strings would write a file no reader opens and call
it damage.

13:1283 also says *"to n pages"*. PDF encryption is a property of the document: there is no
per-page key, so *"n pages"* has no form, and D15.6 rules the whole document.
"""

from __future__ import annotations

import hashlib
import re
import struct
from typing import Final

__all__ = ["PAD", "PERMISSIONS", "encrypt_pdf"]

PAD: Final[bytes] = bytes.fromhex(
    "28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A"
)
"""ISO 32000-1 §7.6.3.3 Algorithm 2 step a's padding string."""

PERMISSIONS: Final[int] = -3904
"""`/P`: printing and copying denied, which is what an owner password usually guards."""

_OBJECT: Final = re.compile(rb"(\d+) (\d+) obj\s(.*?)\sendobj", re.DOTALL)
_ROOT: Final = re.compile(rb"/Root\s+(\d+)\s+(\d+)\s+R")
_INFO: Final = re.compile(rb"/Info\s+(\d+)\s+(\d+)\s+R")
_ID: Final = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>")
_BACKSLASH, _OPEN, _CLOSE, _ANGLE = 0x5C, 0x28, 0x29, 0x3C
_OCTAL: Final = range(0x30, 0x38)
_ESCAPES: Final[dict[int, int]] = {
    ord("n"): 0x0A,
    ord("r"): 0x0D,
    ord("t"): 0x09,
    ord("b"): 0x08,
    ord("f"): 0x0C,
}


def _rc4(key: bytes, data: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    out = bytearray(len(data))
    i = j = 0
    for n, byte in enumerate(data):
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        out[n] = byte ^ state[(state[i] + state[j]) % 256]
    return bytes(out)


def _padded(password: bytes) -> bytes:
    return (password + PAD)[:32]


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data, usedforsecurity=False).digest()


def _owner_entry(owner: bytes, user: bytes) -> bytes:
    """Algorithm 3, revision 3."""
    digest = _md5(_padded(owner))
    for _ in range(50):
        digest = _md5(digest)
    key = digest[:16]
    out = _rc4(key, _padded(user))
    for step in range(1, 20):
        out = _rc4(bytes(byte ^ step for byte in key), out)
    return out


def _file_key(user: bytes, owner_entry: bytes, doc_id: bytes) -> bytes:
    """Algorithm 2, revision 3, a 16-byte key."""
    digest = _md5(_padded(user) + owner_entry + struct.pack("<i", PERMISSIONS) + doc_id)
    for _ in range(50):
        digest = _md5(digest[:16])
    return digest[:16]


def _user_entry(key: bytes, doc_id: bytes) -> bytes:
    """Algorithm 5, revision 3: sixteen significant bytes, then sixteen of padding."""
    out = _rc4(key, _md5(PAD + doc_id))
    for step in range(1, 20):
        out = _rc4(bytes(byte ^ step for byte in key), out)
    return out + bytes(16)


def _object_key(key: bytes, number: int, generation: int) -> bytes:
    """Algorithm 1: the file key, the object number and the generation, hashed and cut."""
    salt = number.to_bytes(3, "little") + generation.to_bytes(2, "little")
    return _md5(key + salt)[: min(16, len(key) + 5)]


def _literal(body: bytes, start: int) -> tuple[bytes, int]:
    """The bytes of the literal string opening at `start`, and the index just past its `)`."""
    out = bytearray()
    depth, i = 1, start + 1
    while depth:
        byte = body[i]
        if byte == _BACKSLASH:
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
            elif nxt in _OCTAL:
                digits = re.match(rb"[0-7]{1,3}", body[i + 1 : i + 4])
                assert digits is not None
                out.append(int(digits.group(), 8) & 0xFF)
                i += 1 + len(digits.group())
            elif nxt in b"\r\n":
                i += 3 if body[i + 1 : i + 3] == b"\r\n" else 2
            else:
                out.append(nxt)
                i += 2
            continue
        if byte == _OPEN:
            depth += 1
        elif byte == _CLOSE:
            depth -= 1
            if not depth:
                break
        out.append(byte)
        i += 1
    return bytes(out), i + 1


def _strings(body: bytes, key: bytes) -> bytes:
    """`body` with every literal and hex string encrypted under `key`, written back as hex."""
    out = bytearray()
    i = 0
    while i < len(body):
        byte = body[i]
        if byte == _OPEN:
            raw, i = _literal(body, i)
            out += b"<" + _rc4(key, raw).hex().encode() + b">"
            continue
        if byte == _ANGLE and body[i + 1 : i + 2] != b"<":
            end = body.index(b">", i)
            hexed = re.sub(rb"\s", b"", body[i + 1 : end])
            raw = bytes.fromhex((hexed + b"0" * (len(hexed) % 2)).decode())
            out += b"<" + _rc4(key, raw).hex().encode() + b">"
            i = end + 1
            continue
        if byte == _ANGLE:  # `<<`: copy both, so the second is not read as a hex string
            out += body[i : i + 2]
            i += 2
            continue
        out.append(byte)
        i += 1
    return bytes(out)


def _encrypt_object(body: bytes, key: bytes) -> bytes:
    """One object: a stream's data under `key`, and every string outside the data."""
    if b"stream" not in body or not re.search(rb">>\s*stream\r?\n", body):
        return _strings(body, key)
    opened = re.search(rb">>\s*stream\r?\n", body)
    assert opened is not None
    head, rest = body[: opened.end()], body[opened.end() :]
    closed = rest.rindex(b"endstream")
    data, tail = rest[:closed], rest[closed:]
    newline = b"\r\n" if data.endswith(b"\r\n") else b"\n" if data.endswith(b"\n") else b""
    length = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", head)
    if length is not None and int(length.group(1)) <= len(data):
        data, newline = data[: int(length.group(1))], data[int(length.group(1)) :]
    return _strings(head, key) + _rc4(key, data) + newline + tail


def encrypt_pdf(data: bytes, *, user_password: str, owner_password: str) -> bytes:
    """`data` re-written under the standard security handler, revision 3, RC4-128.

    `user_password=""` gives an owner-password-only file, which opens with no password. Raises
    `ValueError` for a PDF this does not write: an object stream, a cross-reference stream, one
    already encrypted, or one with no classic xref, root or objects.
    """
    for marker, what in (
        (b"/ObjStm", "an object stream"),
        (b"/XRef", "a cross-reference stream"),
        (b"/Encrypt", "an encryption dictionary already"),
    ):
        if marker in data:
            msg = f"encrypt_pdf writes classic-xref PDFs, and this one has {what}"
            raise ValueError(msg)
    if not data.startswith(b"%PDF-") or b"\nxref" not in data:
        msg = "encrypt_pdf needs a PDF with a classic xref table"
        raise ValueError(msg)
    header_end = data.index(b"\n", data.index(b"\n") + 1) + 1 if data[9:10] == b"%" else 9
    objects = {
        int(match.group(1)): (int(match.group(2)), match.group(3))
        for match in _OBJECT.finditer(data)
    }
    trailer = data[data.rindex(b"trailer") :]
    root = _ROOT.search(trailer)
    if not objects or root is None:
        msg = "encrypt_pdf found no objects, or no /Root in the trailer"
        raise ValueError(msg)
    found_id = _ID.search(trailer)
    doc_id = bytes.fromhex(found_id.group(1).decode()) if found_id else _md5(data)
    user, owner = (
        user_password.encode("latin-1"),
        (owner_password or user_password).encode("latin-1"),
    )
    owner_entry = _owner_entry(owner, user)
    key = _file_key(user, owner_entry, doc_id)

    out = bytearray(data[:header_end])
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        generation, body = objects[number]
        offsets[number] = len(out)
        encrypted = _encrypt_object(body, _object_key(key, number, generation))
        out += f"{number} {generation} obj\n".encode() + encrypted + b"\nendobj\n"
    handler = max(objects) + 1
    offsets[handler] = len(out)
    out += (
        f"{handler} 0 obj\n<< /Filter /Standard /V 2 /R 3 /Length 128 /P {PERMISSIONS} "
        f"/O <{owner_entry.hex()}> /U <{_user_entry(key, doc_id).hex()}> >>\nendobj\n"
    ).encode()
    xref = len(out)
    size = handler + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        if number in offsets:
            generation = objects[number][0] if number in objects else 0
            out += f"{offsets[number]:010d} {generation:05d} n \n".encode()
        else:
            out += b"0000000000 65535 f \n"
    info = _INFO.search(trailer)
    info_ref = f" /Info {info.group(1).decode()} {info.group(2).decode()} R" if info else ""
    out += (
        f"trailer\n<< /Size {size} /Root {root.group(1).decode()} {root.group(2).decode()} R"
        f"{info_ref} /Encrypt {handler} 0 R /ID [<{doc_id.hex()}> <{doc_id.hex()}>] >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)
