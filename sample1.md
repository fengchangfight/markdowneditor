# Python 并发编程


## GIL 是什么

全局解释器锁（Global Interpreter Lock），CPython 中同一时刻只有一个线程执行 Python 字节码。

&gt; ⚠️ GIL 只影响 CPU 密集型任务，IO 密集型可用多线程。

## 方案对比

| 场景 | 推荐方案 | 原因 |
|------|----------|------|
| IO 密集（网络/文件） | `threading` | 切换开销小 |
| CPU 密集（计算） | `multiprocessing` | 绕过 GIL |
| 高并发网络 | `asyncio` | 协程轻量高效 |

## 代码示例

```python
import asyncio

async def fetch(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.text()

# 并发执行
urls = ["https://a.com", "https://b.com"]
results = await asyncio.gather(*[fetch(u) for u in urls])