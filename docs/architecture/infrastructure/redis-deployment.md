# Redis-Based Inter-Container Communication

## Overview

The TUYUL-FX-WOLF 15-Layer Trading System now supports **multi-container deployment** with Redis-based data sharing between the `ingest` and `engine` containers.

### Problem Solved

Previously, the `ingest` service (Finnhub WebSocket) and `engine` service (main trading loop) ran in separate Docker containers but used an **in-memory `LiveContextBus`** singleton. This meant:

- Each container had its own isolated `LiveContextBus` instance
- **Zero market data** flowed from ingest → engine
- The trading engine operated on empty/stale data

### Solution

Redis-based pub/sub and streams architecture enables real-time data sharing:

┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Ingest      │    │   Redis      │    │  Engine      │
│  Container   │───▶│  Pub/Sub &   │───▶│  Container   │
│              │    │  Streams     │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
   FinnhubWS           Tick Stream         RedisConsumer
   CandleBuilder       Candle Pub/Sub      LiveContextBus
                       News Pub/Sub        Analysis L1-L12

## Architecture Components

### 1. Redis Client (`storage/redis_client.py`)

Enhanced with:

- **Connection pooling** (max 50 connections)
- **Redis Streams** support (XADD, XREAD, XREADGROUP)
- **Redis Pub/Sub** support
- **Retry logic** with exponential backoff (tenacity)
- Type hints and comprehensive error handling

### 2. Redis Context Bridge (`context/redis_context_bridge.py`)

Publisher component that writes to Redis:

- **Ticks** → Redis Streams `tick:{symbol}` (maxlen 10,000)
- **Latest tick** → Redis Hash `latest_tick:{symbol}`
- **Candles** → Redis Pub/Sub `candle:{symbol}:{timeframe}`
- **News** → Redis Pub/Sub `news_updates`

### 3. LiveContextBus (`context/live_context_bus.py`)

Supports dual modes:

- **Local mode** (default): Pure in-memory for single-process
- **Redis mode**: Writes to local memory AND Redis for multi-container

Mode controlled by `CONTEXT_MODE` environment variable.

### 4. Redis Consumer (`context/redis_consumer.py`)

Consumer component running in engine container:

- Reads ticks from Redis Streams using **consumer groups**
- Subscribes to candle and news Pub/Sub channels
- Feeds data into local `LiveContextBus`
- Runs as async background task

### 5. Main Loop (`main.py`)

- Detects `CONTEXT_MODE=redis`
- Spawns `RedisConsumer` in background thread
- Trading logic works with real-time data

### 6. Ingest Service (`ingest_service.py`)

Entry point that runs:

- `FinnhubWebSocket` for real-time price feed
- `CandleBuilder` for tick → M15/H1 aggregation

## Deployment Modes

### Local Development (Single Process)

```bash
# .env
CONTEXT_MODE=local

# Run everything in one process
python main.py
```

### Docker Multi-Container (Production)

```bash
# .env
CONTEXT_MODE=redis
REDIS_URL=redis://redis:6379/0

# Start all containers
docker-compose up -d
```

Containers:

- `redis` - Data storage and message broker
- `ingest` - Finnhub WebSocket + Candle Builder
- `engine` - Trading analysis and decision engine
- `api` - FastAPI dashboard backend

## Configuration

### Environment Variables

```env
# Context Mode
CONTEXT_MODE=redis          # redis | local (default: local)

# Redis Connection
REDIS_URL=redis://redis:6379/0
REDIS_PREFIX=wolf15
REDIS_SOCKET_TIMEOUT_SEC=5

# Economic calendar provider-chain ingestion (ingest/calendar_news.py)
NEWS_INGEST_ENABLED=true
NEWS_POLL_INTERVAL_SEC=300
NEWS_PROVIDER=forexfactory
```

### Docker Compose

The `docker-compose.yml` automatically sets:

- `CONTEXT_MODE=redis` for ingest and engine containers
- `REDIS_URL=redis://redis:6379/0` for all services
- Health checks for Redis availability

## Data Flow

### Tick Data Flow

1. Finnhub WS receives tick
   ↓
2. FinnhubWebSocket._handle_message()
   ↓
3. LiveContextBus.update_tick()
   ├─▶ Local: Append to deque
   └─▶ Redis: XADD to stream + HSET latest + PUBLISH
   ↓
4. Redis Streams: tick:{symbol}
   ↓
5. Engine: RedisConsumer reads with XREADGROUP
   ↓
6. Engine: LiveContextBus.update_tick()
   ↓
7. Analysis layers access via get_latest_tick()

### Candle Data Flow

1. CandleBuilder aggregates ticks
   ↓
2. LiveContextBus.update_candle()
   ├─▶ Local: Store in dict
   └─▶ Redis: PUBLISH to channel + HSET latest
   ↓
3. Redis Pub/Sub: candle:{symbol}:{timeframe}
   ↓
4. Engine: RedisConsumer subscribes
   ↓
5. Engine: LiveContextBus.update_candle()
   ↓
6. Analysis layers access via get_candle()

## Redis Data Structures

### Streams (Tick Data)

Key: wolf15:tick:{symbol}
Type: Stream
Maxlen: ~10,000 (approximate)
Entry: {"data": "{json_tick}"}
Consumer Group: engine_group

### Hashes (Latest Data)

Key: wolf15:latest_tick:{symbol}
Type: Hash
Field: data
Value: {json_tick}

Key: wolf15:candle:{symbol}:{timeframe}
Type: Hash
Field: data
Value: {json_candle}

### Pub/Sub Channels

