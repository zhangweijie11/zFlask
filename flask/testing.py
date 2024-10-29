from __future__ import annotations

import importlib.metadata
import typing as t
from contextlib import contextmanager
from contextlib import ExitStack
from copy import copy
from types import TracebackType
from urllib.parse import urlsplit

import werkzeug.test
from click.testing import CliRunner
from werkzeug.test import Client
from werkzeug.wrappers import Request as BaseRequest

from .cli import ScriptInfo
from .sessions import SessionMixin

if t.TYPE_CHECKING:  # pragma: no cover
    from _typeshed.wsgi import WSGIEnvironment
    from werkzeug.test import TestResponse

    from .app import Flask

# 这段代码定义了一个 EnvironBuilder 类，继承自 werkzeug.test.EnvironBuilder。主要功能是构建 WSGI 环境变量，用于测试 Flask 应用。
# 初始化方法 __init__:
# 检查 base_url、subdomain 和 url_scheme 的传递是否合理。
# 如果没有提供 base_url，则根据 app 的配置生成 base_url。
# 将路径 path 分解并重新组合为完整的 URL。
# 调用父类的 __init__ 方法完成环境变量的构建。
# 方法 json_dumps:
# 使用 app 的 JSON 序列化器将对象转换为 JSON 字符串。
class EnvironBuilder(werkzeug.test.EnvironBuilder):
    class CustomRequestContext:
        def __init__(
            self,
            app: Flask,
            path: str = "/",
            base_url: str | None = None,
            subdomain: str | None = None,
            url_scheme: str | None = None,
            *args: t.Any,
            **kwargs: t.Any,
        ) -> None:
            """
            初始化CustomRequestContext类。

            :param app: Flask应用实例。
            :param path: 请求路径，默认为根路径"/"。
            :param base_url: 基础URL，用于构建完整的请求URL。
            :param subdomain: 子域名，如果提供，则会与基础URL合并。
            :param url_scheme: URL方案（如http，https），默认从应用配置中获取。
            :param args: 位置参数，传递给父类初始化方法。
            :param kwargs: 关键字参数，传递给父类初始化方法。

            :raises AssertionError: 如果同时提供了"base_url"与"subdomain"或"url_scheme"，但未提供"http_host"。
            """
            # 确保参数传递的正确性：如果提供了base_url，则不应单独提供subdomain或url_scheme
            assert not (base_url or subdomain or url_scheme) or (
                base_url is not None
            ) != bool(
                subdomain or url_scheme
            ), 'Cannot pass "subdomain" or "url_scheme" with "base_url".'

            # 如果未提供base_url，则根据应用配置和其他参数构建
            if base_url is None:
                # 获取服务器名称作为HTTP主机名，如果没有配置，则默认为"localhost"
                http_host = app.config.get("SERVER_NAME") or "localhost"
                # 获取应用根路径
                app_root = app.config["APPLICATION_ROOT"]

                # 如果提供了子域名，将其与HTTP主机名合并
                if subdomain:
                    http_host = f"{subdomain}.{http_host}"

                # 如果没有提供URL方案，则从应用配置中获取
                if url_scheme is None:
                    url_scheme = app.config["PREFERRED_URL_SCHEME"]

                # 解析提供的路径
                url = urlsplit(path)
                # 构建基础URL
                base_url = (
                    f"{url.scheme or url_scheme}://{url.netloc or http_host}"
                    f"/{app_root.lstrip('/')}"
                )
                # 使用解析后的路径更新path参数
                path = url.path

                # 如果解析后的路径包含查询字符串，将其添加到path中
                if url.query:
                    sep = b"?" if isinstance(url.query, bytes) else "?"
                    path += sep + url.query

            # 保存应用实例
            self.app = app
            # 调用父类初始化方法，传递处理后的路径和基础URL，以及任何其他位置或关键字参数
            super().__init__(path, base_url, *args, **kwargs)

    def json_dumps(self, obj: t.Any, **kwargs: t.Any) -> str:  # type: ignore
        """
        将Python对象转换为JSON字符串。

        本函数封装了Flask应用的json.dumps方法，用于序列化Python对象到JSON格式的字符串。
        主要用途是在于利用Flask框架内部的JSON序列化机制，以保证序列化结果与框架的兼容性。

        参数:
        - obj: t.Any 类型, 待序列化的Python对象。
        - **kwargs: t.Any 类型, 可变关键字参数，传递给json.dumps函数，用于自定义序列化行为。

        返回:
        - str 类型, 序列化后的JSON字符串。
        """
        # 使用应用内部的JSON序列化方法，将Python对象转换为JSON字符串
        return self.app.json.dumps(obj, **kwargs)


