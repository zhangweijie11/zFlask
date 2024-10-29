from __future__ import annotations

import importlib.util
import os
import sys
import typing as t
from datetime import datetime
from functools import lru_cache
from functools import update_wrapper

import werkzeug.utils
from werkzeug.exceptions import abort as _wz_abort
from werkzeug.utils import redirect as _wz_redirect
from werkzeug.wrappers import Response as BaseResponse

from .globals import _cv_request
from .globals import current_app
from .globals import request
from .globals import request_ctx
from .globals import session
from .signals import message_flashed

if t.TYPE_CHECKING:  # pragma: no cover
    from .wrappers import Response


def get_debug_flag() -> bool:
    """
    获取调试标志。

    从环境变量中读取FLASK_DEBUG的值，如果值不存在或为'0', 'false', 'no'（不区分大小写），
    则返回False，否则返回True。

    Returns:
        bool: 调试标志的状态。
    """
    val = os.environ.get("FLASK_DEBUG")
    return bool(val and val.lower() not in {"0", "false", "no"})


def get_load_dotenv(default: bool = True) -> bool:
    """
    获取是否加载环境变量文件的标志。

    从环境变量中读取FLASK_SKIP_DOTENV的值，如果值不存在，则返回默认值。
    如果值为'0', 'false', 'no'（不区分大小写），则返回False，否则返回True。

    Args:
        default (bool, optional): 默认值。默认为True。

    Returns:
        bool: 是否加载环境变量文件的标志。
    """
    val = os.environ.get("FLASK_SKIP_DOTENV")

    if not val:
        return default

    return val.lower() in ("0", "false", "no")


@t.overload
def stream_with_context(
        generator_or_function: t.Iterator[t.AnyStr],
) -> t.Iterator[t.AnyStr]: ...


@t.overload
def stream_with_context(
        generator_or_function: t.Callable[..., t.Iterator[t.AnyStr]],
) -> t.Callable[[t.Iterator[t.AnyStr]], t.Iterator[t.AnyStr]]: ...


def stream_with_context(
        generator_or_function: t.Iterator[t.AnyStr] | t.Callable[..., t.Iterator[t.AnyStr]],
) -> t.Iterator[t.AnyStr] | t.Callable[[t.Iterator[t.AnyStr]], t.Iterator[t.AnyStr]]:
    """
    在请求上下文中流式传输数据。

    该函数允许在请求上下文中执行生成器函数或可调用对象，以便在流式传输数据时
    能够访问请求上下文中的变量。

    Args:
        generator_or_function (t.Iterator[t.AnyStr] | t.Callable[..., t.Iterator[t.AnyStr]]):
            要在请求上下文中执行的生成器函数或可调用对象。

    Returns:
        t.Iterator[t.AnyStr] | t.Callable[[t.Iterator[t.AnyStr]], t.Iterator[t.AnyStr]]:
            返回一个流式传输的生成器或装饰器。
    """
    try:
        # 尝试将参数转换为迭代器，如果参数已经是迭代器则直接使用
        gen = iter(generator_or_function)  # type: ignore[arg-type]
    except TypeError:
        # 如果参数不是迭代器，则将其视为可调用对象，并创建一个装饰器
        def decorator(*args: t.Any, **kwargs: t.Any) -> t.Any:
            # 在请求上下文中执行可调用对象，并返回结果生成器
            gen = generator_or_function(*args, **kwargs)  # type: ignore[operator]
            # 将生成器传递给stream_with_context，并返回结果
            return stream_with_context(gen)

        # 将装饰器的元数据更新为与原始可调用对象相同，以保持其名称和文档
        return update_wrapper(decorator, generator_or_function)  # type: ignore[arg-type, return-value]

    # 定义一个内部生成器函数，用于在请求上下文中流式传输数据
    def generator() -> t.Iterator[t.AnyStr | None]:
        # 获取当前请求上下文
        ctx = _cv_request.get(None)
        # 如果没有活动的请求上下文，抛出异常
        if ctx is None:
            raise RuntimeError(
                "'stream_with_context' can only be used when a request"
                " context is active, such as in a view function."
            )
        # 在请求上下文中执行生成器，并开始流式传输数据
        with ctx:
            yield None

            try:
                # 从生成器中逐项生成数据
                yield from gen
            finally:
                # 确保在生成器执行完毕后，如果生成器有close方法，则调用它
                if hasattr(gen, "close"):
                    gen.close()

    # 创建并返回包装后的生成器
    wrapped_g = generator()
    # 预先启动生成器，使其准备好接收数据
    next(wrapped_g)
    return wrapped_g  # type: ignore[return-value]



