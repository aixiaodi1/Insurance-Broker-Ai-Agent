import json

import redis


class ThreadStateStore:
    def __init__(self, redis_url: str) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)

    def _key(self, user_id: str, thread_id: str, collection: str) -> str:
        return f"thread_state:{user_id}:{thread_id}:{collection}"

    def get_state(
        self, user_id: str, thread_id: str, collection: str
    ) -> dict | None:
        key = self._key(user_id, thread_id, collection)
        data = self._redis.get(key)
        if data is None:
            return None
        self._redis.expire(key, 86400)
        return json.loads(data)

    def save_state(
        self, user_id: str, thread_id: str, collection: str, state: dict
    ) -> None:
        key = self._key(user_id, thread_id, collection)
        self._redis.setex(key, 86400, json.dumps(state, ensure_ascii=False, default=str))

    def delete_state(
        self, user_id: str, thread_id: str, collection: str
    ) -> None:
        key = self._key(user_id, thread_id, collection)
        self._redis.delete(key)