_werkzeug_version = ""


def _get_werkzeug_version() -> str:
    """
    获取Werkzeug库的版本信息。

    该函数通过全局变量缓存版本信息，避免重复查询，以提高性能。

    Returns:
        str: Werkzeug库的版本号。
    """
    global _werkzeug_version

    # 检查是否已经缓存了Werkzeug的版本信息
    if not _werkzeug_version:
        # 使用importlib.metadata查询并缓存Werkzeug的版本号
        _werkzeug_version = importlib.metadata.version("werkzeug")

    # 返回缓存的Werkzeug版本号
    return _werkzeug_version


# __init__ 方法
# 初始化 FlaskClient 类实例。
# 设置默认的环境变量，包括远程地址和用户代理（包含Werkzeug版本）。
# session_transaction 方法
# 提供一个上下文管理器，用于在测试期间操作会话。
# 检查是否启用了 cookies，如果没有启用则抛出异常。
# 创建测试请求上下文，添加 cookies 到 WSGI 环境。
# 打开会话，如果会话未打开则抛出异常。
# 在上下文中保存会话，并更新 cookies。
# _copy_environ 方法
# 复制基础环境变量，并根据需要添加调试上下文。
# _request_from_builder_args 方法
# 根据传入的参数创建请求对象。
# 复制基础环境变量并构建请求。
# open 方法
# 发送请求并处理响应。
# 根据传入参数类型创建请求对象。
# 关闭上下文栈，发送请求，处理响应。
# 将新上下文添加到上下文栈。
# __enter__ 和 __exit__ 方法
# 实现上下文管理器协议。
# __enter__ 方法启用上下文保留。
# __exit__ 方法关闭上下文保留并清理上下文栈。
class FlaskClient(Client):

    application: Flask

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.preserve_context = False
        self._new_contexts: list[t.ContextManager[t.Any]] = []
        self._context_stack = ExitStack()
        self.environ_base = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": f"Werkzeug/{_get_werkzeug_version()}",
        }

    @contextmanager
    def session_transaction(
        self, *args: t.Any, **kwargs: t.Any
    ) -> t.Iterator[SessionMixin]:
        """
        创建一个上下文管理器，用于在测试期间模拟和管理会话（session）的开销和保存。

        此函数主要用于测试场景，模拟服务器请求，并在请求上下文中管理会话数据。
        它首先检查是否启用了cookie，如果没有，则抛出一个TypeError。
        然后，它创建一个测试请求上下文，将cookie添加到WSGI环境中，并打开会话。
        在执行完会话内的操作后，它创建一个响应对象，并保存会话数据到响应中。
        最后，它从响应中更新cookie信息。

        参数:
        - *args: 传递给测试请求上下文创建函数的位置参数。
        - **kwargs: 传递给测试请求上下文创建函数的关键字参数。

        返回:
        - 一个SessionMixin实例，用于在上下文中管理会话。

        异常:
        - TypeError: 如果未启用cookie。
        - RuntimeError: 如果会话后端未能打开会话。
        """
        # 检查是否启用了cookie，如果没有，则抛出TypeError
        if self._cookies is None:
            raise TypeError(
                "Cookies are disabled. Create a client with 'use_cookies=True'."
            )

        # 获取应用实例
        app = self.application
        # 创建测试请求上下文
        ctx = app.test_request_context(*args, **kwargs)
        # 将cookie添加到WSGI环境中
        self._add_cookies_to_wsgi(ctx.request.environ)

        # 在测试请求上下文中执行操作
        with ctx:
            # 打开会话
            sess = app.session_interface.open_session(app, ctx.request)

        # 如果会话未打开，则抛出RuntimeError
        if sess is None:
            raise RuntimeError("Session backend did not open a session.")

        # 在此处之前，所有操作都是为了准备和打开会话
        yield sess
        # 在此处之后，会话操作完成，开始处理响应

        # 创建响应对象
        resp = app.response_class()

        # 如果是空会话，则无需保存会话数据，直接返回
        if app.session_interface.is_null_session(sess):
            return

        # 在测试请求上下文中保存会话数据到响应中
        with ctx:
            app.session_interface.save_session(app, sess, resp)

        # 从响应中更新cookie信息
        self._update_cookies_from_response(
            ctx.request.host.partition(":")[0],
            ctx.request.path,
            resp.headers.getlist("Set-Cookie"),
        )

    def _copy_environ(self, other: WSGIEnvironment) -> WSGIEnvironment:
        """
        复制当前WSGI环境并根据情况添加自定义配置。

        此函数接受另一个WSGI环境变量作为输入，并将其与当前环境变量的基础内容合并。
        如果设置了preserve_context标志，则会在输出环境变量中添加一个自定义配置，以保留调试上下文。

        参数:
        - other: WSGIEnvironment类型，代表要合并的另一个WSGI环境变量。

        返回:
        - WSGIEnvironment类型，代表合并后的WSGI环境变量。
        """
        # 合并基础环境变量和传入的环境变量
        out = {**self.environ_base, **other}

        # 如果需要保留上下文，则在输出环境变量中添加自定义配置
        if self.preserve_context:
            out["werkzeug.debug.preserve_context"] = self._new_contexts.append

        # 返回合并后的环境变量
        return out

    def _request_from_builder_args(
        self, args: tuple[t.Any, ...], kwargs: dict[str, t.Any]
    ) -> BaseRequest:
        """
        根据给定的参数和关键字参数构建一个请求对象。

        此方法使用`EnvironBuilder`根据提供的参数生成一个请求环境，然后从中构建一个`BaseRequest`对象。
        它确保在构建过程中环境变量被正确复制和使用，并在完成后释放相关资源。

        参数:
        - args: 一个包含位置参数的元组，用于构建请求环境。
        - kwargs: 一个字典，包含关键字参数，用于构建请求环境。

        返回:
        - BaseRequest: 返回一个根据提供的参数构建的请求对象。
        """
        # 在kwargs中更新或插入'environ_base'键的值，确保使用的是复制后的环境变量
        kwargs["environ_base"] = self._copy_environ(kwargs.get("environ_base", {}))

        # 使用提供的参数和关键字参数创建EnvironBuilder实例
        builder = EnvironBuilder(self.application, *args, **kwargs)

        try:
            # 尝试从builder中获取构建好的请求对象
            return builder.get_request()
        finally:
            # 确保在退出时释放builder占用的资源
            builder.close()

    def open(
        self,
        *args: t.Any,
        buffered: bool = False,
        follow_redirects: bool = False,
        **kwargs: t.Any,
    ) -> TestResponse:
        """
        打开一个请求并返回相应的测试响应。

        该方法支持多种方式构建请求，包括直接使用环境变量构建器、字典或基础请求对象。
        它还处理上下文管理、重定向跟随以及缓冲设置。

        参数:
        - *args: 位置参数，可以是EnvironBuilder、dict或BaseRequest实例。
        - buffered: 是否缓冲响应，默认为False。
        - follow_redirects: 是否跟随重定向，默认为False。
        - **kwargs: 关键字参数，用于构建请求。

        返回:
        - TestResponse: 测试响应对象。
        """
        # 根据第一个位置参数的类型，选择不同的请求构建方式
        if args and isinstance(
            args[0], (werkzeug.test.EnvironBuilder, dict, BaseRequest)
        ):
            # 处理EnvironBuilder实例
            if isinstance(args[0], werkzeug.test.EnvironBuilder):
                builder = copy(args[0])
                builder.environ_base = self._copy_environ(builder.environ_base or {})  # type: ignore[arg-type]
                request = builder.get_request()
            # 处理字典实例
            elif isinstance(args[0], dict):
                request = EnvironBuilder.from_environ(
                    args[0], app=self.application, environ_base=self._copy_environ({})
                ).get_request()
            # 处理BaseRequest实例
            else:
                request = copy(args[0])
                request.environ = self._copy_environ(request.environ)
        else:
            # 使用builder_args构建请求
            request = self._request_from_builder_args(args, kwargs)

        # 关闭当前上下文栈
        self._context_stack.close()

        # 调用父类的open方法发送请求，并获取响应
        response = super().open(
            request,
            buffered=buffered,
            follow_redirects=follow_redirects,
        )
        # 设置响应的json模块为应用的json模块
        response.json_module = self.application.json  # type: ignore[assignment]

        # 处理新上下文，如果有，将其加入上下文栈
        while self._new_contexts:
            cm = self._new_contexts.pop()
            self._context_stack.enter_context(cm)

        # 返回构建的响应对象
        return response

    def __enter__(self) -> FlaskClient:
        """
        当进入上下文时调用此方法。

        该方法主要用于防止客户端调用的嵌套。
        如果在当前上下文中再次调用客户端，将会引发运行时错误。
        通过设置preserve_context标志，确保在进入上下文时不会丢失上下文信息。

        Raises:
            RuntimeError: 如果尝试在现有的上下文中再次调用客户端，将引发此异常。

        Returns:
            FlaskClient: 返回当前的Flask客户端实例，以便在上下文中使用。
        """
        if self.preserve_context:
            # 如果上下文已经被保存，说明当前正在尝试嵌套调用客户端，这是不被允许的
            raise RuntimeError("Cannot nest client invocations")
        # 在进入上下文时，设置标志以保存当前上下文
        self.preserve_context = True
        # 返回当前的客户端实例，以便在上下文中使用
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """
        定义上下文管理器的退出方法。

        该方法在离开上下文时被调用，负责清理资源并处理可能发生的异常。

        参数:
        - exc_type: 异常类型，如果没有异常则为None。
        - exc_value: 异常实例，如果没有异常则为None。
        - tb: 异常的traceback对象，如果没有异常则为None。

        返回:
        - None
        """
        # 设置preserve_context为False，表示不再需要保留当前上下文。
        self.preserve_context = False

        # 调用_context_stack的close方法，清理上下文栈。
        self._context_stack.close()


