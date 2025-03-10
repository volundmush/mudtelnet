import asyncio

async def never_finishing():
    # This coroutine waits on an Event that is never set.
    ev = asyncio.Event()
    await ev.wait()

async def test_timeout():
    try:
        await asyncio.wait_for(never_finishing(), 0.5)
    except asyncio.TimeoutError:
        print("Timeout occurred as expected.")

asyncio.run(test_timeout())