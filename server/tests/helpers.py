"""여러 테스트에서 쓰는 준비 도우미."""

from __future__ import annotations

from tests.test_pipeline import processed_space


def ready_space(client) -> tuple[dict, list[dict]]:
    """fixture 통화를 올리고, '목소리 2'(엄마)를 그 사람으로 고른 공간."""
    space, asset = processed_space(client)
    sid = space["id"]
    review = client.get(f"/api/spaces/{sid}/voices").json()
    child, mom = review["assets"][0]["speakers"]
    client.patch(f"/api/spaces/{sid}/speakers/{mom['id']}", json={"role": "person"})
    client.patch(f"/api/spaces/{sid}/speakers/{child['id']}", json={"role": "other"})
    clips = client.get(f"/api/spaces/{sid}/assets/{asset['id']}/clips").json()["clips"]
    return space, clips
