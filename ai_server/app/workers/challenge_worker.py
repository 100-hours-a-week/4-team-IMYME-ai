import json
import logging
from aio_pika.abc import AbstractIncomingMessage

from app.core.config import settings
from app.services.rabbitmq_service import rabbitmq_service
from app.services.pairs_service import pairs_service
from app.services.redis_lua_script import RedisLuaScripts
# Assuming redis client init will be provided or injected. Here we mock a get_redis()
import redis.asyncio as aioredis

logger = logging.getLogger("imyme-challenge-worker")

# Define global redis client 
redis_client = None
redis_lua = None

async def init_redis_for_worker():
    global redis_client, redis_lua
    if redis_client is None:
        redis_client = await aioredis.from_url(settings.REDIS_URL)
        redis_lua = RedisLuaScripts(redis_client)
        await redis_lua.init_scripts()

async def process_challenge_evaluation(body: dict, message: AbstractIncomingMessage) -> None:
    """
    1. Receive {"job_id": "job:999", "level": L, "arr1": [...], "arr2": [...]}
    2. Merge via PAIRS-beam.
    3. Push to Redis level:L+1 using Lua Script.
    4. If the script pops a new pair (length reached 2), publish it to MQ for level L+1.
    5. If level:L+1 merged array length == 100, we're done! Publish completion.
    """
    job_id = body.get("job_id")
    level = body.get("level")
    arr1 = body.get("arr1")
    arr2 = body.get("arr2")

    if not all([job_id, level is not None, arr1, arr2]):
        logger.error(f"Invalid challenge MQ payload: {body}")
        return

    logger.info(f"Challenge Worker started for {job_id} at Level {level}. Merging len {len(arr1)} and {len(arr2)}")

    try:
        # 1. Evaluate and Merge
        merged_array = await pairs_service.merge_beam(arr1, arr2)
        
        # 2. Redis Push & Check Level Up (Atomic)
        next_level = level + 1
        redis_key = f"pairs:{job_id}:level:{next_level}"
        
        # TTL: 2 hours (7200s) infrastructure requirement
        serialized = json.dumps(merged_array, ensure_ascii=False)
        popped_pair = await redis_lua.push_and_check_pairs(redis_key, serialized, ttl=7200)

        # 3. Handle Lua Script Result
        if popped_pair and len(popped_pair) == 2:
            new_arr1 = json.loads(popped_pair[0])
            new_arr2 = json.loads(popped_pair[1])
            
            # Check for Final Completion (Length = 100)
            # Actually, if we pop two arrays and their combined size config is 100 
            # OR we just merged 100 and it's parked. Wait, the algorithm merges until 1 array of 100 is formed.
            # If we merged them, and the result length is 100:
            if len(new_arr1) + len(new_arr2) == 100:
                 # It means we're about to merge the last two halves. We need to evaluate them first!
                 # So we publish them to queue normally.
                 pass
                 
        # Let's check completion right after merge before pushing, or check the merged_array length.
        total_len = len(merged_array)
        if total_len == 100:
            logger.info(f"🏆 {job_id} ranking completed! Final length 100 reached.")
            
            # Save the final array to the final target key gracefully 
            # (already pushed to level N, but lets mark a specific completed key)
            final_key = f"pairs:{job_id}:completed"
            await redis_client.set(final_key, serialized, ex=7200)
            
            # Publish bare-minimum completion message to MQ 
            completion_msg = {
                "job_id": job_id,
                "status": "COMPLETED",
                "redis_key": final_key
            }
            await rabbitmq_service.publish(settings.CHALLENGE_COMPLETED_QUEUE, completion_msg)
            return

        # Not complete 100 yet, if we got a pair from the same level, publish next mission
        if popped_pair and len(popped_pair) == 2:
             new_arr1 = json.loads(popped_pair[0])
             new_arr2 = json.loads(popped_pair[1])
             
             next_mission = {
                 "job_id": job_id,
                 "level": next_level,
                 "arr1": new_arr1,
                 "arr2": new_arr2
             }
             logger.info(f"Level UP ⬆️ Publishing next match for {job_id} to Level {next_level} queue.")
             await rabbitmq_service.publish(settings.CHALLENGE_EVAL_QUEUE, next_mission)

    except Exception as e:
        logger.error(f"Error resolving challenge merge for {job_id}: {e}")
        raise

async def start_challenge_consumer() -> None:
    """
    Start the RabbitMQ consumer for Challenge Mode.
    Called from main.py lifespan.
    """
    await init_redis_for_worker()
    logger.info("Starting Challenge MQ Consumer...")
    await rabbitmq_service.consume(
        queue_name=settings.CHALLENGE_EVAL_QUEUE,
        callback=process_challenge_evaluation,
    )
