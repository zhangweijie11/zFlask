from __future__ import annotations

import collections.abc as cabc
import os
import sys
import typing as t
import weakref
from datetime import timedelta
from inspect import iscoroutinefunction
from itertools import chain
from types import TracebackType
from urllib.parse import quote as _url_quote

import click
from werkzeug.datastructures import Headers
from werkzeug.datastructures import ImmutableDict
from werkzeug.exceptions import BadRequestKeyError
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import InternalServerError
from werkzeug.routing import BuildError
from werkzeug.routing import MapAdapter
from werkzeug.routing import RequestRedirect
from werkzeug.routing import RoutingException
from werkzeug.routing import Rule
from werkzeug.serving import is_running_from_reloader
from werkzeug.wrappers import Response as BaseResponse

from . import cli
from . import typing as ft
from .ctx import AppContext
from .ctx import RequestContext
from .globals import _cv_app
from .globals import _cv_request
from .globals import current_app
from .globals import g
from .globals import request
from .globals import request_ctx
from .globals import session
from .helpers import get_debug_flag
from .helpers import get_flashed_messages
from .helpers import get_load_dotenv
from .helpers import send_from_directory
from .sansio.app import App
from .sansio.scaffold import _sentinel
from .sessions import SecureCookieSessionInterface
from .sessions import SessionInterface
from .signals import appcontext_tearing_down
from .signals import got_request_exception
from .signals import request_finished
from .signals import request_started
from .signals import request_tearing_down
from .templating import Environment
from .wrappers import Request
from .wrappers import Response

if t.TYPE_CHECKING:  # pragma: no cover
    from _typeshed.wsgi import StartResponse
    from _typeshed.wsgi import WSGIEnvironment

    from .testing import FlaskClient
    from .testing import FlaskCliRunner

T_shell_context_processor = t.TypeVar(
    "T_shell_context_processor", bound=ft.ShellContextProcessorCallable
)
T_teardown = t.TypeVar("T_teardown", bound=ft.TeardownCallable)
T_template_filter = t.TypeVar("T_template_filter", bound=ft.TemplateFilterCallable)
T_template_global = t.TypeVar("T_template_global", bound=ft.TemplateGlobalCallable)
T_template_test = t.TypeVar("T_template_test", bound=ft.TemplateTestCallable)


def _make_timedelta(value: timedelta | int | None) -> timedelta | None:
    """
    根据输入值创建一个 timedelta 对象。

    该函数接受一个 timedelta、整数或 None 作为输入，并返回一个 timedelta 对象或 None。
    如果输入是 timedelta，直接返回该值。如果输入是整数，假设它是秒数，并创建一个具有该秒数的 timedelta 对象。
    如果输入是 None，函数也返回 None。

    参数:
    value (timedelta | int | None): 输入值，可以是 timedelta、整数或 None。

    返回:
    timedelta | None: 返回一个 timedelta 对象或 None。
    """
    # 检查输入值是否为 None 或已经是 timedelta 类型
    if value is None or isinstance(value, timedelta):
        # 如果是，直接返回该值
        return value

    # 如果输入是一个整数，创建一个具有该秒数的 timedelta 对象并返回
    return timedelta(seconds=value)