def make_response(*args: t.Any) -> Response:
    """
    根据传入的参数构建一个响应对象。

    该函数是 Flask 应用中的一个辅助函数，用于简化响应对象的创建过程。
    它可以根据传入的参数数量和内容，灵活地创建不同的响应对象。

    参数:
    *args: t.Any - 可变数量的参数，用于构建响应对象。参数类型不定，取决于具体的响应需求。

    返回:
    Response - 返回一个根据当前应用上下文和传入参数构建的响应对象。
    """
    # 如果没有提供任何参数，则创建并返回一个空的响应对象。
    if not args:
        return current_app.response_class()

    # 如果只有一个参数，则直接使用该参数，而不是使用元组。
    if len(args) == 1:
        args = args[0]

    # 使用当前应用的 make_response 方法和提供的参数，创建并返回一个响应对象。
    return current_app.make_response(args)



def url_for(
        endpoint: str,
        *,
        _anchor: str | None = None,
        _method: str | None = None,
        _scheme: str | None = None,
        _external: bool | None = None,
        **values: t.Any,
) -> str:
    """
    生成指定终点的URL。

    此函数通过当前应用的URL路由生成指定终点（endpoint）的URL，支持通过各种参数定制URL。

    参数:
    - endpoint (str): URL的终点名称。
    - _anchor (str | None, optional): 若提供，则在URL中添加锚点。
    - _method (str | None, optional): 指定HTTP方法，影响URL的生成。
    - _scheme (str | None, optional): 指定URL的方案部分（如http, https）。
    - _external (bool | None, optional): 是否生成绝对URL（包含方案和域名）。
    - **values (t.Any): 其他任何终点支持的参数，如查询参数等。

    返回:
    - str: 生成的URL字符串。

    此函数主要是作为一个工具函数，用于在Flask等框架中生成动态URL，便于开发者构建灵活的、可配置的URL。
    """
    # 调用当前应用的url_for方法来生成URL，传入所有提供的参数
    return current_app.url_for(
        endpoint,
        _anchor=_anchor,
        _method=_method,
        _scheme=_scheme,
        _external=_external,
        **values,
    )



def redirect(
        location: str, code: int = 302, Response: type[BaseResponse] | None = None
) -> BaseResponse:
    """
    重定向函数。

    该函数用于执行HTTP重定向到指定的位置。它首先检查是否存在一个当前应用（current_app），
    如果存在，使用当前应用的redirect方法进行重定向。如果不存在当前应用，它将调用_wz_redirect函数
    进行重定向。

    Parameters:
    - location (str): 重定向的目标URL。
    - code (int): HTTP状态码，默认为302，表示临时重定向。
    - Response (type[BaseResponse] | None): 可选的响应类类型，用于自定义响应对象。

    Returns:
    - BaseResponse: 返回一个BaseResponse实例，用于执行重定向操作。
    """
    # 检查是否存在当前应用
    if current_app:
        # 如果存在，使用当前应用的redirect方法进行重定向
        return current_app.redirect(location, code=code)
    else:
        # 如果不存在当前应用，调用_wz_redirect函数进行重定向
        return _wz_redirect(location, code=code, Response=Response)



