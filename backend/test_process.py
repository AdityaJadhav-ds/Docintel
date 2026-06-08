import asyncio
import anyio.to_process
from app.services.validation_service import process_user_documents

async def test():
    print("Testing process pool...")
    res = await anyio.to_process.run_sync(process_user_documents, 1)
    print(res)

if __name__ == '__main__':
    asyncio.run(test())
