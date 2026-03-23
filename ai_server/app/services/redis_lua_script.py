"""
Challenge Mode Redis Lua Scripts (Phase 2: 설계.md 기반 리팩토링)

스마트 Lua 스크립트:
 - PAIR: 리스트에 2개 이상 쌓이면 2개를 팝하여 반환
 - PROMOTE: 해당 레벨의 마지막 노드인데 짝이 없는 경우 (홀수 부전승)
 - WAIT: 아직 짝꿍이 도착하지 않음
"""

from typing import List, Tuple
import logging
import redis.asyncio as aioredis

logger = logging.getLogger("imyme-redis-lua")


class RedisLuaScripts:
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self._smart_push_script = None

    async def init_scripts(self):
        """서버 시작 시 Lua 스크립트를 Redis에 로드합니다."""
        # KEYS[1] = level list key  (예: pairs:job:{id}:level:1)
        # KEYS[2] = arrived counter (예: pairs:job:{id}:level:1:arrived)
        # ARGV[1] = serialized merged array (JSON string)
        # ARGV[2] = TTL (seconds)
        # ARGV[3] = expected_count (이 레벨에 도달해야 할 총 노드 수)
        #
        # Returns:
        #   {"PAIR", elem1, elem2}  -> 짝이 맞아서 병합 대상 2개 반환
        #   {"PROMOTE", elem1}      -> 홀수 부전승: 이 레벨 마지막 노드
        #   {"WAIT"}                -> 짝꿍을 더 기다려야 함
        smart_lua = """
        local list_key      = KEYS[1]
        local arrived_key   = KEYS[2]
        local data           = ARGV[1]
        local ttl            = tonumber(ARGV[2])
        local expected_count = tonumber(ARGV[3])

        -- 1. Push data into the level list
        redis.call('RPUSH', list_key, data)

        -- 2. TTL 설정 (최초 1회)
        local cur_ttl = redis.call('TTL', list_key)
        if cur_ttl == -1 or cur_ttl == -2 then
            redis.call('EXPIRE', list_key, ttl)
        end

        -- 3. 도달 카운터 증가 (이 레벨에 몇 개의 노드가 도착했는지)
        local arrived = redis.call('INCR', arrived_key)
        redis.call('EXPIRE', arrived_key, ttl)

        -- 4. 리스트 길이 확인
        local list_len = redis.call('LLEN', list_key)

        -- 5. 분기 로직
        if list_len >= 2 then
            -- 짝이 맞음: 2개 꺼내서 반환
            local p1 = redis.call('LPOP', list_key)
            local p2 = redis.call('LPOP', list_key)
            return {"PAIR", p1, p2}
        elseif arrived >= expected_count and list_len == 1 then
            -- 이 레벨의 마지막 노드인데 짝이 없음 -> 부전승(Promote)
            local lone = redis.call('LPOP', list_key)
            return {"PROMOTE", lone}
        else
            -- 아직 짝꿍 대기 중
            return {"WAIT"}
        end
        """
        self._smart_push_script = self.redis.register_script(smart_lua)
        logger.info("Challenge Mode Smart Lua scripts registered.")

    async def push_and_route(
        self,
        list_key: str,
        arrived_key: str,
        serialized_array: str,
        expected_count: int,
        ttl: int = 7200,
    ) -> Tuple[str, List[str]]:
        """
        원자적으로 병합 결과를 레벨 리스트에 넣고 다음 행동을 결정합니다.

        Returns:
            ("PAIR", [arr1_json, arr2_json])   - 짝이 맞아 병합할 2개 반환
            ("PROMOTE", [lone_arr_json])       - 홀수 부전승, 승급 대상 1개 반환
            ("WAIT", [])                       - 짝꿍 대기 중
        """
        if not self._smart_push_script:
            raise RuntimeError(
                "Lua scripts not initialized. Call init_scripts() first."
            )

        try:
            result = await self._smart_push_script(
                keys=[list_key, arrived_key],
                args=[serialized_array, str(ttl), str(expected_count)],
            )

            # result는 list[bytes] 형태
            decoded = [r.decode("utf-8") if isinstance(r, bytes) else r for r in result]
            action = decoded[0]
            data = decoded[1:]
            return action, data

        except Exception as e:
            logger.error(f"Error executing smart Lua script: {e}")
            raise
