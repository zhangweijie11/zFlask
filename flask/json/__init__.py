from __future__ import annotations

import json as _json
import typing as t

from ..globals import current_app
from .provider import _default

if t.TYPE_CHECKING:  # pragma: no cover
    from ..wrappers import Response


def dumps(obj: t.Any, **kwargs: t.Any) -> str:
    """
    将Python对象转换为JSON字符串。

    该函数首先检查是否存在当前应用实例（current_app）。如果存在，使用该应用实例的json.dumps方法进行序列化，
    这可能是因为应用实例可能定义了特定的序列化规则或配置。如果不存在当前应用实例，则使用全局的_json.dumps
    方法进行序列化，同时设置一个默认的序列化函数_default，以处理可能无法直接序列化的对象。

    参数:
    - obj: 待序列化的Python对象。
    - **kwargs: 可变关键字参数，允许调用者指定控制序列化过程的选项，例如缩进、排序等。

    返回:
    - str: 序列化后的JSON字符串。
    """
    # 检查是否存在当前应用实例
    if current_app:
        # 使用当前应用实例的json.dumps方法进行序列化
        return current_app.json.dumps(obj, **kwargs)

    # 设置默认的序列化函数处理无法直接序列化的对象
    kwargs.setdefault("default", _default)
    # 使用全局的_json.dumps方法进行序列化
    return _json.dumps(obj, **kwargs)



def dump(obj: t.Any, fp: t.IO[str], **kwargs: t.Any) -> None:
    """
    将Python对象序列化为JSON格式并写入文件。

    此函数根据当前应用上下文的不同，选择使用当前应用的JSON序列化方法或内置的JSON序列化方法。
    它允许通过额外的关键字参数自定义序列化行为。

    参数:
    - obj: t.Any -- 要序列化的Python对象。
    - fp: t.IO[str] -- 用于写入JSON数据的文件对象。
    - **kwargs: t.Any -- 传递给JSON序列化方法的额外关键字参数。

    返回:
    无返回值。
    """
    # 检查是否存在当前应用上下文
    if current_app:
        # 如果存在，使用当前应用的JSON序列化方法
        current_app.json.dump(obj, fp, **kwargs)
    else:
        # 如果不存在，设置默认的序列化行为并使用内置的JSON序列化方法
        kwargs.setdefault("default", _default)
        _json.dump(obj, fp, **kwargs)



def loads(s: str | bytes, **kwargs: t.Any) -> t.Any:
    """
    解析JSON字符串或字节流并将其转换为Python对象。

    该函数根据当前应用上下文的不同，选择适当的JSON解析器来解析输入的字符串或字节流。
    如果存在当前应用实例，将使用应用实例的JSON解析器，否则使用全局的JSON解析器。

    参数:
    - s: 待解析的JSON字符串或字节流。
    - **kwargs: 任意额外的关键字参数，将传递给实际的JSON解析器。

    返回:
    - t.Any: 解析后的Python对象，类型取决于JSON数据本身。

    选择解析器的逻辑:
    - 如果`current_app`存在，则使用`current_app.json.loads`进行解析，这允许解析逻辑与应用上下文相关。
    - 否则，使用全局的`_json.loads`进行解析，这是一种通用的解析方式，不依赖于任何特定的应用上下文。
    """
    if current_app:
        return current_app.json.loads(s, **kwargs)

    return _json.loads(s, **kwargs)



def load(fp: t.IO[t.AnyStr], **kwargs: t.Any) -> t.Any:
    """
    从文件指针中加载JSON数据。

    该函数尝试从当前应用上下文中加载JSON数据，如果不存在应用上下文，
    则使用独立的_json模块加载JSON数据。

    参数:
    - fp: 文件指针，应该已经打开并指向要读取的JSON文件。
    - **kwargs: 可变关键字参数，允许传递额外的参数到json.load函数。

    返回:
    - 从JSON文件中解析出的数据，数据类型取决于JSON内容。
    """
    # 检查是否存在当前应用上下文
    if current_app:
        # 如果存在，使用当前应用上下文中的json.load方法加载JSON数据
        return current_app.json.load(fp, **kwargs)

    # 如果不存在应用上下文，使用独立的_json模块加载JSON数据
    return _json.load(fp, **kwargs)



def jsonify(*args: t.Any, **kwargs: t.Any) -> Response:
    """
    生成一个JSON格式的HTTP响应。

    该函数接受任意数量和关键字参数，将其序列化为JSON格式的数据，并返回一个包含这些数据的HTTP响应。
    它是Flask框架中的一个辅助函数，用于简化JSON数据的返回过程。

    Parameters:
    - *args: 任意数量的非关键字参数，这些参数将被序列化为JSON格式的数据。
    - **kwargs: 任意数量的关键字参数，这些参数将被序列化为JSON格式的数据。

    Returns:
    - Response: 一个包含JSON格式数据的HTTP响应对象。
    """

    # 使用当前应用的JSON响应构造器来生成响应
    return current_app.json.response(*args, **kwargs)  # type: ignore[return-value]

