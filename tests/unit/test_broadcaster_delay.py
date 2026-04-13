from __future__ import annotations

import asyncio
import random

import pytest


def compute_delay(base: int, randomize: bool, rmin: int, rmax: int) -> int:
    if randomize:
        return random.randint(rmin, rmax)
    return base


def test_delay_no_randomize() -> None:
    delay = compute_delay(5, False, 3, 10)
    assert delay == 5


def test_delay_randomize_in_range() -> None:
    for _ in range(50):
        delay = compute_delay(5, True, 3, 10)
        assert 3 <= delay <= 10


def test_delay_randomize_bounds() -> None:
    delays = {compute_delay(5, True, 7, 7) for _ in range(10)}
    assert delays == {7}


class FakePost:
    def __init__(self, post_type: str) -> None:
        self.type = type("PostType", (), {"value": post_type})()
        self.source_message_id = 1
        self.source_chat_id = -100
        self.text = "Hello"
        self.text_entities = None
        self.media_file_id = "FILEID"


def test_fake_post_text_type() -> None:
    post = FakePost("text")
    assert post.type.value == "text"


def test_fake_post_forwarded_type() -> None:
    post = FakePost("forwarded")
    assert post.source_message_id == 1