Channel: tick_updates
Publisher: Ingest (on every tick)
Subscribers: Engine RedisConsumer

Channel: candle:{symbol}:{timeframe}
Publisher: Ingest (on candle completion)
Subscribers: Engine RedisConsumer

Channel: news_updates
Publisher: Ingest (on news fetch)
Subscribers: Engine RedisConsumer

## Performance Characteristics

### Tick Processing

- **Latency**: <5ms from ingest → Redis → engine
- **Throughput**: 10,000+ ticks/sec
- **Durability**: Last 10,000 ticks per symbol retained
- **Backpressure**: Approximate maxlen trimming

### Connection Pool

- **Max connections**: 50
- **Timeout**: 5 seconds
- **Retry**: 3 attempts with exponential backoff

### Memory Usage

Redis memory cap: 512MB (configured in docker-compose.yml)
Policy: allkeys-lru (evict least recently used)

## Backward Compatibility

✅ **Zero breaking changes**

- Local mode (`CONTEXT_MODE=local`) works exactly as before
- All existing code continues to work
- No changes needed in analysis layers
- Transparent to developers

## Monitoring & Debugging

### Check Redis Health

```bash
docker-compose exec redis redis-cli ping
# Expected: PONG
```

### Monitor Stream Length

```bash
docker-compose exec redis redis-cli XLEN wolf15:tick:EURUSD
# Example: (integer) 8432
```

### View Latest Tick

```bash
docker-compose exec redis redis-cli HGET wolf15:latest_tick:EURUSD data
# Returns: {"symbol":"EURUSD","bid":1.0842,"ask":1.0843,...}
```

### Check Pub/Sub Activity

```bash
docker-compose exec redis redis-cli PUBSUB CHANNELS
# Lists active channels
```

### View Consumer Group

```bash
docker-compose exec redis redis-cli XINFO GROUPS wolf15:tick:EURUSD
# Shows consumer group status
```

### Container Logs

```bash
# Ingest container
docker-compose logs -f ingest

# Engine container
docker-compose logs -f engine

# Redis container
docker-compose logs -f redis
```

## Testing

### Unit Tests

```bash
pytest tests/test_redis_bridge.py -v
# 16 tests covering Redis bridge and LiveContextBus modes
```

### Integration Test

1. Start containers: `docker-compose up -d`
2. Check ingest logs: `docker-compose logs -f ingest`
3. Check engine logs: `docker-compose logs -f engine`
4. Verify tick flow: `docker-compose exec redis redis-cli XLEN wolf15:tick:EURUSD`

## Troubleshooting

### No Data in Engine

**Symptoms**: Engine container shows no ticks/candles

**Checklist**:

1. Check `CONTEXT_MODE=redis` is set in both containers
2. Verify Redis is healthy: `docker-compose ps`
3. Check ingest logs for tick ingestion
4. Check Redis streams: `redis-cli XLEN wolf15:tick:EURUSD`
5. Check engine logs for RedisConsumer startup

### Redis Connection Errors

**Symptoms**: `redis.exceptions.ConnectionError`

**Solutions**:

1. Verify Redis is running: `docker-compose ps redis`
2. Check `REDIS_URL` environment variable
3. Check network connectivity: `docker-compose exec engine ping redis`
4. Review Redis logs: `docker-compose logs redis`

### High Memory Usage

**Symptoms**: Redis memory approaching 512MB limit

**Solutions**:

1. Reduce tick stream maxlen in `redis_context_bridge.py`
2. Increase Redis memory limit in `docker-compose.yml`
3. Check for memory leaks in application code
4. Monitor with: `redis-cli INFO memory`

### Consumer Group Errors

**Symptoms**: `BUSYGROUP` or `NOGROUP` errors

**Solutions**:

1. Consumer groups are auto-created on first run
2. Delete and recreate: `redis-cli XGROUP DESTROY wolf15:tick:EURUSD engine_group`
3. Check engine logs for consumer initialization

## Security Considerations

- Redis is on private Docker network (not exposed to host)
- No authentication required within trusted network
- For production: Redis AUTH + TLS are enforced for non-local hosts (`rediss://` + password)
- Use secrets management for sensitive credentials
- Network policies to restrict Redis access

## Migration Guide

### From In-Memory to Redis Mode

1. **Update .env**:

   ```env
   CONTEXT_MODE=redis
   ```

2. **Start Redis**:

   ```bash
   docker-compose up -d redis
   ```

3. **Restart services**:

   ```bash
   docker-compose restart ingest engine
   ```

4. **Verify**:

   ```bash
   docker-compose logs -f engine | grep "RedisConsumer started"
   ```

### Rollback to Local Mode

1. **Update .env**:

   ```env
   CONTEXT_MODE=local
   ```

2. **Restart services**:

   ```bash
   docker-compose restart ingest engine
   ```

## Performance Tuning

### Increase Throughput

- Increase Redis connection pool size in `redis_client.py`
- Batch tick writes with PIPELINE
- Tune `maxlen` parameter for tick streams

### Reduce Latency

- Use Redis on same host as containers
- Enable TCP_NODELAY
- Reduce `socket_timeout` for faster failures

### Scale Horizontally

- Multiple ingest containers (different symbols)
- Multiple engine consumers (consumer group handles distribution)
- Redis Cluster for high availability

## References

- [Redis Streams Documentation](https://redis.io/docs/data-types/streams/)
- [Redis Pub/Sub Documentation](https://redis.io/docs/interact/pubsub/)
- [Python Redis Client](https://redis-py.readthedocs.io/)
- [Docker Compose Networking](https://docs.docker.com/compose/networking/)
