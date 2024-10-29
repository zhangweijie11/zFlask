from __future__ import annotations

import logging
import os
import sys
import typing as t
from datetime import timedelta
from itertools import chain

from werkzeug.exceptions import Aborter
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import BadRequestKeyError
from werkzeug.routing import BuildError
from werkzeug.routing import Map
from werkzeug.routing import Rule
from werkzeug.sansio.response import Response
from werkzeug.utils import cached_property
from werkzeug.utils import redirect as _wz_redirect

from .. import typing as ft
from ..config import Config
from ..config import ConfigAttribute
from ..ctx import _AppCtxGlobals
from ..helpers import _split_blueprint_path
from ..helpers import get_debug_flag
from ..json.provider import DefaultJSONProvider
from ..json.provider import JSONProvider
from ..logging import create_logger
from ..templating import DispatchingJinjaLoader
from ..templating import Environment
from .scaffold import _endpoint_from_view_func
from .scaffold import find_package
from .scaffold import Scaffold
from .scaffold import setupmethod

if t.TYPE_CHECKING:  # pragma: no cover
    from werkzeug.wrappers import Response as BaseResponse

    from ..testing import FlaskClient
    from ..testing import FlaskCliRunner
    from .blueprints import Blueprint

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



class App(Scaffold):

    aborter_class = Aborter

    jinja_environment = Environment

    app_ctx_globals_class = _AppCtxGlobals

    config_class = Config

    testing = ConfigAttribute[bool]("TESTING")

    secret_key = ConfigAttribute[t.Union[str, bytes, None]]("SECRET_KEY")

    permanent_session_lifetime = ConfigAttribute[timedelta](
        "PERMANENT_SESSION_LIFETIME",
        get_converter=_make_timedelta,  # type: ignore[arg-type]
    )

    json_provider_class: type[JSONProvider] = DefaultJSONProvider
    """A subclass of :class:`~flask.json.provider.JSONProvider`. An
    instance is created and assigned to :attr:`app.json` when creating
    the app.

    The default, :class:`~flask.json.provider.DefaultJSONProvider`, uses
    Python's built-in :mod:`json` library. A different provider can use
    a different JSON library.

    .. versionadded:: 2.2
    """

    jinja_options: dict[str, t.Any] = {}

    url_rule_class = Rule

    url_map_class = Map

    test_client_class: type[FlaskClient] | None = None

    test_cli_runner_class: type[FlaskCliRunner] | None = None

    default_config: dict[str, t.Any]
    response_class: type[Response]

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
    ) -> None:
        super().__init__(
            import_name=import_name,
            static_folder=static_folder,
            static_url_path=static_url_path,
            template_folder=template_folder,
            root_path=root_path,
        )

        if instance_path is None:
            instance_path = self.auto_find_instance_path()
        elif not os.path.isabs(instance_path):
            raise ValueError(
                "If an instance path is provided it must be absolute."
                " A relative path was given instead."
            )

        self.instance_path = instance_path

        self.config = self.make_config(instance_relative_config)

        self.aborter = self.make_aborter()

        self.json: JSONProvider = self.json_provider_class(self)
        """Provides access to JSON methods. Functions in ``flask.json``
        will call methods on this provider when the application context
        is active. Used for handling JSON requests and responses.

        An instance of :attr:`json_provider_class`. Can be customized by
        changing that attribute on a subclass, or by assigning to this
        attribute afterwards.

        The default, :class:`~flask.json.provider.DefaultJSONProvider`,
        uses Python's built-in :mod:`json` library. A different provider
        can use a different JSON library.

        .. versionadded:: 2.2
        """

        self.url_build_error_handlers: list[
            t.Callable[[Exception, str, dict[str, t.Any]], str]
        ] = []

        self.teardown_appcontext_funcs: list[ft.TeardownCallable] = []

        self.shell_context_processors: list[ft.ShellContextProcessorCallable] = []

        self.blueprints: dict[str, Blueprint] = {}

        self.extensions: dict[str, t.Any] = {}

        self.url_map = self.url_map_class(host_matching=host_matching)

        self.subdomain_matching = subdomain_matching

        self._got_first_request = False

    def _check_setup_finished(self, f_name: str) -> None:
        """
        确保在应用程序处理第一个请求之前已完成设置。

        如果尝试在应用程序处理了第一个请求之后调用设置方法，
        则引发AssertionError。这确保了应用程序的设置
        只能在其处理任何请求之前进行，以确保设置的一致性和有效性。

        参数:
        f_name (str): 被调用的设置方法的名称。

        返回:
        无返回值。
        """
        if self._got_first_request:
            raise AssertionError(
                f"The setup method '{f_name}' can no longer be called"
                " on the application. It has already handled its first"
                " request, any changes will not be applied"
                " consistently.\n"
                "Make sure all imports, decorators, functions, etc."
                " needed to set up the application are done before"
                " running it."
            )

    @cached_property
    def name(self) -> str:
        """
        根据模块的导入名称或文件名生成模块的名称。

        如果模块的导入名称为 "__main__"，则尝试从模块的文件名中提取名称。
        如果模块没有文件名（例如，交互模式下），则返回 "__main__"。
        否则，返回模块的导入名称。

        :return: 模块的名称
        """
        # 当模块的导入名称为 "__main__" 时，尝试获取其文件名
        if self.import_name == "__main__":
            # 从 sys.modules 中获取 "__main__" 模块的文件名
            fn: str | None = getattr(sys.modules["__main__"], "__file__", None)
            # 如果模块没有文件名，则返回 "__main__"
            if fn is None:
                return "__main__"
            # 从文件名中提取名称部分（去除扩展名）
            return os.path.splitext(os.path.basename(fn))[0]
        # 如果模块的导入名称不是 "__main__"，直接返回导入名称
        return self.import_name

    @cached_property
    def logger(self) -> logging.Logger:

        return create_logger(self)

    @cached_property
    def jinja_env(self) -> Environment:

        return self.create_jinja_environment()

    def create_jinja_environment(self) -> Environment:
        raise NotImplementedError()

    def make_config(self, instance_relative: bool = False) -> Config:
        """
        创建一个配置对象。

        参数:
        - instance_relative (bool): 如果为True，则相对于实例路径创建配置；否则，相对于根路径创建配置。默认为False。

        返回:
        - Config: 一个配置对象，包含了应用的配置设置。
        """

        # 确定使用哪个路径作为配置的根路径
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path

        # 初始化默认配置字典，并添加DEBUG配置
        defaults = dict(self.default_config)
        defaults["DEBUG"] = get_debug_flag()

        # 创建并返回配置对象
        return self.config_class(root_path, defaults)

    def make_aborter(self) -> Aborter:

        return self.aborter_class()

    def auto_find_instance_path(self) -> str:
        """
        自动查找实例路径。

        本函数尝试根据应用的导入名称找到一个合适的实例路径。
        实例路径用于存储运行时的数据，如数据库文件等。

        :return: 返回实例路径的字符串。
        """

        # 查找包的位置，find_package 是一个假设存在的函数，用于查找给定导入名称对应的包路径。
        # 它返回一个元组，其中包含前缀和包路径。
        prefix, package_path = find_package(self.import_name)

        # 如果没有前缀，意味着这是一个没有特定前缀的包，
        # 这种情况下，我们直接在包路径下创建一个 "instance" 文件夹作为实例路径。
        if prefix is None:
            return os.path.join(package_path, "instance")

        # 如果有前缀，我们则在前缀下创建一个 "var" 文件夹，并在其下以应用名称命名实例文件夹。
        # 这样做是为了在有前缀的情况下提供更灵活和可配置的实例路径。
        return os.path.join(prefix, "var", f"{self.name}-instance")

    def create_global_jinja_loader(self) -> DispatchingJinjaLoader:

        return DispatchingJinjaLoader(self)

    def select_jinja_autoescape(self, filename: str) -> bool:
        """
        根据文件名判断是否需要自动转义。

        自动转义通常用于处理文本文件，以避免潜在的代码注入风险。此函数主要用于决定
        是否对给定的文件名应用自动转义。如果文件名以特定的扩展名结尾，则认为需要自动转义。

        参数:
        filename: str - 文件名，用于判断是否需要自动转义。

        返回:
        bool - 如果文件名以".html", ".htm", ".xml", ".xhtml", ".svg"结尾，则返回True，
               表示需要自动转义；否则返回False。
        """
        # 如果文件名为空，则默认选择自动转义。
        if filename is None:
            return True
        # 检查文件名是否以常见的需要自动转义的文件扩展名结尾。
        return filename.endswith((".html", ".htm", ".xml", ".xhtml", ".svg"))

    @property
    def debug(self) -> bool:

        return self.config["DEBUG"]  # type: ignore[no-any-return]

    @debug.setter
    def debug(self, value: bool) -> None:
        """
        设置debug属性的setter方法。

        当设置debug值时，此方法将DEBUG键的值更新为新的debug值，并根据新的debug值更新Jinja环境的auto_reload属性。
        如果TEMPLATES_AUTO_RELOAD配置项未设置，将根据新的DEBUG值更新jinja_env的auto_reload属性。

        参数:
        value (bool): 新的DEBUG配置值。

        返回:
        None
        """
        # 更新配置字典中的DEBUG键值对
        self.config["DEBUG"] = value

        # 检查TEMPLATES_AUTO_RELOAD配置项是否未设置
        if self.config["TEMPLATES_AUTO_RELOAD"] is None:
            # 如果未设置，则根据新的DEBUG值更新Jinja环境的自动重载设置
            self.jinja_env.auto_reload = value

    @setupmethod
    def register_blueprint(self, blueprint: Blueprint, **options: t.Any) -> None:
        """
        注册蓝图到应用中。

        此装饰器方法允许在应用初始化时注册蓝图，通过将蓝图的配置和路由信息
        集成到应用中，从而实现模块化的设计和代码的重用。

        参数:
        - blueprint (Blueprint): 要注册的蓝图对象，包含了路由和配置信息。
        - **options (t.Any): 传递给蓝图注册方法的额外选项，允许在注册时自定义行为。

        返回:
        此方法不返回任何值。
        """
        # 调用蓝图的register方法，将当前应用实例和额外选项传递给蓝图进行注册
        blueprint.register(self, options)

    def iter_blueprints(self) -> t.ValuesView[Blueprint]:
        """
        迭代所有蓝图。

        该方法返回一个包含所有蓝图的值视图，允许用户在不直接访问内部字典的情况下迭代蓝prints。

        :return: 一个值视图，包含所有蓝图。
        """
        return self.blueprints.values()

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        provide_automatic_options: bool | None = None,
        **options: t.Any,
    ) -> None:
        """
        添加一个URL规则和对应的视图函数到应用的URL映射中。

        :param rule: URL规则的字符串表达，例如 '/index'。
        :param endpoint: 该规则的终点（endpoint），如果未提供，默认为视图函数的名称。
        :param view_func: 视图函数，即当请求匹配此规则时将被调用的函数。
        :param provide_automatic_options: 是否自动生成OPTIONS请求的响应，如果未指定，将使用应用配置中的设置。
        :param options: 其他选项，例如可以指定允许的HTTP方法（'methods'）等。
        :raises TypeError: 如果允许的方法不是字符串列表。
        :raises AssertionError: 如果视图函数映射将覆盖一个现有的终点函数。
        """
        # 确定终点（endpoint）名称
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)  # type: ignore
        options["endpoint"] = endpoint

        # 获取允许的HTTP方法列表
        methods = options.pop("methods", None)
        if methods is None:
            methods = getattr(view_func, "methods", None) or ("GET",)
        if isinstance(methods, str):
            raise TypeError(
                "Allowed methods must be a list of strings, for"
                ' example: @app.route(..., methods=["POST"])'
            )
        methods = {item.upper() for item in methods}

        # 获取视图函数所需的HTTP方法
        required_methods = set(getattr(view_func, "required_methods", ()))

        # 确定是否自动生成OPTIONS请求的响应
        if provide_automatic_options is None:
            provide_automatic_options = getattr(
                view_func, "provide_automatic_options", None
            )

        if provide_automatic_options is None:
            if "OPTIONS" not in methods and self.config["PROVIDE_AUTOMATIC_OPTIONS"]:
                provide_automatic_options = True
                required_methods.add("OPTIONS")
            else:
                provide_automatic_options = False

        methods |= required_methods

        # 创建URL规则对象并添加到URL映射中
        rule_obj = self.url_rule_class(rule, methods=methods, **options)
        rule_obj.provide_automatic_options = provide_automatic_options  # type: ignore[attr-defined]

        self.url_map.add(rule_obj)

        # 注册视图函数
        if view_func is not None:
            old_func = self.view_functions.get(endpoint)
            if old_func is not None and old_func != view_func:
                raise AssertionError(
                    "View function mapping is overwriting an existing"
                    f" endpoint function: {endpoint}"
                )
            self.view_functions[endpoint] = view_func

    @setupmethod
    def template_filter(
        self, name: str | None = None
    ) -> t.Callable[[T_template_filter], T_template_filter]:
        """
        用于注册模板过滤器的装饰器。

        该方法允许通过装饰器语法轻松地将函数注册为模板过滤器。
        它可以接受一个可选的名称参数，用于指定过滤器在模板中的名称。
        如果未提供名称，则使用函数本身的名称。

        参数:
        - name (str | None): 过滤器在模板中使用的名称。如果未提供，则使用函数名称。

        返回:
        - Callable[[T_template_filter], T_template_filter]: 返回一个装饰器，用于注册模板过滤器。

        使用示例:
        @app.template_filter(name='double')
        def double_filter(x):
            return x * 2

        # 在模板中使用
        {{ some_value|double }}
        """
        def decorator(f: T_template_filter) -> T_template_filter:
            """
            实际的装饰器函数，它将函数注册为模板过滤器。

            参数:
            - f (T_template_filter): 要注册为模板过滤器的函数。

            返回:
            - T_template_filter: 返回注册后的函数。
            """
            self.add_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_filter(
        self, f: ft.TemplateFilterCallable, name: str | None = None
    ) -> None:

        self.jinja_env.filters[name or f.__name__] = f

    @setupmethod
    def template_test(
        self, name: str | None = None
    ) -> t.Callable[[T_template_test], T_template_test]:
        """
        一个装饰器工厂函数，用于注册模板测试函数。

        这个函数允许开发者在类中定义一个装饰器，通过该装饰器来注册其他函数
        作为模板测试函数。模板测试函数通常用于在特定的上下文中验证模板的正确性。

        参数:
        - self: 装饰器工厂函数所属的实例。
        - name: 可选参数，指定模板测试的名称。如果未提供，则使用被装饰函数的名称。

        返回:
        - 返回一个装饰器，该装饰器用于包裹并注册模板测试函数。

        使用示例:
        @template_test(name="example_test")
        def example():
            pass
        """
        def decorator(f: T_template_test) -> T_template_test:
            """
            实际的装饰器函数，用于包裹并注册模板测试函数。

            参数:
            - f: 被装饰的模板测试函数。

            返回:
            - 返回被装饰的函数，主要用于注册。
            """
            self.add_template_test(f, name=name)
            return f

        return decorator

    # 使用装饰器声明这是一个设置方法，意味着这个方法用于在特定环境下配置或准备一些资源
    @setupmethod
    def add_template_test(
        self, f: ft.TemplateTestCallable, name: str | None = None
    ) -> None:
        """
        添加一个模板测试函数到Jinja2环境。

        这个方法主要用于向Jinja2模板引擎注册一个新的测试函数，测试函数用于在模板渲染时进行条件判断。

        参数:
        - f: ft.TemplateTestCallable - 一个可调用对象，用于在模板中作为测试。
        - name: str | None - 测试的名称，如果未提供，则使用函数自身的名称。

        返回:
        - None - 这个方法不返回任何值。
        """
        # 将测试函数注册到Jinja2环境，键为提供的名称或函数名称，值为可调用的测试函数
        self.jinja_env.tests[name or f.__name__] = f

    @setupmethod
    def template_global(
        self, name: str | None = None
    ) -> t.Callable[[T_template_global], T_template_global]:
        """
        用于将函数标记为模板全局变量的装饰器。

        此方法允许用户使用装饰器语法来标记一个函数，以便它被添加到模板引擎的全局变量中。
        可以为被装饰的函数指定一个可选的名称，作为在模板中引用该函数时使用的标识符。
        如果未提供名称，则使用函数的原始名称。

        参数:
        - name (str | None): 在模板中使用的函数名称。如果未提供，则使用函数的原始名称。

        返回:
        - Callable[[T_template_global], T_template_global]: 返回一个装饰器，该装饰器接受并返回一个函数，
          将其添加到模板引擎的全局变量中。
        """

        def decorator(f: T_template_global) -> T_template_global:
            """
            实际的装饰器函数，用于将标记的函数添加到模板全局变量。

            参数:
            - f (T_template_global): 被装饰的函数，将被添加到模板的全局变量中。

            返回:
            - T_template_global: 返回原始函数，保持其原有的行为和特性。
            """
            self.add_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_global(
        self, f: ft.TemplateGlobalCallable, name: str | None = None
    ) -> None:
        """
        将给定的函数添加为模板全局变量。

        此装饰器方法允许在模板环境中注册一个全局可用的函数。
        这对于在模板中使用Python函数非常有用，而无需在每个模板中重复定义它。

        参数:
        - f: 一个可调用对象，将在模板环境中作为全局变量使用。
        - name: 可选参数，指定在模板环境中使用的变量名称。
          如果未提供，则使用函数的名称。

        返回值:
        无返回值。

        示例:
        @env.add_template_global
        def current_year():
            return datetime.now().year

        # 在模板中使用
        {{ current_year() }}
        """
        # 注册函数为模板全局变量
        self.jinja_env.globals[name or f.__name__] = f

    @setupmethod
    def teardown_appcontext(self, f: T_teardown) -> T_teardown:
        """
        注册一个在处理请求后，应用程序上下文被拆解时需要执行的函数。

        此装饰器用于在应用程序上下文被拆解时执行一些清理操作，例如关闭数据库连接或清理缓存。
        它将被装饰的函数添加到一个列表中，以便在上下文被拆解时按顺序调用这些函数。

        参数:
        - f: T_teardown 类型的函数，表示一个将在应用程序上下文被拆解时调用的函数。

        返回:
        - 返回被装饰的函数本身，便于装饰器的使用。
        """
        self.teardown_appcontext_funcs.append(f)
        return f

    @setupmethod
    def shell_context_processor(
        self, f: T_shell_context_processor
    ) -> T_shell_context_processor:
        """
        注册一个自定义的shell上下文处理器。

        该装饰器方法用于向Flask应用中添加自定义的shell上下文处理器。
        shell上下文处理器是在交互式shell中使用上下文时非常有用，因为它可以自动地将应用中的重要对象添加到shell的命名空间中。

        参数:
        - f: T_shell_context_processor 类型的函数，表示要注册的shell上下文处理器。

        返回:
        - 返回注册后的shell上下文处理器函数。
        """
        # 将传入的函数f添加到shell上下文处理器列表中
        self.shell_context_processors.append(f)
        # 返回传入的函数f，使其可以被继续使用
        return f

    def _find_error_handler(
        self, e: Exception, blueprints: list[str]
    ) -> ft.ErrorHandlerCallable | None:
        """
        根据异常类型和蓝图列表寻找错误处理器。

        此函数尝试根据给定的异常类型和蓝图列表找到一个合适的错误处理器。
        它首先确定异常的类和HTTP状态码，然后在错误处理器规范中查找匹配的处理器。

        参数:
        - e: 发生的异常实例。
        - blueprints: 参与查找的蓝图列表，因为不同的蓝图可能定义了不同的错误处理器。

        返回:
        - 如果找到合适的错误处理器，则返回该处理器。
        - 如果没有找到合适的错误处理器，则返回None。
        """

        # 获取异常类和对应的HTTP状态码
        exc_class, code = self._get_exc_class_and_code(type(e))

        # 准备蓝图名称和默认名称的元组，用于后续的错误处理器查找
        names = (*blueprints, None)

        # 遍历HTTP状态码和默认值，以及蓝图名称，以查找错误处理器映射
        for c in (code, None) if code is not None else (None,):
            for name in names:
                # 尝试获取当前蓝图和状态码对应的错误处理器映射
                handler_map = self.error_handler_spec[name][c]

                # 如果当前映射为空，则跳过，继续查找下一个
                if not handler_map:
                    continue

                # 遍历异常类的方法解析顺序（MRO），以查找匹配的错误处理器
                for cls in exc_class.__mro__:
                    # 尝试获取当前异常类对应的错误处理器
                    handler = handler_map.get(cls)

                    # 如果找到匹配的处理器，则返回它
                    if handler is not None:
                        return handler

        # 如果没有找到任何匹配的错误处理器，则返回None
        return None

    def trap_http_exception(self, e: Exception) -> bool:
        """
        决定是否捕获HTTP异常。

        此方法根据当前配置和异常类型，决定是否捕获HTTP异常。它首先检查是否需要捕获所有HTTP异常，
        如果需要，则直接返回True。然后，它根据配置和当前调试状态，决定是否捕获特定的HTTP请求错误。

        参数:
        - e: Exception - 发生的异常实例。

        返回:
        - bool: 表示是否应该捕获该HTTP异常。
        """
        # 检测是否需要捕获HTTP异常
        if self.config["TRAP_HTTP_EXCEPTIONS"]:
            return True

        # 获取配置中关于是否捕获不良请求错误的设置
        trap_bad_request = self.config["TRAP_BAD_REQUEST_ERRORS"]

        # 如果配置未明确是否捕获不良请求错误，且处于调试模式，并且异常是BadRequestKeyError类型，则捕获
        if (
            trap_bad_request is None
            and self.debug
            and isinstance(e, BadRequestKeyError)
        ):
            return True

        # 如果配置明确需要捕获不良请求错误，并且异常是BadRequest类型，则捕获
        if trap_bad_request:
            return isinstance(e, BadRequest)

        # 如果以上条件均不满足，则不捕获异常
        return False

    def should_ignore_error(self, error: BaseException | None) -> bool:

        return False

    def redirect(self, location: str, code: int = 302) -> BaseResponse:
        """
        重定向用户到指定的页面。

        该方法使用_Werkzeug提供的_wz_redirect方法来执行重定向操作。它允许开发者指定重定向的位置
        和HTTP状态码。此方法通常用于路由控制，将用户从一个页面引导至另一个页面。

        参数:
        - location (str): 用户将被重定向到的页面URL。
        - code (int): HTTP状态码，表示重定向的类型，默认为302，表示临时重定向。

        返回:
        - BaseResponse: 返回一个包含重定向信息的HTTP响应对象。
        """
        return _wz_redirect(
            location,
            code=code,
            Response=self.response_class,  # type: ignore[arg-type]
        )

    def inject_url_defaults(self, endpoint: str, values: dict[str, t.Any]) -> None:
        """
        向给定的终点(endpoint)对应的URL参数字典(values)中注入默认参数值。

        此函数会根据终点的蓝图路径，查找并执行所有相关的URL默认参数处理函数，
        以确保URL参数字典中包含了所有必要的默认值。

        参数:
        - endpoint: 字符串类型，表示请求的终点。
        - values: 字典类型，包含终点的URL参数，此函数将向其中注入默认值。
        """
        # 初始化名称集合，用于存储蓝图路径中的各部分名称，从右至左
        names: t.Iterable[str | None] = (None,)

        # 如果终点包含蓝图分隔符"."，则分解蓝图路径，并将路径各部分反转存储
        if "." in endpoint:
            names = chain(
                names, reversed(_split_blueprint_path(endpoint.rpartition(".")[0]))
            )

        # 遍历蓝图路径的各部分名称，包括None（代表全局默认参数）
        for name in names:
            # 如果当前名称有对应的URL默认参数处理函数，则执行这些函数
            if name in self.url_default_functions:
                for func in self.url_default_functions[name]:
                    func(endpoint, values)

    def handle_url_build_error(
        self, error: BuildError, endpoint: str, values: dict[str, t.Any]
    ) -> str:
        """
        处理URL构建错误。

        当URL构建失败时，此方法会被调用以处理构建错误。它会尝试使用注册的URL构建错误处理器来处理错误。
        如果所有处理器都无法处理错误或返回None，则会重新抛出原始错误。

        参数:
        - error (BuildError): 发生的URL构建错误实例。
        - endpoint (str): 尝试构建的终点名称。
        - values (dict[str, t.Any]): 用于构建URL的值的字典。

        返回:
        - str: 如果错误被成功处理，则返回处理结果（通常是构建的URL）。

        抛出:
        - BuildError: 如果没有处理器能处理错误，或者所有处理器都返回None，则会重新抛出构建错误。
        """
        # 遍历所有URL构建错误处理器，尝试处理错误
        for handler in self.url_build_error_handlers:
            try:
                rv = handler(error, endpoint, values)
            except BuildError as e:
                # 如果处理器在处理过程中遇到新的构建错误，将其设为当前错误
                error = e
            else:
                # 如果处理器成功处理错误并返回结果，则返回该结果
                if rv is not None:
                    return rv

        # 如果当前错误与系统异常信息中的错误相同，直接重新抛出
        if error is sys.exc_info()[1]:
            raise

        # 如果上述条件不满足，重新抛出当前错误
        raise error