# 该 Flask 类继承自 App，并实现了一个完整的 Flask 应用程序框架。以下是主要功能的简要说明：
# 默认配置 (default_config)：定义了应用程序的默认配置项，如调试模式、会话密钥、静态文件路径等。
# 初始化方法 (__init__)：设置应用程序的基本属性，如导入名称、静态文件夹、模板文件夹等，并注册命令行接口和静态文件路由。
# 发送静态文件 (send_static_file)：处理静态文件请求，返回静态文件内容。
# 创建 Jinja 环境 (create_jinja_environment)：配置并返回 Jinja 模板环境。
# 创建 URL 适配器 (create_url_adapter)：根据请求或配置创建 URL 适配器，用于生成 URL。
# 处理 HTTP 异常 (handle_http_exception)：处理 HTTP 异常，调用异常处理器。
# 处理用户异常 (handle_user_exception)：处理用户引发的异常，调用异常处理器。
# 处理未捕获的异常 (handle_exception)：处理未捕获的异常，记录日志并返回错误响应。
# 调度请求 (dispatch_request)：根据请求的 URL 和方法调用相应的视图函数。
# 完整调度请求 (full_dispatch_request)：处理请求的完整流程，包括预处理、调度和后处理。
# 生成响应 (make_response)：将视图函数的返回值转换为 Response 对象。
# 预处理请求 (preprocess_request)：在调度请求之前执行预处理函数。
# 处理响应 (process_response)：在返回响应之前执行后处理函数。
# WSGI 应用程序入口 (wsgi_app)：处理 WSGI 请求，调用 full_dispatch_request 并返回响应。
# 可调用对象 (__call__)：使 Flask 实例可以直接作为 WSGI 应用程序调用。
# 这些方法共同构成了 Flask 应用程序的核心功能，处理从请求到响应的整个生命周期。
class Flask(App):
    default_config = ImmutableDict(
        {
            "DEBUG": None,
            "TESTING": False,
            "PROPAGATE_EXCEPTIONS": None,
            "SECRET_KEY": None,
            "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
            "USE_X_SENDFILE": False,
            "SERVER_NAME": None,
            "APPLICATION_ROOT": "/",
            "SESSION_COOKIE_NAME": "session",
            "SESSION_COOKIE_DOMAIN": None,
            "SESSION_COOKIE_PATH": None,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_SAMESITE": None,
            "SESSION_REFRESH_EACH_REQUEST": True,
            "MAX_CONTENT_LENGTH": None,
            "SEND_FILE_MAX_AGE_DEFAULT": None,
            "TRAP_BAD_REQUEST_ERRORS": None,
            "TRAP_HTTP_EXCEPTIONS": False,
            "EXPLAIN_TEMPLATE_LOADING": False,
            "PREFERRED_URL_SCHEME": "http",
            "TEMPLATES_AUTO_RELOAD": None,
            "MAX_COOKIE_SIZE": 4093,
            "PROVIDE_AUTOMATIC_OPTIONS": True,
        }
    )

    request_class: type[Request] = Request

    response_class: type[Response] = Response

    session_interface: SessionInterface = SecureCookieSessionInterface()

    def __init__(
            self,
            import_name: str,
            static_url_path: str | None = None,
            static_folder: str | os.PathLike[str] | None = "static",
            static_host: str | None = None,
            host_matching: bool = False,
            subdomain_matching: bool = False,
            template_folder: str | os.PathLike[str] | None = "templates",
            instance_path: str | None = None,
            instance_relative_config: bool = False,
            root_path: str | None = None,
    ):
        """
        初始化应用程序对象。

        参数:
        - import_name (str): 应用程序的导入名称。
        - static_url_path (str | None): 静态文件的URL路径。默认为 None。
        - static_folder (str | os.PathLike[str] | None): 静态文件的目录。默认为 "static"。
        - static_host (str | None): 静态文件的主机名。默认为 None。
        - host_matching (bool): 是否匹配主机名。默认为 False。
        - subdomain_matching (bool): 是否匹配子域名。默认为 False。
        - template_folder (str | os.PathLike[str] | None): 模板文件的目录。默认为 "templates"。
        - instance_path (str | None): 实例文件的路径。默认为 None。
        - instance_relative_config (bool): 是否相对实例文件路径加载配置。默认为 False。
        - root_path (str | None): 应用程序的根路径。默认为 None。
        """
        # 调用父类的初始化方法，传递所有初始化参数
        super().__init__(
            import_name=import_name,
            static_url_path=static_url_path,
            static_folder=static_folder,
            static_host=static_host,
            host_matching=host_matching,
            subdomain_matching=subdomain_matching,
            template_folder=template_folder,
            instance_path=instance_path,
            instance_relative_config=instance_relative_config,
            root_path=root_path,
        )

        # 初始化命令行接口（CLI）对象
        self.cli = cli.AppGroup()

        # 设置CLI的名称为应用程序的名称
        self.cli.name = self.name

        # 如果应用程序有静态文件夹，则进行静态文件的URL规则添加
        if self.has_static_folder:
            # 确保static_host和host_matching的组合是有效的
            assert (
                    bool(static_host) == host_matching
            ), "Invalid static_host/host_matching combination"

            # 添加静态文件的URL规则
            self.add_url_rule(
                f"{self.static_url_path}/<path:filename>",
                endpoint="static",
                host=static_host,
                view_func=lambda **kw: self_ref().send_static_file(**kw),  # type: ignore # noqa: B950
            )

    def get_send_file_max_age(self, filename: str | None) -> int | None:
        """
        获取发送文件的最大缓存时间。

        本函数根据应用程序配置中的默认值来确定文件发送时的最大缓存时间。
        这个默认值可以是None，表示不进行缓存；也可以是一个timedelta对象，表示缓存时间；
        或者是一个整数，直接表示缓存的秒数。

        参数:
        filename (str | None): 文件名，本函数中未使用，但保持参数存在以符合接口要求。

        返回:
        int | None: 文件的最大缓存时间，以秒为单位。如果配置值为None，则返回None，表示不进行缓存。
        """
        # 获取应用程序配置中的文件发送缓存时间默认值
        value = current_app.config["SEND_FILE_MAX_AGE_DEFAULT"]

        # 如果默认值为None，则返回None，表示不进行缓存
        if value is None:
            return None

        # 如果默认值是timedelta类型，则将其转换为秒数并返回
        if isinstance(value, timedelta):
            return int(value.total_seconds())

        # 如果默认值是其他类型，则直接返回其值，这里忽略了类型检查
        return value  # type: ignore[no-any-return]

    def send_static_file(self, filename: str) -> Response:

        if not self.has_static_folder:
            raise RuntimeError("'static_folder' must be set to serve static_files.")

        max_age = self.get_send_file_max_age(filename)
        return send_from_directory(
            t.cast(str, self.static_folder), filename, max_age=max_age
        )

    def open_resource(
            self, resource: str, mode: str = "rb", encoding: str | None = None
    ) -> t.IO[t.AnyStr]:
        """
        打开指定资源。

        该方法允许以只读模式打开资源。支持的模式包括：
        - "r": 以文本模式读取。
        - "rt": 同 "r"，显式指定文本模式。
        - "rb": 以二进制模式读取。

        :param resource: 要打开的资源名称。
        :param mode: 打开文件的模式，默认为 "rb"。
        :param encoding: 文件编码，当以文本模式打开时需要指定。
        :return: 返回一个文件对象。
        :raises ValueError: 如果尝试使用不支持的模式打开资源。
        """
        # 检查模式是否为支持的只读模式
        if mode not in {"r", "rt", "rb"}:
            raise ValueError("Resources can only be opened for reading.")

        # 构造资源的完整路径
        path = os.path.join(self.root_path, resource)

        # 根据模式打开文件并返回文件对象
        if mode == "rb":
            return open(path, mode)

        # 以文本模式打开文件并返回文件对象
        return open(path, mode, encoding=encoding)

    def open_instance_resource(
        self, resource: str, mode: str = "rb", encoding: str | None = "utf-8"
    ) -> t.IO[t.AnyStr]:
        """
        打开实例资源文件。

        该方法用于打开位于实例路径下的指定资源文件，并根据给定的模式和编码方式返回文件对象。

        参数:
        - resource (str): 资源文件的名称。
        - mode (str): 文件的打开模式，默认为 "rb"（二进制读取）。
        - encoding (str | None): 文件的编码方式，默认为 "utf-8"，如果模式中包含 "b" 则编码方式无效。

        返回:
        - t.IO[t.AnyStr]: 返回一个文件对象，根据模式可以进行读取或写入操作。

        说明:
        - 该方法首先会将实例路径与资源文件名拼接，以获取资源文件的完整路径。
        - 如果模式中包含 "b"，则以二进制方式打开文件，此时编码参数将被忽略。
        - 否则，以文本方式打开文件，并使用指定的编码方式。
        """
        # 拼接实例路径与资源文件名，获取资源文件的完整路径
        path = os.path.join(self.instance_path, resource)

        # 根据模式中是否包含 "b"，选择合适的方式打开文件
        if "b" in mode:
            return open(path, mode)

        return open(path, mode, encoding=encoding)

    def create_jinja_environment(self) -> Environment:
        """
        创建并返回一个配置好的Jinja2环境。

        此方法用于设置Jinja2模板引擎的环境。它首先根据当前应用的配置，
        设置Jinja2的各种选项，然后创建一个Jinja2环境实例，并返回该实例。

        Returns:
            Environment: 一个配置好的Jinja2环境实例。
        """
        # 复制Jinja2配置选项，以避免直接修改应用的配置
        options = dict(self.jinja_options)

        # 如果配置中未指定autoescape选项，则使用默认的自动转义选择函数
        if "autoescape" not in options:
            options["autoescape"] = self.select_jinja_autoescape

        # 如果配置中未指定auto_reload选项，则根据模板自动重载配置或调试模式决定是否自动重载模板
        if "auto_reload" not in options:
            auto_reload = self.config["TEMPLATES_AUTO_RELOAD"]

            # 如果模板自动重载配置未设置，则根据是否是调试模式来决定
            if auto_reload is None:
                auto_reload = self.debug

            options["auto_reload"] = auto_reload

        # 使用上述配置创建Jinja2环境实例
        rv = self.jinja_environment(self, **options)

        # 更新Jinja2环境的全局变量，使其包含Flask应用中的一些有用的方法和对象
        rv.globals.update(
            url_for=self.url_for,
            get_flashed_messages=get_flashed_messages,
            config=self.config,
            session=session,
            g=g,
        )

        # 设置Jinja2环境的JSON序列化函数为应用配置中指定的函数
        rv.policies["json.dumps_function"] = self.json.dumps

        # 返回配置好的Jinja2环境实例
        return rv
    def create_url_adapter(self, request: Request | None) -> MapAdapter | None:
        """
        根据请求创建一个URL适配器。

        此函数用于根据给定的请求对象生成一个MapAdapter实例，该实例用于解析或构建URL。
        如果请求对象为空，则根据配置信息创建一个通用的MapAdapter实例。

        参数:
        - request: 一个可选的Request对象，表示传入的HTTP请求。

        返回:
        - 如果请求对象不为空且配置信息允许，返回一个绑定到请求环境的MapAdapter实例。
        - 如果请求对象为空但配置了服务器名称，返回一个基于配置信息的MapAdapter实例。
        - 如果以上条件都不满足，返回None。
        """

        # 检查请求对象是否提供，如果提供，则根据子域匹配配置确定子域值
        if request is not None:
            if not self.subdomain_matching:
                subdomain = self.url_map.default_subdomain or None
            else:
                subdomain = None

            # 使用请求的环境变量和配置信息绑定URL映射，生成适配器
            return self.url_map.bind_to_environ(
                request.environ,
                server_name=self.config["SERVER_NAME"],
                subdomain=subdomain,
            )

        # 如果请求对象未提供但配置了服务器名称，则根据应用配置信息绑定URL映射
        if self.config["SERVER_NAME"] is not None:
            return self.url_map.bind(
                self.config["SERVER_NAME"],
                script_name=self.config["APPLICATION_ROOT"],
                url_scheme=self.config["PREFERRED_URL_SCHEME"],
            )

        # 如果以上条件都不满足，返回None
        return None

    def raise_routing_exception(self, request: Request) -> t.NoReturn:
        """
        在特定条件下引发请求的路由异常。

        此函数检查当前请求的路由异常是否应该被引发。如果当前环境不是调试模式，
        或者请求的路由异常不是RequestRedirect类型，或者异常状态码是307或308，
        或者请求的方法是GET、HEAD或OPTIONS之一，则直接引发原始路由异常。
        否则，在调试模式下，如果路由异常是RequestRedirect类型且状态码不是307或308，
        并且请求方法不是GET、HEAD或OPTIONS之一，则引发FormDataRoutingRedirect异常。

        参数:
        request (Request): 当前请求对象，包含路由信息和异常。

        返回:
        该函数不返回，总是引发异常。
        """
        # 检查是否满足直接引发路由异常的条件
        if (
                not self.debug
                or not isinstance(request.routing_exception, RequestRedirect)
                or request.routing_exception.code in {307, 308}
                or request.method in {"GET", "HEAD", "OPTIONS"}
        ):
            raise request.routing_exception  # type: ignore[misc]

        # 在调试模式下，对于特定的重定向异常，引发FormDataRoutingRedirect异常
        from .debughelpers import FormDataRoutingRedirect

        raise FormDataRoutingRedirect(request)

    def update_template_context(self, context: dict[str, t.Any]) -> None:
        """
        更新模板上下文。

        遍历请求的蓝本列表，依次更新模板上下文。如果存在请求，将反向遍历请求的蓝本，
        以便蓝本的模板上下文处理器可以按照输入的顺序应用。此方法不会返回任何值，
        但会直接更新传入的上下文字典。

        参数:
        context: 一个字典，表示模板的上下文，将被更新。

        返回:
        无返回值。
        """
        # 初始化蓝本名称列表，默认包含一个None值
        names: t.Iterable[str | None] = (None,)
        #  遍历请求的蓝本列表，依次更新模板上下文
        if request:
            names = chain(names, reversed(request.blueprints))

        # 复制原始上下文，以备后续合并
        orig_ctx = context.copy()

        # 遍历蓝本名称列表和模板上下文处理器，更新上下文
        for name in names:
            if name in self.template_context_processors:
                for func in self.template_context_processors[name]:
                    context.update(self.ensure_sync(func)())

        # 最后更新原始上下文，确保所有处理器都已应用
        context.update(orig_ctx)

    def make_shell_context(self) -> dict[str, t.Any]:
        """
        创建并返回一个shell上下文环境。

        该方法主要用于构建一个包含应用上下文和全局变量的字典，用于在shell环境中进行交互。
        它首先创建一个包含应用实例和全局变量g的字典，然后遍历所有注册的shell上下文处理器，
        将它们的返回值合并到上下文字典中，最终返回这个字典。

        Returns:
            dict[str, t.Any]: 包含应用上下文和全局变量的字典，用于shell环境。
        """
        # 初始化shell上下文字典，包含应用实例和全局变量g
        rv = {"app": self, "g": g}
        # 遍历shell上下文处理器，更新上下文
        for processor in self.shell_context_processors:
            rv.update(processor())
        return rv

    def run(
            self,
            host: str | None = None,
            port: int | None = None,
            debug: bool | None = None,
            load_dotenv: bool = True,
            **options: t.Any,
    ) -> None:
        """
        运行Flask应用程序。

        该方法允许通过指定主机、端口、调试模式等选项来启动应用。
        它还会根据环境变量和传入参数来配置应用的运行环境。

        参数:
            host (str | None): 应用监听的主机接口。
            port (int | None): 应用监听的端口。
            debug (bool | None): 是否启用调试模式。
            load_dotenv (bool): 是否加载环境变量文件。
            **options (t.Any): 其他传递给服务器的选项。
        """
        # 检查是否从CLI运行，如果是且不是在重载器中运行，则显示警告并返回
        if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
            if not is_running_from_reloader():
                click.secho(
                    " * Ignoring a call to 'app.run()' that would block"
                    " the current 'flask' CLI command.\n"
                    "   Only call 'app.run()' in an 'if __name__ =="
                    ' "__main__"\' guard.',
                    fg="red",
                )

            return

        # 加载环境变量，如果FLASK_DEBUG设置，则设置调试标志
        if get_load_dotenv(load_dotenv):
            cli.load_dotenv()

            if "FLASK_DEBUG" in os.environ:
                self.debug = get_debug_flag()

        # 如果提供了debug参数，则根据其值设置调试模式
        if debug is not None:
            self.debug = bool(debug)

        # 处理服务器名称配置，以确定主机和端口
        server_name = self.config.get("SERVER_NAME")
        sn_host = sn_port = None

        if server_name:
            sn_host, _, sn_port = server_name.partition(":")

        # 根据配置或默认值确定主机和端口
        if not host:
            if sn_host:
                host = sn_host
            else:
                host = "127.0.0.1"

        if port or port == 0:
            port = int(port)
        elif sn_port:
            port = int(sn_port)
        else:
            port = 5000

        # 设置运行选项，默认启用重载器、调试器和多线程模式
        options.setdefault("use_reloader", self.debug)
        options.setdefault("use_debugger", self.debug)
        options.setdefault("threaded", True)

        # 显示服务器启动横幅
        cli.show_server_banner(self.debug, self.name)

        # 导入并运行简易服务器
        from werkzeug.serving import run_simple

        try:
            run_simple(t.cast(str, host), port, self, **options)
        finally:
            # 重置首次请求标志
            self._got_first_request = False

    def test_client(self, use_cookies: bool = True, **kwargs: t.Any) -> FlaskClient:
        """
        创建一个测试客户端对象。

        此方法用于生成一个测试客户端实例，以便开发者可以进行HTTP请求的模拟和测试。
        它支持自定义是否使用cookies以及任意的额外参数。

        参数:
        - use_cookies: 是否在测试客户端中启用cookies，默认为True。
        - **kwargs: 任意额外的关键字参数，允许开发者传入特定的测试配置。

        返回:
        返回一个FlaskClient实例，用于模拟HTTP请求和测试。
        """
        # 检查是否已经设置了测试客户端类，如果没有，则使用默认的FlaskClient类。
        cls = self.test_client_class
        if cls is None:
            from .testing import FlaskClient as cls
        # 创建并返回测试客户端实例。
        return cls(  # type: ignore
            self, self.response_class, use_cookies=use_cookies, **kwargs
        )

    def test_cli_runner(self, **kwargs: t.Any) -> FlaskCliRunner:
        """
        创建一个测试命令行应用程序接口的FlaskCliRunner实例。

        此方法允许通过命令行与应用程序进行交互，以便于测试和调试目的。它接受可变关键字参数以支持不同的测试场景。

        参数:
        - **kwargs: t.Any: 接受任意关键字参数，提供给FlaskCliRunner实例。

        返回:
        - FlaskCliRunner: 一个FlaskCliRunner实例，用于运行命令行应用程序接口测试。
        """
        # 获取测试命令行运行器类，如果未指定，则默认使用FlaskCliRunner
        cls = self.test_cli_runner_class

        # 如果未指定测试命令行运行器类，从.testing模块导入FlaskCliRunner作为默认类
        if cls is None:
            from .testing import FlaskCliRunner as cls

        # 使用当前测试实例和任何关键字参数创建并返回测试命令行运行器实例
        return cls(self, **kwargs)  # type: ignore

    def handle_http_exception(
            self, e: HTTPException
    ) -> HTTPException | ft.ResponseReturnValue:
        """
        处理HTTP异常。

        该方法主要用于处理发生的HTTP异常。它首先检查异常的代码是否为空，
        如果为空则直接返回异常。接着检查异常是否是RoutingException类型，
        如果是则同样直接返回。之后，尝试找到与异常对应的处理程序，
        如果找到了，则调用该处理程序来处理异常，否则直接返回异常。

        参数:
        - e: 发生的HTTP异常。

        返回:
        - 处理后的HTTP异常或响应结果。
        """
        # 检查异常代码是否为空，如果为空则直接返回异常
        if e.code is None:
            return e

        # 检查异常是否是RoutingException类型，如果是则直接返回
        if isinstance(e, RoutingException):
            return e

        # 尝试找到与异常对应的处理程序
        handler = self._find_error_handler(e, request.blueprints)

        # 如果没有找到处理程序，则直接返回异常
        if handler is None:
            return e

        # 调用找到的处理程序来处理异常，并确保处理是同步的
        return self.ensure_sync(handler)(e)  # type: ignore[no-any-return]

    def handle_user_exception(
            self, e: Exception
    ) -> HTTPException | ft.ResponseReturnValue:
        """
        处理用户引发的异常。

        此函数负责根据异常类型和当前配置决定如何处理异常。
        它可以返回一个HTTPException用于直接响应给客户端，
        或者返回一个ResponseReturnValue，具体取决于异常类型和配置。

        参数:
        - e: Exception - 被捕获的异常实例。

        返回:
        - HTTPException | ft.ResponseReturnValue - 根据异常类型和配置返回相应的处理结果。
        """

        # 当异常为BadRequestKeyError类型且处于调试模式或配置中设置了捕获此类错误时，显示异常信息。
        if isinstance(e, BadRequestKeyError) and (
                self.debug or self.config["TRAP_BAD_REQUEST_ERRORS"]
        ):
            e.show_exception = True

        # 如果异常是HTTPException类型且不满足特定条件（由trap_http_exception方法判断），则调用handle_http_exception方法处理。
        if isinstance(e, HTTPException) and not self.trap_http_exception(e):
            return self.handle_http_exception(e)

        # 尝试找到针对当前异常的错误处理函数。
        handler = self._find_error_handler(e, request.blueprints)

        # 如果没有找到合适的错误处理函数，则重新抛出异常。
        if handler is None:
            raise

        # 使用找到的错误处理函数处理异常，并确保处理是同步执行的。
        return self.ensure_sync(handler)(e)  # type: ignore[no-any-return]

    def handle_exception(self, e: Exception) -> Response:
        """
        处理异常并生成相应的响应。

        该方法用于捕获和处理应用程序中未捕获的异常。它首先发送一个请求异常信号，
        然后根据配置决定是否传播异常。如果不传播异常，它会记录异常并生成一个内部服务器错误响应。

        参数:
        - e: Exception - 发生的异常实例。

        返回:
        - Response - 根据异常生成的响应对象。
        """
        # 获取当前异常信息
        exc_info = sys.exc_info()
        # 发送请求异常信号
        got_request_exception.send(self, _async_wrapper=self.ensure_sync, exception=e)
        # 获取是否传播异常的配置
        propagate = self.config["PROPAGATE_EXCEPTIONS"]

        # 如果未设置传播异常配置，根据测试或调试模式决定
        if propagate is None:
            propagate = self.testing or self.debug

        # 根据配置决定是否传播异常
        if propagate:
            # 如果当前异常信息与传入的异常一致，重新抛出异常
            if exc_info[1] is e:
                raise
            # 否则，直接抛出传入的异常
            raise e

        # 记录异常信息
        self.log_exception(exc_info)
        # 创建InternalServerError实例
        server_error: InternalServerError | ft.ResponseReturnValue
        server_error = InternalServerError(original_exception=e)
        # 查找错误处理程序
        handler = self._find_error_handler(server_error, request.blueprints)

        # 如果找到处理程序，使用它处理错误
        if handler is not None:
            server_error = self.ensure_sync(handler)(server_error)

        # 最终化请求并返回响应
        return self.finalize_request(server_error, from_error_handler=True)

    def log_exception(
            self,
            exc_info: (tuple[type, BaseException, TracebackType] | tuple[None, None, None]),
    ) -> None:
        """
        日志记录异常信息。

        该方法用于记录发生在一个请求处理过程中的异常信息。它将使用配置的logger记录一个错误消息，
        并包含引发异常的请求路径和方法信息。此外，如果提供了异常信息（exc_info），它将被用来
        生成更详细的异常追踪信息。

        参数:
        - exc_info: 一个元组，包含异常类型、异常实例和异常追踪对象，或者全部为None。
                    当没有异常发生时，该元组应为(None, None, None)。

        返回值:
        无返回值。
        """
        # 记录异常日志，包含请求路径和方法信息，以及可选的异常追踪信息
        self.logger.error(
            f"Exception on {request.path} [{request.method}]", exc_info=exc_info
        )

    def dispatch_request(self) -> ft.ResponseReturnValue:
        """
        处理请求以生成响应。

        此方法负责根据当前请求的上下文，选择正确的视图函数执行，并处理特定情况下的异常或特殊情况。

        :return: 返回视图函数的执行结果，作为HTTP响应的主体。
        """
        # 获取当前请求对象
        req = request_ctx.request

        # 如果请求有路由异常，则抛出异常
        if req.routing_exception is not None:
            self.raise_routing_exception(req)

        # 忽略类型检查警告，获取当前请求的路由规则
        rule: Rule = req.url_rule  # type: ignore[assignment]

        # 如果路由规则提供自动选项且请求方法为OPTIONS，则返回默认的OPTIONS响应
        if (
                getattr(rule, "provide_automatic_options", False)
                and req.method == "OPTIONS"
        ):
            return self.make_default_options_response()

        # 忽略类型检查警告，获取视图函数的参数
        view_args: dict[str, t.Any] = req.view_args  # type: ignore[assignment]

        # 根据路由规则的端点，同步执行相应的视图函数，并返回结果
        return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)  # type: ignore[no-any-return]

    def full_dispatch_request(self) -> Response:
        """
        完整处理请求的函数。

        该函数负责处理从请求开始到结束的所有步骤，并返回相应的响应。

        Returns:
            Response: 处理请求后生成的响应对象。
        """
        # 标记已接收到第一个请求
        self._got_first_request = True

        try:
            # 在请求开始时发送信号，允许异步处理
            request_started.send(self, _async_wrapper=self.ensure_sync)
            # 预处理请求
            rv = self.preprocess_request()
            # 如果预处理没有返回结果，则继续处理请求
            if rv is None:
                rv = self.dispatch_request()
        except Exception as e:
            # 捕获并处理用户引发的异常
            rv = self.handle_user_exception(e)
        # 最终处理请求并返回响应
        return self.finalize_request(rv)

    def finalize_request(
            self,
            rv: ft.ResponseReturnValue | HTTPException,
            from_error_handler: bool = False,
    ) -> Response:
        # 处理响应
        response = self.make_response(rv)
        try:
            # 发送请求完成信号
            response = self.process_response(response)
            request_finished.send(
                self, _async_wrapper=self.ensure_sync, response=response
            )
        except Exception:
            if not from_error_handler:
                raise
            self.logger.exception(
                "Request finalizing failed with an error while handling an error"
            )
        return response

    def make_default_options_response(self) -> Response:
        """
        创建并返回一个默认的OPTIONS请求响应。

        该方法首先获取当前请求上下文的URL适配器，然后查询该适配器允许的HTTP方法。
        随后，创建一个响应对象，并将允许的HTTP方法设置为响应的允许方法。

        Returns:
            Response: 包含允许的HTTP方法的默认OPTIONS响应。
        """
        # 获取当前请求上下文的URL适配器
        adapter = request_ctx.url_adapter

        # 获取适配器允许的HTTP方法
        methods = adapter.allowed_methods()  # type: ignore[union-attr]

        # 创建一个空的响应对象
        rv = self.response_class()

        # 更新响应对象的允许方法
        rv.allow.update(methods)

        # 返回配置好的响应对象
        return rv

    def ensure_sync(self, func: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
        """
        确保给定的函数在同步环境中可以执行。

        如果传入的函数是一个异步函数，它会被转换为一个同步函数，以便在同步环境中调用。
        如果传入的函数已经是同步的，那么不做任何转换直接返回。

        参数:
        - func: t.Callable[..., t.Any]: 一个可调用对象，可以接受任意参数并返回任意类型。

        返回:
        - t.Callable[..., t.Any]: 经过转换后的同步函数，或者原封不动的同步函数。
        """
        # 检查传入的函数是否为异步函数
        if iscoroutinefunction(func):
            # 如果是异步函数，使用async_to_sync方法将其转换为同步函数
            return self.async_to_sync(func)

        # 如果已经是同步函数，直接返回该函数
        return func
    def async_to_sync(
            self, func: t.Callable[..., t.Coroutine[t.Any, t.Any, t.Any]]
    ) -> t.Callable[..., t.Any]:
        """
        将异步视图函数转换为同步视图函数。

        当需要在不支持异步的环境中运行异步视图函数时，此方法很有用。
        它使用 asgiref 库中的 async_to_sync 函数来执行转换。

        参数:
        - func: 一个异步视图函数，可以接受任意参数并返回一个任意类型的协程。

        返回:
        - 一个同步版本的视图函数，可以接受同样的参数并返回相同的类型。

        异常:
        - RuntimeError: 如果没有安装 asgiref 库，将引发此异常。
        """
        try:
            # 尝试导入 asgiref 库中的 async_to_sync 函数
            from asgiref.sync import async_to_sync as asgiref_async_to_sync
        except ImportError:
            # 如果导入失败，提示用户需要安装 Flask 的 'async' 额外组件
            raise RuntimeError(
                "Install Flask with the 'async' extra in order to use async views."
            ) from None

        # 返回转换后的同步视图函数
        return asgiref_async_to_sync(func)

    def url_for(
            self,
            /,
            endpoint: str,
            *,
            _anchor: str | None = None,
            _method: str | None = None,
            _scheme: str | None = None,
            _external: bool | None = None,
            **values: t.Any,
    ) -> str:
        """
        生成指定端点的URL。

        :param endpoint: 端点名称，用于生成URL。
        :param _anchor: 锚点，如果指定，将添加到URL末尾。
        :param _method: HTTP方法，用于生成URL。
        :param _scheme: URL的方案（如http、https）。
        :param _external: 是否生成绝对URL。
        :param values: 其他用于生成URL的参数。
        :return: 生成的URL字符串。
        :raises RuntimeError: 如果无法在当前上下文中生成URL。
        :raises ValueError: 如果'_scheme'被指定但'_external'为False。
        """
        # 获取当前请求上下文
        req_ctx = _cv_request.get(None)

        # 如果存在请求上下文，从中获取URL适配器和蓝图名称
        if req_ctx is not None:
            url_adapter = req_ctx.url_adapter
            blueprint_name = req_ctx.request.blueprint

            # 处理相对端点，将其转换为绝对端点
            if endpoint[:1] == ".":
                if blueprint_name is not None:
                    endpoint = f"{blueprint_name}{endpoint}"
                else:
                    endpoint = endpoint[1:]

            # 确定是否需要生成外部URL
            if _external is None:
                _external = _scheme is not None
        else:
            # 如果没有请求上下文，尝试从应用上下文中获取URL适配器
            app_ctx = _cv_app.get(None)

            if app_ctx is not None:
                url_adapter = app_ctx.url_adapter
            else:
                # 如果没有应用上下文，创建一个新的URL适配器
                url_adapter = self.create_url_adapter(None)

            # 如果无法创建URL适配器，抛出运行时错误
            if url_adapter is None:
                raise RuntimeError(
                    "Unable to build URLs outside an active request"
                    " without 'SERVER_NAME' configured. Also configure"
                    " 'APPLICATION_ROOT' and 'PREFERRED_URL_SCHEME' as"
                    " needed."
                )

            # 默认生成外部URL
            if _external is None:
                _external = True

        # 如果指定了方案但不要求外部URL，抛出值错误
        if _scheme is not None and not _external:
            raise ValueError("When specifying '_scheme', '_external' must be True.")

        # 注入URL默认值
        self.inject_url_defaults(endpoint, values)

        # 尝试生成URL
        try:
            rv = url_adapter.build(  # type: ignore[union-attr]
                endpoint,
                values,
                method=_method,
                url_scheme=_scheme,
                force_external=_external,
            )
        except BuildError as error:
            # 如果生成URL失败，更新参数并调用错误处理函数
            values.update(
                _anchor=_anchor, _method=_method, _scheme=_scheme, _external=_external
            )
            return self.handle_url_build_error(error, endpoint, values)

        # 如果指定了锚点，将其添加到URL末尾
        if _anchor is not None:
            _anchor = _url_quote(_anchor, safe="%!#$&'()*+,/:;=?@")
            rv = f"{rv}#{_anchor}"

        # 返回生成的URL
        return rv

    def make_response(self, rv: ft.ResponseReturnValue) -> Response:
        """
        将视图函数的返回值转换为一个标准的Response对象。

        参数:
        - rv: 视图函数的返回值，可以是一个Response对象、一个字符串、一个字典、一个列表或一个可迭代对象。

        返回:
        - 一个标准的Response对象。

        此函数首先检查视图函数的返回值类型，并根据其类型进行相应的处理，以确保最终返回一个标准的Response对象。
        """

        # 初始化状态码和头部信息变量
        status = headers = None

        # 如果返回值是一个元组，则根据元组长度进一步处理
        if isinstance(rv, tuple):
            len_rv = len(rv)

            # 根据元组长度和内容，解析出响应体、状态码和头部信息
            if len_rv == 3:
                rv, status, headers = rv  # type: ignore[misc]
            elif len_rv == 2:
                if isinstance(rv[1], (Headers, dict, tuple, list)):
                    rv, headers = rv
                else:
                    rv, status = rv  # type: ignore[assignment,misc]
            else:
                raise TypeError(
                    "The view function did not return a valid response tuple."
                    " The tuple must have the form (body, status, headers),"
                    " (body, status), or (body, headers)."
                )

        # 如果返回值为空，则抛出异常
        if rv is None:
            raise TypeError(
                f"The view function for {request.endpoint!r} did not"
                " return a valid response. The function either returned"
                " None or ended without a return statement."
            )

        # 如果返回值不是Response类的实例，则根据其类型进行转换
        if not isinstance(rv, self.response_class):
            if isinstance(rv, (str, bytes, bytearray)) or isinstance(rv, cabc.Iterator):
                rv = self.response_class(
                    rv,
                    status=status,
                    headers=headers,  # type: ignore[arg-type]
                )
                status = headers = None
            elif isinstance(rv, (dict, list)):
                rv = self.json.response(rv)
            elif isinstance(rv, BaseResponse) or callable(rv):
                try:
                    rv = self.response_class.force_type(
                        rv,  # type: ignore[arg-type]
                        request.environ,
                    )
                except TypeError as e:
                    raise TypeError(
                        f"{e}\nThe view function did not return a valid"
                        " response. The return type must be a string,"
                        " dict, list, tuple with headers or status,"
                        " Response instance, or WSGI callable, but it"
                        f" was a {type(rv).__name__}."
                    ).with_traceback(sys.exc_info()[2]) from None
            else:
                raise TypeError(
                    "The view function did not return a valid"
                    " response. The return type must be a string,"
                    " dict, list, tuple with headers or status,"
                    " Response instance, or WSGI callable, but it was a"
                    f" {type(rv).__name__}."
                )

        # 强制转换类型，确保rv是一个Response对象
        rv = t.cast(Response, rv)

        # 如果状态码不为空，则设置Response对象的状态码
        if status is not None:
            if isinstance(status, (str, bytes, bytearray)):
                rv.status = status
            else:
                rv.status_code = status

        # 如果头部信息不为空，则更新Response对象的头部信息
        if headers:
            rv.headers.update(headers)  # type: ignore[arg-type]

        # 返回最终构建的Response对象
        return rv

    def preprocess_request(self) -> ft.ResponseReturnValue | None:
        """
        预处理请求函数，在请求分发到对应的视图函数之前执行。

        本函数主要进行两部分预处理：
        1. URL值预处理：根据请求的蓝图（blueprints）逆序遍历，查找并执行注册的URL值预处理器。
        2. 请求前预处理：同样根据蓝图逆序遍历，查找并执行注册的请求前处理函数。

        如果任何请求前处理函数返回了一个非None值，则会终止后续处理，并直接返回该值。

        参数:
        无

        返回:
        可能返回一个响应值或None，具体取决于请求前处理函数的执行结果。
        """
        # 准备蓝图名称列表，用于后续的预处理查找
        names = (None, *reversed(request.blueprints))
        # 预处理URL值
        for name in names:
            if name in self.url_value_preprocessors:
                for url_func in self.url_value_preprocessors[name]:
                    url_func(request.endpoint, request.view_args)

        # 请求前预处理
        for name in names:
            if name in self.before_request_funcs:
                for before_func in self.before_request_funcs[name]:
                    rv = self.ensure_sync(before_func)()

                    if rv is not None:
                        return rv  # type: ignore[no-any-return]

        # 如果没有执行任何请求前处理函数，或者所有函数均未返回值，则返回None
        return None

    def process_response(self, response: Response) -> Response:
        """
        处理响应。

        该方法主要用于处理在请求处理之后，发送响应之前对响应对象进行一系列的处理和修改。
        它会调用一系列注册的处理函数来对响应对象进行处理，然后保存会话（如果需要的话）。

        参数:
        - response: Response类型的对象，代表当前请求的响应。

        返回:
        - 处理后的Response对象。
        """

        # 获取当前的请求上下文对象
        ctx = request_ctx._get_current_object()  # type: ignore[attr-defined]

        # 调用当前请求上下文中注册的所有请求后处理函数
        for func in ctx._after_request_functions:
            response = self.ensure_sync(func)(response)

        # 调用按照蓝图和应用范围注册的请求后处理函数
        for name in chain(request.blueprints, (None,)):
            if name in self.after_request_funcs:
                for func in reversed(self.after_request_funcs[name]):
                    response = self.ensure_sync(func)(response)

        # 如果当前会话不是空会话，则保存会话
        if not self.session_interface.is_null_session(ctx.session):
            self.session_interface.save_session(self, ctx.session, response)

        return response

    def do_teardown_request(
            self,
            exc: BaseException | None = _sentinel,  # type: ignore[assignment]
    ) -> None:
        """
        执行请求结束时的清理工作。

        该方法在请求上下文结束时调用，用于执行注册的清理函数。它接受一个可选的异常参数，
        该参数表示是否有一个异常结束了请求。如果请求是正常结束的，这个参数将被省略。

        参数:
        - exc: 可选的BaseException或None，默认为_sentinel。表示请求结束时是否发生了异常。
        """
        # 如果未提供exc参数或其值为_sentinel，则从当前的异常信息中获取。
        if exc is _sentinel:
            exc = sys.exc_info()[1]

        # 遍历请求的蓝本和None，执行每个蓝本的清理函数。
        for name in chain(request.blueprints, (None,)):
            # 检查当前蓝本是否有注册的清理函数。
            if name in self.teardown_request_funcs:
                # 逆序执行清理函数，因为后注册的函数应该先执行。
                for func in reversed(self.teardown_request_funcs[name]):
                    # 确保清理函数同步执行。
                    self.ensure_sync(func)(exc)

        # 触发请求结束的信号，允许其他部分执行额外的清理工作。
        request_tearing_down.send(self, _async_wrapper=self.ensure_sync, exc=exc)

    def do_teardown_appcontext(
            self,
            exc: BaseException | None = _sentinel,  # type: ignore[assignment]
    ) -> None:
        """
        执行应用程序上下文的拆除操作。

        该方法在应用程序上下文被弹出时调用，用于执行注册的拆除函数。
        它确保以适当的顺序调用所有注册的拆除函数，并处理可能发生的异常。

        参数:
        - exc: 可选参数，表示可能发生的异常。如果未提供，则从系统的异常信息中获取。

        返回:
        该方法不返回任何值。
        """
        # 如果未提供异常信息，则从系统异常信息中获取
        if exc is _sentinel:
            exc = sys.exc_info()[1]

        # 逆序调用所有注册的拆除函数，并传递当前异常信息
        for func in reversed(self.teardown_appcontext_funcs):
            self.ensure_sync(func)(exc)

        # 发送信号，通知应用程序上下文正在被拆除
        appcontext_tearing_down.send(self, _async_wrapper=self.ensure_sync, exc=exc)

    def app_context(self) -> AppContext:
        """
        创建并返回一个AppContext实例。

        该方法用于生成一个AppContext对象，该对象包含了应用上下文信息，
        通过返回这个对象，可以方便地在应用中共享和访问上下文数据。

        :return: AppContext实例，包含了应用上下文信息。
        """
        return AppContext(self)

    def request_context(self, environ: WSGIEnvironment) -> RequestContext:
        """
        创建并返回一个请求上下文对象。

        该方法用于根据给定的WSGI环境变量生成一个请求上下文（RequestContext）实例，
        以便在当前请求中共享和管理上下文信息。

        参数:
        - environ: WSGI环境变量，包含了关于当前请求的信息，如HTTP头、查询参数等。

        返回:
        - RequestContext: 一个请求上下文实例，用于表示当前请求的相关信息和状态。
        """
        return RequestContext(self, environ)

    def test_request_context(self, *args: t.Any, **kwargs: t.Any) -> RequestContext:
        """
        创建一个请求上下文用于测试。

        该方法使用提供的参数和关键字参数生成一个模拟的环境变量，然后基于这个环境变量创建一个请求上下文。
        这对于测试非常有用，因为它允许在隔离的环境中测试请求的处理。

        参数:
        - *args: 位置参数，允许传递任意数量的未命名参数到EnvironBuilder。
        - **kwargs: 关键字参数，允许传递任意数量的命名参数到EnvironBuilder。

        返回:
        - RequestContext: 一个请求上下文对象，用于测试目的。
        """
        # 导入EnvironBuilder类，负责构建环境变量。
        from .testing import EnvironBuilder

        # 创建EnvironBuilder实例，用于构建测试所需的环境变量。
        builder = EnvironBuilder(self, *args, **kwargs)

        try:
            # 使用构建器生成环境变量，并返回相应的请求上下文。
            return self.request_context(builder.get_environ())
        finally:
            # 确保在测试结束后关闭构建器，释放任何持有的资源。
            builder.close()

    def wsgi_app(
            self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> cabc.Iterable[bytes]:
        """
        实现WSGI应用程序的核心逻辑。

        该方法主要用于处理传入的请求，并生成相应的响应。它通过创建一个请求上下文，
        处理请求，生成响应，并最终返回响应给服务器。

        参数:
        - environ: WSGI环境变量，包含有关传入请求的信息。
        - start_response: 用于开始响应的回调函数。

        返回:
        - 一个字节迭代器，表示HTTP响应。
        """
        # 创建请求上下文
        ctx = self.request_context(environ)
        # 初始化错误变量
        error: BaseException | None = None
        try:
            try:
                # 将上下文推入栈中
                ctx.push()
                # 完整地处理请求并生成响应
                response = self.full_dispatch_request()
            except Exception as e:
                # 捕获处理请求时的异常，并生成相应的响应
                error = e
                response = self.handle_exception(e)
            except:  # noqa: B001
                # 捕获所有其他异常
                error = sys.exc_info()[1]
                raise
            # 返回生成的响应
            return response(environ, start_response)
        finally:
            # 如果存在特定环境变量，则保留上下文
            if "werkzeug.debug.preserve_context" in environ:
                environ["werkzeug.debug.preserve_context"](_cv_app.get())
                environ["werkzeug.debug.preserve_context"](_cv_request.get())

            # 如果有错误且应忽略该错误，则重置错误变量
            if error is not None and self.should_ignore_error(error):
                error = None

            # 弹出上下文
            ctx.pop(error)

    def __call__(
            self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> cabc.Iterable[bytes]:
        """
        实例化对象时使其实现可调用。

        该方法允许实例像函数一样被调用，通常用于构建WSGI应用程序。

        参数:
        - environ: WSGI环境变量，包含有关传入请求的信息。
        - start_response: 用于发送响应状态和头信息的函数。

        返回:
        - 一个字节迭代器，表示WSGI应用程序的响应体。
        """
        # 调用内部的WSGI应用，处理请求并生成响应
        return self.wsgi_app(environ, start_response)
