import redis.asyncio as redis

# The Lua Script for atomic bidding.
# KEYS[1] = The Redis key for the current highest bid (e.g., "auction:123:price")
# KEYS[2] = The Redis key for the current winner's ID (e.g., "auction:123:winner")
# ARGV[1] = The new bid amount submitted by the user
# ARGV[2] = The user ID of the person bidding
LUA_BID_SCRIPT = """
local current_bid = tonumber(redis.call('GET', KEYS[1]) or '0')
local new_bid = tonumber(ARGV[1])

if new_bid > current_bid then
    -- Bid is valid. Update the price and the winner.
    redis.call('SET', KEYS[1], new_bid)
    redis.call('SET', KEYS[2], ARGV[2])
    return 1 -- Success
else
    return 0 -- Failed: New bid is too low
end
"""

# Global variables to hold our connection and compiled script
redis_client = None
place_bid_script = None

async def init_redis():
    global redis_client, place_bid_script
    
    # Connect to the Redis container running on your local machine
    # decode_responses=True automatically converts Redis byte strings to Python strings
    redis_client = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)
    
    # We "register" the script. This sends the Lua code to the Redis server exactly once 
    # and compiles it. From then on, we can call it incredibly fast using just its hash.
    place_bid_script = redis_client.register_script(LUA_BID_SCRIPT)
    print("✅ Connected to Redis and loaded Lua bidding script.")

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.aclose()
        print("🛑 Disconnected from Redis.")