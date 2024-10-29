from __future__ import annotations

import typing as t

from jinja2.loaders import BaseLoader
from werkzeug.routing import RequestRedirect

from .blueprints import Blueprint
from .globals import request_ctx
from .sansio.app import App

if t.TYPE_CHECKING:
    from .sansio.scaffold import Scaffold
    from .wrappers import Request


class UnexpectedUnicodeError(AssertionError, UnicodeError):
    """Raised in places where we want some better error reporting for
    unexpected unicode or binary data.
    """


class DebugFilesKeyError(KeyError, AssertionError):
    """
    当尝试访问request.files中的文件但文件不存在时引发的自定义异常。

    这个异常同时继承自KeyError和AssertionError，用于处理文件上传时的错误。

    参数:
    - request: 当前的请求对象。
    - key: 尝试访问的文件键名。
    """

    def __init__(self, request: Request, key: str) -> None:
        """
        初始化异常对象，并根据请求信息构建异常消息。

        参数:
        - request: 当前的请求对象。
        - key: 尝试访问的文件键名。
        """
        form_matches = request.form.getlist(key)
        buf = [
            f"You tried to access the file {key!r} in the request.files"
            " dictionary but it does not exist. The mimetype for the"
            f" request is {request.mimetype!r} instead of"
            " 'multipart/form-data' which means that no file contents"
            " were transmitted. To fix this error you should provide"
            ' enctype="multipart/form-data" in your form.'
        ]
        if form_matches:
            names = ", ".join(repr(x) for x in form_matches)
            buf.append(
                "\n\nThe browser instead transmitted some file names. "
                f"This was submitted: {names}"
            )
        self.msg = "".join(buf)

    def __str__(self) -> str:
        """
        返回异常的字符串表示。

        返回:
        - 异常消息字符串。
        """
        return self.msg


class FormDataRoutingRedirect(AssertionError):
    """
    当表单数据路由重定向时引发的自定义异常。

    这个异常继承自AssertionError，用于在调试模式下处理表单数据的路由重定向问题。

    参数:
    - request: 当前的请求对象。
    """

    def __init__(self, request: Request) -> None:
        """
        初始化异常对象，并根据请求信息构建异常消息。

        参数:
        - request: 当前的请求对象。
        """
        exc = request.routing_exception
        assert isinstance(exc, RequestRedirect)
        buf = [
            f"A request was sent to '{request.url}', but routing issued"
            f" a redirect to the canonical URL '{exc.new_url}'."
        ]

        if f"{request.base_url}/" == exc.new_url.partition("?")[0]:
            buf.append(
                " The URL was defined with a trailing slash. Flask"
                " will redirect to the URL with a trailing slash if it"
                " was accessed without one."
            )

        buf.append(
            " Send requests to the canonical URL, or use 307 or 308 for"
            " routing redirects. Otherwise, browsers will drop form"
            " data.\n\n"
            "This exception is only raised in debug mode."
        )
        super().__init__("".join(buf))


def attach_enctype_error_multidict(request: Request) -> None:
    """
    为请求的files属性附加自定义错误处理。

    这个函数会修改请求的files属性的类，为其添加自定义的__getitem__方法，
    以便在文件键不存在时抛出更详细的异常信息。

    参数:
    - request: 当前的请求对象。
    """
    oldcls = request.files.__class__

    class newcls(oldcls):  # type: ignore[valid-type, misc]
        """
        继承自原files类的自定义类，带有增强的错误处理。
        """
        def __getitem__(self, key: str) -> t.Any:
            """
            尝试获取文件，如果文件不存在则抛出DebugFilesKeyError异常。

            参数:
            - key: 文件键名。

            异常:
            - DebugFilesKeyError: 如果文件键不存在。
            """
            try:
                return super().__getitem__(key)
            except KeyError as e:
                if key not in request.form:
                    raise

                raise DebugFilesKeyError(request, key).with_traceback(
                    e.__traceback__
                ) from None

    newcls.__name__ = oldcls.__name__
    newcls.__module__ = oldcls.__module__
    request.files.__class__ = newcls


def _dump_loader_info(loader: BaseLoader) -> t.Iterator[str]:
    """
    生成加载器信息的字符串迭代器。

    参数:
    - loader: 模板加载器对象。

    返回:
    - 加载器信息的字符串迭代器。
    """
    # 生成加载器的类信息字符串
    yield f"class: {type(loader).__module__}.{type(loader).__name__}"

    # 遍历加载器的属性，生成相应的信息字符串
    for key, value in sorted(loader.__dict__.items()):
        if key.startswith("_"):
            continue
        if isinstance(value, (tuple, list)):
            if not all(isinstance(x, str) for x in value):
                continue
            yield f"{key}:"
            for item in value:
                yield f"  - {item}"
            continue
        elif not isinstance(value, (str, int, float, bool)):
            continue
        yield f"{key}: {value!r}"



def explain_template_loading_attempts(
    app: App,
    template: str,
    attempts: list[
        tuple[
            BaseLoader,
            Scaffold,
            tuple[str, str | None, t.Callable[[], bool] | None] | None,
        ]
    ],
) -> None:
    """
    记录模板加载尝试的详细信息。

    这个函数会生成关于模板加载尝试的信息，并将其记录到应用日志中。

    参数:
    - app: 应用对象。
    - template: 模板名。
    - attempts: 模板加载尝试的列表，每个尝试包含加载器、源对象和加载结果。
    """
    # 初始化信息列表，用于记录模板加载尝试的详细信息
    info = [f"Locating template {template!r}:"]
    # 初始化找到的模板计数
    total_found = 0
    # 初始化蓝图变量
    blueprint = None
    # 如果请求上下文存在且请求有蓝图，则获取蓝图
    if request_ctx and request_ctx.request.blueprint is not None:
        blueprint = request_ctx.request.blueprint

    # 遍历每个模板加载尝试
    for idx, (loader, srcobj, triple) in enumerate(attempts):
        # 根据源对象类型生成源信息
        if isinstance(srcobj, App):
            src_info = f"application {srcobj.import_name!r}"
        elif isinstance(srcobj, Blueprint):
            src_info = f"blueprint {srcobj.name!r} ({srcobj.import_name})"
        else:
            src_info = repr(srcobj)

        # 将尝试使用的加载器信息添加到信息列表
        info.append(f"{idx + 1:5}: trying loader of {src_info}")

        # 将加载器的详细信息添加到信息列表
        for line in _dump_loader_info(loader):
            info.append(f"       {line}")

        # 根据加载结果更新信息列表和找到的模板计数
        if triple is None:
            detail = "no match"
        else:
            detail = f"found ({triple[1] or '<string>'!r})"
            total_found += 1
        info.append(f"       -> {detail}")

    # 初始化可疑标志
    seems_fishy = False
    # 如果没有找到模板，添加错误信息并设置可疑标志
    if total_found == 0:
        info.append("Error: the template could not be found.")
        seems_fishy = True
    # 如果找到多个模板，添加警告信息并设置可疑标志
    elif total_found > 1:
        info.append("Warning: multiple loaders returned a match for the template.")
        seems_fishy = True

    # 如果有蓝图且存在可疑情况，添加额外的信息
    if blueprint is not None and seems_fishy:
        info.append(
            "  The template was looked up from an endpoint that belongs"
            f" to the blueprint {blueprint!r}."
        )
        info.append("  Maybe you did not place a template in the right folder?")
        info.append("  See https://flask.palletsprojects.com/blueprints/#templates")

    # 将所有信息记录到应用日志
    app.logger.info("\n".join(info))

