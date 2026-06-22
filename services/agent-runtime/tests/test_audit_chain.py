"""Hermetic test of the tamper-evident audit hash-chain. [paper §6.1]"""
from __future__ import annotations

import importlib.util
from pathlib import Path

# Load the feedback-loop collector module directly (it's a separate service).
_COLLECTOR = (Path(__file__).resolve().parents[3] / "services" / "feedback-loop"
              / "app" / "collector.py")
_spec = importlib.util.spec_from_file_location("vcl_collector", _COLLECTOR)
collector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collector)


def test_chain_is_deterministic():
    h1 = collector.chain_hash(collector.GENESIS, '{"a":1}')
    h2 = collector.chain_hash(collector.GENESIS, '{"a":1}')
    assert h1 == h2 and len(h1) == 64


def test_chain_links_depend_on_prev_and_payload():
    a = collector.chain_hash(collector.GENESIS, '{"step":1}')
    b = collector.chain_hash(a, '{"step":2}')
    # changing the previous hash or the payload changes the link
    assert collector.chain_hash("0" * 64, '{"step":2}') != b
    assert collector.chain_hash(a, '{"step":2-tampered}') != b


def test_verify_rows_detects_tampering():
    def link(prev, payload):
        return {"payload": payload, "prev_hash": prev,
                "entry_hash": collector.chain_hash(prev, payload)}

    g = collector.GENESIS
    r1 = link(g, '{"s":1}')
    r2 = link(r1["entry_hash"], '{"s":2}')
    r3 = link(r2["entry_hash"], '{"s":3}')
    assert collector._verify_rows([r1, r2, r3])["valid"] is True

    # tamper with the middle event's payload without recomputing downstream hashes
    r2_tampered = {**r2, "payload": '{"s":2,"evil":true}'}
    bad = collector._verify_rows([r1, r2_tampered, r3])
    assert bad["valid"] is False
    assert bad["broken_at_step"] == 2
