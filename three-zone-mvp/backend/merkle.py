"""Deterministic SHA-256 Merkle tree for settlement inclusion proofs."""

from __future__ import annotations

import hashlib
import json


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_canonical(obj) -> str:
    blob = json.dumps(obj, separators=(",", ":"), sort_keys=True)
    return sha256_hex(blob)


def _pair(left: str, right: str) -> str:
    return sha256_hex(bytes.fromhex(left) + bytes.fromhex(right))


def merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return sha256_hex(b"")
    layer = list(leaves)
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        nxt = []
        for i in range(0, len(layer), 2):
            nxt.append(_pair(layer[i], layer[i + 1]))
        layer = nxt
    return layer[0]


def merkle_proof(leaves: list[str], index: int) -> list[dict]:
    if not leaves:
        return []
    layer = list(leaves)
    idx = index
    proof = []
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        pair_index = idx ^ 1
        sibling = layer[pair_index]
        proof.append({"sibling": sibling, "position": "left" if pair_index < idx else "right"})
        nxt = []
        for i in range(0, len(layer), 2):
            nxt.append(_pair(layer[i], layer[i + 1]))
        layer = nxt
        idx //= 2
    return proof


def verify_proof(leaf: str, proof: list[dict], root: str) -> bool:
    current = leaf
    for step in proof:
        sib = step["sibling"]
        if step.get("position") == "left":
            current = _pair(sib, current)
        else:
            current = _pair(current, sib)
    return current == root
