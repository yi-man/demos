-- KEYS[1] = stock key
-- KEYS[2] = request marker key
-- KEYS[3] = result key
-- KEYS[4] = stream key
-- ARGV[1] = ttl seconds
-- ARGV[2] = activity_id
-- ARGV[3] = user_id
-- ARGV[4] = request_id

if redis.call("EXISTS", KEYS[2]) == 1 then
    return "DUPLICATE"
end

local stock = tonumber(redis.call("GET", KEYS[1]) or "0")
if stock <= 0 then
    return "SOLD_OUT"
end

redis.call("DECR", KEYS[1])
redis.call("SET", KEYS[2], "1", "EX", ARGV[1])
redis.call("SET", KEYS[3], "PENDING", "EX", ARGV[1])
redis.call(
    "XADD",
    KEYS[4],
    "*",
    "activity_id",
    ARGV[2],
    "user_id",
    ARGV[3],
    "request_id",
    ARGV[4]
)

return "ACCEPTED"
