from typing import Optional, List
import logging
import redis.asyncio as aioredis

logger = logging.getLogger("imyme-redis-lua")

class RedisLuaScripts:
    def __init__(self, redis_client):
        """
        Initializes Lua scripts for Challenge Mode (Phase 2).
        Requires an active aioredis client.
        """
        self.redis = redis_client
        self._push_and_check_script = None

    async def init_scripts(self):
        """
        Loads the Lua script into Redis. Call this during app startup.
        """
        # Lua script: 
        # 1. Pushes the merged_array into the target level list.
        # 2. Checks if the list length >= 2.
        # 3. If yes, pops 2 elements from the list and returns them so the worker can publish the next mission.
        # 4. If no, returns nil.
        # KEYS[1]: The Redis list key (e.g., pairs:job:999:level:1)
        # ARGV[1]: The serialized JSON array string
        push_check_lua = """
        redis.call('RPUSH', KEYS[1], ARGV[1])
        local len = redis.call('LLEN', KEYS[1])
        if len >= 2 then
            local p1 = redis.call('LPOP', KEYS[1])
            local p2 = redis.call('LPOP', KEYS[1])
            return {p1, p2}
        else
            return nil
        end
        """
        self._push_and_check_script = self.redis.register_script(push_check_lua)
        logger.info("Challenge Mode Lua scripts registered.")

    async def push_and_check_pairs(self, list_key: str, serialized_array: str, ttl: int = 7200) -> Optional[List[str]]:
        """
        Atomically pushes a merged array into the level list and pops if a pair is formed.
        Also guarantees TTL is applied to the key to prevent memory leaks (Infrastructure Checkpoint).
        """
        if not self._push_and_check_script:
            raise RuntimeError("Lua scripts not initialized. Call init_scripts() first.")

        # Ensure TTL is set on the key before or during the process.
        # In a strict environment, TTL can be set inside the Lua script, 
        # but for simplicity, we do it in python if it's the first element.
        # We will use Lua to ensure atomicity.

        lua_with_ttl = """
        local key = KEYS[1]
        local data = ARGV[1]
        local ttl = tonumber(ARGV[2])
        
        -- Push data
        redis.call('RPUSH', key, data)
        
        -- Set TTL if it doesn't have one
        local current_ttl = redis.call('TTL', key)
        if current_ttl == -1 or current_ttl == -2 then
            redis.call('EXPIRE', key, ttl)
        end
        
        -- Check and Pop
        local len = redis.call('LLEN', key)
        if len >= 2 then
            local p1 = redis.call('LPOP', key)
            local p2 = redis.call('LPOP', key)
            return {p1, p2}
        else
            return {}
        end
        """
        
        # Override the simple script with the robust TTL embedded one
        script = self.redis.register_script(lua_with_ttl)
        
        try:
            result = await script(keys=[list_key], args=[serialized_array, str(ttl)])
            if result and len(result) == 2:
                # result is a list of two string-serialized arrays
                return [r.decode("utf-8") if isinstance(r, bytes) else r for r in result]
            return None
        except Exception as e:
            logger.error(f"Error executing push_and_check_pairs Lua script: {e}")
            raise

# A global instance placeholder, needs to be initialized with the actual redis client in main.py or dependencies
# redis_lua_manager = RedisLuaScripts(redis_client)
