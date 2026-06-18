-- Distributed token-bucket rate limiter.
-- Runs atomically inside Redis; uses the Redis server clock (TIME) so it is
-- correct across many app instances regardless of their local clock skew.
--
-- KEYS[1] = bucket key
-- ARGV[1] = capacity (max tokens / burst)
-- ARGV[2] = refill rate (tokens per second)
-- ARGV[3] = requested tokens (cost of this call)
-- returns: { allowed (1/0), remaining_tokens (string) }

local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])

local t = redis.call('TIME')
local now = tonumber(t[1]) + (tonumber(t[2]) / 1000000)

local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  ts = now
end

local delta = now - ts
if delta < 0 then delta = 0 end
tokens = math.min(capacity, tokens + (delta * refill))

local allowed = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
-- expire idle buckets so we don't leak memory
redis.call('PEXPIRE', KEYS[1], math.ceil((capacity / refill) * 1000) + 1000)

return { allowed, tostring(tokens) }
