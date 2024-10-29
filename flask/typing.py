from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:  # pragma: no cover
    from _typeshed.wsgi import WSGIApplication  # noqa: F401
    from werkzeug.datastructures import Headers  # noqa: F401
    from werkzeug.sansio.response import Response  # noqa: F401


# 定义ResponseValue类型，它可以是Response实例、字符串、字节流、列表、字典映射、字符串迭代器或字节迭代器
ResponseValue = t.Union[
    "Response",
    str,
    bytes,
    t.List[t.Any],
    t.Mapping[str, t.Any],
    t.Iterator[str],
    t.Iterator[bytes],
]

# 定义HeaderValue类型，它可以是字符串、字符串列表或字符串元组
HeaderValue = t.Union[str, t.List[str], t.Tuple[str, ...]]

# 定义HeadersValue类型，它可以是Headers实例、字符串到HeaderValue的映射或元组序列
HeadersValue = t.Union[
    "Headers",
    t.Mapping[str, HeaderValue],
    t.Sequence[t.Tuple[str, HeaderValue]],
]

# 定义ResponseReturnValue类型，它可以是ResponseValue、ResponseValue与HeadersValue的元组、
# ResponseValue与整数的元组、ResponseValue与整数及HeadersValue的元组，或是一个WSGIApplication实例
ResponseReturnValue = t.Union[
    ResponseValue,
    t.Tuple[ResponseValue, HeadersValue],
    t.Tuple[ResponseValue, int],
    t.Tuple[ResponseValue, int, HeadersValue],
    "WSGIApplication",
]

# 定义ResponseClass类型变量，它绑定于Response类型
ResponseClass = t.TypeVar("ResponseClass", bound="Response")

# 定义AppOrBlueprintKey类型，它可以是可选的字符串
AppOrBlueprintKey = t.Optional[str]

# 定义AfterRequestCallable类型，它可以是一个接收ResponseClass并返回ResponseClass的可调用对象，
# 或是一个接收ResponseClass并返回一个可等待的ResponseClass的可调用对象
AfterRequestCallable = t.Union[
    t.Callable[[ResponseClass], ResponseClass],
    t.Callable[[ResponseClass], t.Awaitable[ResponseClass]],
]

# 定义BeforeFirstRequestCallable类型，它可以是一个接收无参数并返回None的可调用对象，
# 或是一个接收无参数并返回一个可等待的None的可调用对象
BeforeFirstRequestCallable = t.Union[
    t.Callable[[], None], t.Callable[[], t.Awaitable[None]]
]

# 定义BeforeRequestCallable类型，它可以是一个接收无参数并返回可选的ResponseReturnValue的可调用对象，
# 或是一个接收无参数并返回一个可等待的可选的ResponseReturnValue的可调用对象
BeforeRequestCallable = t.Union[
    t.Callable[[], t.Optional[ResponseReturnValue]],
    t.Callable[[], t.Awaitable[t.Optional[ResponseReturnValue]]],
]

# 定义ShellContextProcessorCallable类型，它是一个接收无参数并返回字典的可调用对象
ShellContextProcessorCallable = t.Callable[[], t.Dict[str, t.Any]]

# 定义TeardownCallable类型，它可以是一个接收可选的BaseException并返回None的可调用对象，
# 或是一个接收可选的BaseException并返回一个可等待的None的可调用对象
TeardownCallable = t.Union[
    t.Callable[[t.Optional[BaseException]], None],
    t.Callable[[t.Optional[BaseException]], t.Awaitable[None]],
]

# 定义TemplateContextProcessorCallable类型，它可以是一个接收无参数并返回字典的可调用对象，
# 或是一个接收无参数并返回一个可等待的字典的可调用对象
TemplateContextProcessorCallable = t.Union[
    t.Callable[[], t.Dict[str, t.Any]],
    t.Callable[[], t.Awaitable[t.Dict[str, t.Any]]],
]

# 定义TemplateFilterCallable类型，它是一个可调用对象，接受任意参数并返回任意类型
TemplateFilterCallable = t.Callable[..., t.Any]

# 定义TemplateGlobalCallable类型，它是一个可调用对象，接受任意参数并返回任意类型
TemplateGlobalCallable = t.Callable[..., t.Any]

# 定义TemplateTestCallable类型，它是一个可调用对象，接受任意参数并返回布尔值
TemplateTestCallable = t.Callable[..., bool]

# 定义URLDefaultCallable类型，它是一个接收字符串和字典并返回None的可调用对象
URLDefaultCallable = t.Callable[[str, t.Dict[str, t.Any]], None]

# 定义URLValuePreprocessorCallable类型，它是一个接收可选的字符串和可选的字典并返回None的可调用对象
URLValuePreprocessorCallable = t.Callable[
    [t.Optional[str], t.Optional[t.Dict[str, t.Any]]], None
]

# 定义ErrorHandlerCallable类型，它可以是一个接收任意类型并返回ResponseReturnValue的可调用对象，
# 或是一个接收任意类型并返回一个可等待的ResponseReturnValue的可调用对象
ErrorHandlerCallable = t.Union[
    t.Callable[[t.Any], ResponseReturnValue],
    t.Callable[[t.Any], t.Awaitable[ResponseReturnValue]],
]

# 定义RouteCallable类型，它可以是一个接收任意参数并返回ResponseReturnValue的可调用对象，
# 或是一个接收任意参数并返回一个可等待的ResponseReturnValue的可调用对象
RouteCallable = t.Union[
    t.Callable[..., ResponseReturnValue],
    t.Callable[..., t.Awaitable[ResponseReturnValue]],
]
