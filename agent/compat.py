"""Python 3.8 兼容层。

项目最低支持 Python 3.8。3.9+ 才有的标准库能力统一放在这里做降级，
避免各模块散落版本判断。
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")


async def to_thread(func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """``asyncio.to_thread`` 的 3.8 兼容实现。

    Python 3.9+ 直接走标准库；3.8 用 ``run_in_executor`` 达到相同效果。
    """
    impl = getattr(asyncio, "to_thread", None)
    if impl is not None:
        return await impl(func, *args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