# 这段代码定义了一个名为 FlaskCliRunner 的类，继承自 CliRunner。主要功能如下：
# 初始化方法 __init__：
# 接受一个 Flask 应用实例 app 和其他可选参数 kwargs。
# 将 app 存储在实例变量 self.app 中。
# 调用父类 CliRunner 的初始化方法。
# 调用方法 invoke：
# 接受 cli、args 和其他可选参数 kwargs。
# 如果 cli 为 None，则使用 self.app.cli。
# 如果 kwargs 中没有 obj，则添加一个 ScriptInfo 实例，该实例的 create_app 方法返回 self.app。
# 调用父类的 invoke 方法并返回结果。
class FlaskCliRunner(CliRunner):
    def __init__(self, app: Flask, **kwargs: t.Any) -> None:
        self.app = app
        super().__init__(**kwargs)

    def invoke(  # type: ignore
        self, cli: t.Any = None, args: t.Any = None, **kwargs: t.Any
    ) -> t.Any:
        """
        自定义调用方法，用于执行命令行接口。

        此方法允许通过命令行接口（CLI）调用应用程序，提供了一种灵活的方式来配置和启动应用程序。

        参数:
        - cli: t.Any = None -- CLI对象，如果未提供，则使用应用程序的默认CLI。
        - args: t.Any = None -- 调用CLI时使用的参数，如果未提供，则使用调用时提供的参数。
        - **kwargs: t.Any -- 传递给CLI的额外关键字参数，特别地，如果其中不包含'obj'键，则会添加一个。

        返回:
        - t.Any -- 调用CLI后的返回值，具体类型取决于调用的CLI方法。
        """
        # 如果未提供cli参数，则使用应用程序的默认cli
        if cli is None:
            cli = self.app.cli

        # 如果kwargs中不包含'obj'键，则添加一个，其值为一个ScriptInfo对象
        # ScriptInfo对象包含一个创建应用程序的lambda函数，这为CLI提供了访问应用程序实例的方式
        if "obj" not in kwargs:
            kwargs["obj"] = ScriptInfo(create_app=lambda: self.app)

        # 调用父类的invoke方法，传入cli、args和更新后的kwargs
        return super().invoke(cli, args, **kwargs)