def abort(code: int | BaseResponse, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
    """
    中止当前请求并返回特定错误响应。

    该函数根据提供的参数中止当前请求。如果当前应用上下文 (current_app) 存在，
    则使用当前应用的 aborter 中止请求；否则使用全局的中止函数 _wz_abort 中止请求。

    :param code: 错误代码，可以是整数或 BaseResponse 实例。
    :param args: 传递给中止函数的额外位置参数。
    :param kwargs: 传递给中止函数的额外关键字参数。
    :return: 该函数不会返回，标记为 t.NoReturn。
    """
    # 检查当前应用上下文是否存在
    if current_app:
        # 使用当前应用的 aborter 中止请求
        current_app.aborter(code, *args, **kwargs)
    else:
        # 使用全局的中止函数中止请求
        _wz_abort(code, *args, **kwargs)



def get_template_attribute(template_name: str, attribute: str) -> t.Any:
    """
    从Jinja2模板中获取指定属性的值。

    :param template_name: 模板文件的名称，用于定位特定的模板。
    :param attribute: 需要从模板中获取的属性名称。
    :return: 返回模板中指定属性的值，属性类型可以是任意合法的Python类型。
    """
    # 使用current_app的jinja_env属性获取Jinja2环境。
    # 调用get_template方法加载指定名称的模板。
    # 使用getattr函数从模板的module属性中获取指定名称的属性。
    return getattr(current_app.jinja_env.get_template(template_name).module, attribute)



def flash(message: str, category: str = "message") -> None:
    """
    在Web应用中显示一次性消息。

    该函数将消息及其类别添加到用户会话中的"_flashes"列表里，并触发message_flashed事件，
    以便在服务器和客户端之间同步消息。

    参数:
    - message (str): 要显示的消息文本。
    - category (str): 消息的类别，默认为"message"。可以用来区分不同类型的消息（如"error"、"info"等）。

    返回:
    - None
    """
    # 从会话中获取已有的闪现消息列表，如果不存在，则初始化为空列表
    flashes = session.get("_flashes", [])
    # 将新的消息及其类别作为元组添加到闪现消息列表中
    flashes.append((category, message))
    # 更新会话中的闪现消息列表
    session["_flashes"] = flashes

    # 获取当前应用实例，忽略类型检查以避免特定框架的依赖问题
    app = current_app._get_current_object()  # type: ignore
    # 触发message_flashed信号，传递应用实例、异步包装器、消息文本和类别
    message_flashed.send(
        app,
        _async_wrapper=app.ensure_sync,
        message=message,
        category=category,
    )



def get_flashed_messages(
        with_categories: bool = False, category_filter: t.Iterable[str] = ()
) -> list[str] | list[tuple[str, str]]:
    """
    获取存储在会话中的闪光消息。

    该函数从请求上下文中提取闪光消息，如果在请求上下文中没有找到，则尝试从会话中提取。
    它可以根据类别过滤消息，并选择是否将类别与消息一起返回。

    参数:
    - with_categories: 指示是否返回消息类别。如果为False，只返回消息文本。
    - category_filter: 一个包含要过滤的类别的可迭代对象。如果提供，只有属于这些类别的消息会被返回。

    返回:
    - 如果with_categories为False，返回一个包含消息文本的列表。
    - 如果with_categories为True，返回一个包含类别和消息文本的元组列表。
    """
    # 尝试从请求上下文中获取闪光消息
    flashes = request_ctx.flashes
    if flashes is None:
        # 如果请求上下文中没有闪光消息，尝试从会话中提取
        flashes = session.pop("_flashes") if "_flashes" in session else []
        request_ctx.flashes = flashes
    if category_filter:
        # 如果提供了类别过滤器，应用过滤
        flashes = list(filter(lambda f: f[0] in category_filter, flashes))
    if not with_categories:
        # 如果不需要返回类别，只返回消息文本列表
        return [x[1] for x in flashes]
    # 如果需要返回类别，返回包含类别和消息文本的元组列表
    return flashes



def _prepare_send_file_kwargs(**kwargs: t.Any) -> dict[str, t.Any]:
    """
    准备发送文件的关键字参数。

    此函数用于根据当前应用的配置更新发送文件的关键字参数，以确保这些参数与应用的设置一致。

    参数:
    - **kwargs: t.Any - 接受任意关键字参数，这些参数将被更新以包含发送文件所必需的配置。

    返回:
    - dict[str, t.Any] - 更新后的关键字参数字典，包含了发送文件所需的配置。
    """
    # 如果max_age参数未设置，使用当前应用的get_send_file_max_age方法获取默认值
    if kwargs.get("max_age") is None:
        kwargs["max_age"] = current_app.get_send_file_max_age

    # 更新关键字参数，添加当前请求环境、是否使用x_sendfile、响应类和应用的根路径
    kwargs.update(
        environ=request.environ,
        use_x_sendfile=current_app.config["USE_X_SENDFILE"],
        response_class=current_app.response_class,
        _root_path=current_app.root_path,  # type: ignore
    )
    # 返回更新后的关键字参数字典
    return kwargs



def send_file(
        path_or_file: os.PathLike[t.AnyStr] | str | t.BinaryIO,
        mimetype: str | None = None,
        as_attachment: bool = False,
        download_name: str | None = None,
        conditional: bool = True,
        etag: bool | str = True,
        last_modified: datetime | int | float | None = None,
        max_age: None | (int | t.Callable[[str | None], int | None]) = None,
) -> Response:
    """
    发送文件作为HTTP响应。

    该函数主要用于发送文件给客户端。它可以将文件内容直接发送到客户端，或者将文件作为附件发送。

    参数:
    - path_or_file: 文件的路径或文件对象。可以是路径字符串、路径对象或文件对象。
    - mimetype: 文件的MIME类型。如果未提供，将根据文件扩展名进行推断。
    - as_attachment: 是否将文件作为附件发送。如果为True，浏览器将提示用户下载文件。
    - download_name: 当文件作为附件发送时，指定文件的下载名称。
    - conditional: 是否使用条件响应。如果为True，将根据客户端的请求头生成条件响应。
    - etag: 是否使用ETag。可以是布尔值或字符串。如果为True，将生成一个唯一的ETag。
    - last_modified: 文件的最后修改时间。可以是datetime对象、时间戳或None。
    - max_age: 缓存控制的最大年龄。可以是整数表示秒数，或一个可调用对象，根据请求路径返回最大年龄。

    返回:
    - Response: 一个包含文件内容的HTTP响应对象。
    """
    # 准备发送文件所需的参数，并调用werkzeug.utils.send_file函数发送文件
    return werkzeug.utils.send_file(  # type: ignore[return-value]
        **_prepare_send_file_kwargs(
            path_or_file=path_or_file,
            environ=request.environ,
            mimetype=mimetype,
            as_attachment=as_attachment,
            download_name=download_name,
            conditional=conditional,
            etag=etag,
            last_modified=last_modified,
            max_age=max_age,
        )
    )



def send_from_directory(
        directory: os.PathLike[str] | str,
        path: os.PathLike[str] | str,
        **kwargs: t.Any,
) -> Response:
    """
    从指定目录发送文件。

    本函数封装了werkzeug.utils.send_from_directory，用于从一个特定的目录中发送文件。
    它允许通过路径参数来指定要发送的文件，并支持额外的关键字参数以定制发送行为。

    参数:
    - directory: os.PathLike[str] | str -- 文件所在的目录。
    - path: os.PathLike[str] | str -- 相对于directory的文件路径。
    - **kwargs: t.Any -- 额外的关键字参数，用于定制文件发送行为。

    返回:
    - Response -- 生成的文件响应。
    """
    # 调用werkzeug.utils.send_from_directory发送文件，此处忽略类型检查以避免类型错误。
    return werkzeug.utils.send_from_directory(  # type: ignore[return-value]
        directory, path, **_prepare_send_file_kwargs(**kwargs)
    )



def get_root_path(import_name: str) -> str:
    """
    获取给定模块的根路径。

    该函数尝试通过模块名找到模块的文件位置，并返回其所在目录的绝对路径。
    如果模块来自没有文件名信息的导入钩子或是一个命名空间包，
    则可能无法找到根路径，在这种情况下，需要显式提供根路径。

    参数:
    import_name: 模块的名称，用于查找模块的路径。

    返回:
    模块的根路径的绝对值。如果无法确定路径，则返回当前工作目录。
    """

    # 尝试从已加载的模块中获取指定模块
    mod = sys.modules.get(import_name)

    # 如果模块已加载且有文件属性，则直接返回文件的目录路径
    if mod is not None and hasattr(mod, "__file__") and mod.__file__ is not None:
        return os.path.dirname(os.path.abspath(mod.__file__))

    try:
        # 尝试查找模块的规格信息
        spec = importlib.util.find_spec(import_name)

        # 如果找不到模块规格，抛出ValueError异常
        if spec is None:
            raise ValueError
    except (ImportError, ValueError):
        # 捕获ImportError或ValueError，将loader设置为None
        loader = None
    else:
        # 如果找到模块规格，获取其加载器
        loader = spec.loader

    # 如果加载器为空，返回当前工作目录
    if loader is None:
        return os.getcwd()

    # 如果加载器有get_filename方法，使用该方法获取文件路径
    if hasattr(loader, "get_filename"):
        filepath = loader.get_filename(import_name)
    else:
        # 否则，导入模块并尝试获取其__file__属性
        __import__(import_name)
        mod = sys.modules[import_name]
        filepath = getattr(mod, "__file__", None)

        # 如果无法获取文件路径，抛出运行时错误
        if filepath is None:
            raise RuntimeError(
                "No root path can be found for the provided module"
                f" {import_name!r}. This can happen because the module"
                " came from an import hook that does not provide file"
                " name information or because it's a namespace package."
                " In this case the root path needs to be explicitly"
                " provided."
            )

    # 返回文件路径的目录部分
    return os.path.dirname(os.path.abspath(filepath))  # type: ignore[no-any-return]



@lru_cache(maxsize=None)
def _split_blueprint_path(name: str) -> list[str]:
    """
    分割蓝图路径。

    该函数通过将蓝图名称按点（".")分隔，生成一个包含所有层级的路径列表。
    使用了LRU缓存来优化重复路径的处理。

    参数:
    - name: 蓝图的名称，字符串类型。

    返回值:
    - 一个字符串列表，包含按层级分割的蓝图路径。
    """
    # 初始化路径列表，包含当前蓝图名称
    out: list[str] = [name]

    # 如果蓝图名称中包含点（"."），则进行递归分割
    if "." in name:
        # 使用rpartition从右边开始分割，获取最后一个点之前的部分
        # 递归调用_split_blueprint_path，直到分割完所有层级
        out.extend(_split_blueprint_path(name.rpartition(".")[0]))

    # 返回分割后的路径列表
    return out

