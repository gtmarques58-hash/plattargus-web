import redis.asyncio as redis
from app.config import settings

async def get_redis():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)

async def ensure_group(r, stream: str):
    try:
        await r.xgroup_create(stream, settings.CONSUMER_GROUP, id="0-0", mkstream=True)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            raise

async def push_job(r, stream: str, job_id: str, *, priority: int | None = None):
    fields = {"job_id": job_id}
    if priority is not None:
        fields["priority"] = str(priority)
    await r.xadd(stream, fields)

async def read_one(r, stream: str, block_ms: int = 5000):
    resp = await r.xreadgroup(
        groupname=settings.CONSUMER_GROUP,
        consumername=settings.CONSUMER_NAME,
        streams={stream: ">"},
        count=1,
        block=block_ms
    )
    if not resp:
        return None
    _stream, msgs = resp[0]
    msg_id, fields = msgs[0]
    return msg_id, fields

async def ack(r, stream: str, msg_id: str):
    await r.xack(stream, settings.CONSUMER_GROUP, msg_id)
