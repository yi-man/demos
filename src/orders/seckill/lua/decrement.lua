-- KEYS[1] = stock key
-- KEYS[2] = request marker key
-- KEYS[3] = result key
-- ARGV[1] = ttl seconds

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

return "ACCEPTED"
