from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import typing as t
from collections import defaultdict
from functools import update_wrapper

from jinja2 import BaseLoader
from jinja2 import FileSystemLoader
from werkzeug.exceptions import default_exceptions
from werkzeug.exceptions import HTTPException
from werkzeug.utils import cached_property

from .. import typing as ft
from ..helpers import get_root_path
from ..templating import _default_template_ctx_processor

if t.TYPE_CHECKING:  # pragma: no cover
    from click import Group

# a singleton sentinel value for parameter defaults
_sentinel = object()

F = t.TypeVar("F", bound=t.Callable[..., t.Any])
T_after_request = t.TypeVar("T_after_request", bound=ft.AfterRequestCallable[t.Any])
T_before_request = t.TypeVar("T_before_request", bound=ft.BeforeRequestCallable)
T_error_handler = t.TypeVar("T_error_handler", bound=ft.ErrorHandlerCallable)
T_teardown = t.TypeVar("T_teardown", bound=ft.TeardownCallable)
T_template_context_processor = t.TypeVar(
    "T_template_context_processor", bound=ft.TemplateContextProcessorCallable
)
T_url_defaults = t.TypeVar("T_url_defaults", bound=ft.URLDefaultCallable)
T_url_value_preprocessor = t.TypeVar(
    "T_url_value_preprocessor", bound=ft.URLValuePreprocessorCallable
)
T_route = t.TypeVar("T_route", bound=ft.RouteCallable)


def setupmethod(f: F) -> F:
    """
    一个装饰器函数，用于确保在调用被装饰的方法前，某个设置过程已经完成。

    参数:
    - f: F 被装饰的函数类型，F 为函数类型别名。

    返回:
    - F 返回与被装饰函数相同类型的函数。
    """
    # 获取被装饰函数的名称
    f_name = f.__name__

    def wrapper_func(self: Scaffold, *args: t.Any, **kwargs: t.Any) -> t.Any:
        """
        包装函数，用于在调用被装饰的函数前执行额外的检查操作。

        参数:
        - self: Scaffold 调用被装饰方法的实例对象。
        - *args: 位置参数，允许接受不定数量的位置参数。
        - **kwargs: 关键字参数，允许接受不定数量的关键字参数。

        返回:
        - t.Any 被装饰函数的返回类型。
        """
        # 在调用被装饰的函数前，检查设置过程是否完成
        self._check_setup_finished(f_name)
        # 调用被装饰的函数
        return f(self, *args, **kwargs)

    # 更新包装函数的元数据，使其与被装饰的函数一致，并返回
    return t.cast(F, update_wrapper(wrapper_func, f))


class Scaffold:
    """
    Scaffold类是用于构建应用程序骨架的基础类。
    它包含了应用程序所需的基本配置和功能，如静态文件夹、模板文件夹、错误处理器等。
    """
    cli: Group
    name: str
    _static_folder: str | None = None
    _static_url_path: str | None = None

    def __init__(
            self,
            import_name: str,
            static_folder: str | os.PathLike[str] | None = None,
            static_url_path: str | None = None,
            template_folder: str | os.PathLike[str] | None = None,
            root_path: str | None = None,
    ):
        """
        初始化Scaffold实例。

        参数:
        - import_name: 用于导入的名称。
        - static_folder: 静态文件夹的路径。
        - static_url_path: 静态文件的URL路径。
        - template_folder: 模板文件夹的路径。
        - root_path: 应用程序的根路径。
        """
        self.import_name = import_name

        # 设置静态文件夹和静态URL路径
        self.static_folder = static_folder  # type: ignore
        self.static_url_path = static_url_path

        # 设置模板文件夹
        self.template_folder = template_folder

        # 如果未提供根路径，则根据导入名称获取根路径
        if root_path is None:
            root_path = get_root_path(self.import_name)

        self.root_path = root_path

        # 初始化视图函数字典
        self.view_functions: dict[str, ft.RouteCallable] = {}

        # 初始化错误处理器规格字典
        self.error_handler_spec: dict[
            ft.AppOrBlueprintKey,
            dict[int | None, dict[type[Exception], ft.ErrorHandlerCallable]],
        ] = defaultdict(lambda: defaultdict(dict))

        # 初始化请求前处理函数列表
        self.before_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.BeforeRequestCallable]
        ] = defaultdict(list)

        # 初始化请求后处理函数列表
        self.after_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.AfterRequestCallable[t.Any]]
        ] = defaultdict(list)

        # 初始化请求销毁处理函数列表
        self.teardown_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.TeardownCallable]
        ] = defaultdict(list)

        # 初始化模板上下文处理器列表
        self.template_context_processors: dict[
            ft.AppOrBlueprintKey, list[ft.TemplateContextProcessorCallable]
        ] = defaultdict(list, {None: [_default_template_ctx_processor]})

        # 初始化URL值预处理器列表
        self.url_value_preprocessors: dict[
            ft.AppOrBlueprintKey,
            list[ft.URLValuePreprocessorCallable],
        ] = defaultdict(list)

        # 初始化URL默认函数列表
        self.url_default_functions: dict[
            ft.AppOrBlueprintKey, list[ft.URLDefaultCallable]
        ] = defaultdict(list)

    def __repr__(self) -> str:
        """
        返回Scaffold实例的字符串表示。

        返回:
        - 字符串表示的实例。
        """
        return f"<{type(self).__name__} {self.name!r}>"

    def _check_setup_finished(self, f_name: str) -> None:
        """
        检查设置是否完成。

        参数:
        - f_name: 要检查的函数名称。

        异常:
        - NotImplementedError: 如果设置未完成。
        """
        raise NotImplementedError

    @property
    def static_folder(self) -> str | None:
        """
        获取静态文件夹的路径。

        返回:
        - 静态文件夹的路径，如果未设置则返回None。
        """
        if self._static_folder is not None:
            return os.path.join(self.root_path, self._static_folder)
        else:
            return None

    @static_folder.setter
    def static_folder(self, value: str | os.PathLike[str] | None) -> None:
        """
        设置静态文件夹的路径。

        参数:
        - value: 静态文件夹的路径。
        """

        if value is not None:
            value = os.fspath(value).rstrip(r"\/")

        self._static_folder = value

    @property
    def has_static_folder(self) -> bool:
        """
        检查是否设置了静态文件夹。

        返回:
        - 如果设置了静态文件夹则返回True，否则返回False。
        """
        return self.static_folder is not None

    @property
    def static_url_path(self) -> str | None:
        """
        获取静态文件URL路径。

        如果已显式设置_static_url_path，则直接返回它。否则，尝试根据static_folder的名称推断静态文件URL路径。
        如果static_folder也没有设置，则返回None，表示没有可用的静态文件路径。
        """
        if self._static_url_path is not None:
            return self._static_url_path

        if self.static_folder is not None:
            basename = os.path.basename(self.static_folder)
            return f"/{basename}".rstrip("/")

        return None

    @static_url_path.setter
    def static_url_path(self, value: str | None) -> None:
        """
        设置静态文件URL路径。

        如果提供的值不为None，则移除其末尾的斜杠，以保持URL路径格式的一致性。
        """
        if value is not None:
            value = value.rstrip("/")

        self._static_url_path = value

    @cached_property
    def jinja_loader(self) -> BaseLoader | None:
        """
        获取Jinja模板加载器。

        如果template_folder已设置，则返回一个FileSystemLoader，指向模板文件所在的目录。
        否则，返回None，表示没有模板加载器可用。
        """
        if self.template_folder is not None:
            return FileSystemLoader(os.path.join(self.root_path, self.template_folder))
        else:
            return None

    def _method_route(
            self,
            method: str,
            rule: str,
            options: dict[str, t.Any],
    ) -> t.Callable[[T_route], T_route]:
        """
        内部方法，用于创建仅限单个HTTP方法的路由。

        如果options中包含'methods'，则引发TypeError，因为应使用'route'装饰器来指定方法。
        该函数返回一个装饰器，用于处理给定规则和HTTP方法的路由。
        """
        if "methods" in options:
            raise TypeError("Use the 'route' decorator to use the 'methods' argument.")

        return self.route(rule, methods=[method], **options)

    @setupmethod
    def get(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
        装饰器方法，用于处理GET请求。

        :param rule: URL规则字符串
        :param options: 附加选项字典
        :return: 返回一个装饰器，用于装饰处理GET请求的函数
        """
        return self._method_route("GET", rule, options)

    @setupmethod
    def post(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
        装饰器方法，用于处理POST请求。

        :param rule: URL规则字符串
        :param options: 附加选项字典
        :return: 返回一个装饰器，用于装饰处理POST请求的函数
        """
        return self._method_route("POST", rule, options)

    @setupmethod
    def put(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
        装饰器方法，用于处理PUT请求。

        :param rule: URL规则字符串
        :param options: 附加选项字典
        :return: 返回一个装饰器，用于装饰处理PUT请求的函数
        """
        return self._method_route("PUT", rule, options)

    @setupmethod
    def delete(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
        装饰器方法，用于处理DELETE请求。

        :param rule: URL规则字符串
        :param options: 附加选项字典
        :return: 返回一个装饰器，用于装饰处理DELETE请求的函数
        """
        return self._method_route("DELETE", rule, options)

    @setupmethod
    def patch(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
        装饰器方法，用于处理PATCH请求。

        :param rule: URL规则字符串
        :param options: 附加选项字典
        :return: 返回一个装饰器，用于装饰处理PATCH请求的函数
        """
        return self._method_route("PATCH", rule, options)

    @setupmethod
    def route(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
        装饰器方法，用于为特定URL规则和选项注册路由。

        :param rule: URL规则字符串
        :param options: 附加选项字典
        :return: 返回一个装饰器，用于装饰处理特定URL规则的函数
        """

        def decorator(f: T_route) -> T_route:
            """
            内部装饰器函数，用于实际注册路由。

            :param f: 被装饰的处理函数
            :return: 返回原处理函数
            """
            endpoint = options.pop("endpoint", None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f

        return decorator

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
        添加一个URL规则和对应的视图函数到应用程序。

        此方法允许在应用程序中动态地添加新的URL规则和视图函数，以便处理特定的HTTP请求。

        参数:
        - rule (str): URL规则的字符串表达，如 '/index'。
        - endpoint (str | None): 视图函数的端点名称，如果未提供，默认为视图函数的名称。
        - view_func (ft.RouteCallable | None): 处理此URL规则的视图函数。
        - provide_automatic_options (bool | None): 是否自动生成OPTIONS请求的响应，如果未提供，默认为配置的值。
        - **options (t.Any): 其他任何应该传递给视图函数的额外选项。

        返回:
        - None
        """

        raise NotImplementedError

    @setupmethod
    def endpoint(self, endpoint: str) -> t.Callable[[F], F]:
        """
        一个装饰器，用于将函数注册为特定端点的视图函数。

        参数:
        - endpoint (str): 要注册的端点名称。

        返回:
        - t.Callable[[F], F]: 一个装饰器，用于注册视图函数。
        """

        def decorator(f: F) -> F:
            """
            装饰器函数，将视图函数与端点关联。

            参数:
            - f (F): 要关联的视图函数。

            返回:
            - F: 被装饰的视图函数。
            """
            self.view_functions[endpoint] = f
            return f

        return decorator

    @setupmethod
    def before_request(self, f: T_before_request) -> T_before_request:
        """
        在处理请求之前执行的函数。

        此方法允许注册一个函数，在每个请求处理之前执行。可以用于验证、日志记录等。

        参数:
        - f (T_before_request): 在请求处理之前执行的函数。

        返回:
        - T_before_request: 被装饰的函数。
        """
        self.before_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def after_request(self, f: T_after_request) -> T_after_request:
        """
        在处理请求之后执行的函数。

        此方法允许注册一个函数，在每个请求处理之后执行。可以用于修改响应、资源释放等。

        参数:
        - f (T_after_request): 在请求处理之后执行的函数。

        返回:
        - T_after_request: 被装饰的函数。
        """
        self.after_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def teardown_request(self, f: T_teardown) -> T_teardown:
        """
        注册一个在请求结束时执行的函数。

        此函数用于在请求处理完毕后执行一些清理工作，如关闭数据库连接等。
        它接受一个函数作为参数，并将其添加到请求结束时要执行的函数列表中。

        参数:
        - f: T_teardown -- 要注册的函数，该函数将在请求结束后执行。

        返回:
        - T_teardown -- 返回注册的函数本身，便于链式调用。
        """
        self.teardown_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def context_processor(
            self,
            f: T_template_context_processor,
    ) -> T_template_context_processor:
        """
        注册一个模板上下文处理器。

        该函数用于向模板渲染时提供额外的上下文信息。通过此装饰器注册的函数
        将在每次模板渲染前被调用，其返回的字典将被合并到模板的上下文中。

        参数:
        - f: T_template_context_processor -- 要注册的模板上下文处理器函数。

        返回:
        - T_template_context_processor -- 返回注册的函数本身，便于链式调用。
        """
        self.template_context_processors[None].append(f)
        return f

    @setupmethod
    def url_value_preprocessor(
            self,
            f: T_url_value_preprocessor,
    ) -> T_url_value_preprocessor:
        """
        注册一个URL值预处理器。

        该函数用于在解析URL参数之前执行预处理，可以用于修改请求参数等。

        参数:
        - f: T_url_value_preprocessor -- 要注册的URL值预处理器函数。

        返回:
        - T_url_value_preprocessor -- 返回注册的函数本身，便于链式调用。
        """
        self.url_value_preprocessors[None].append(f)
        return f

    @setupmethod
    def url_defaults(self, f: T_url_defaults) -> T_url_defaults:
        """
        注册一个URL默认值处理器。

        该函数用于在生成URL时提供默认参数值，以简化URL生成过程中的参数管理。

        参数:
        - f: T_url_defaults -- 要注册的URL默认值处理器函数。

        返回:
        - T_url_defaults -- 返回注册的函数本身，便于链式调用。
        """
        self.url_default_functions[None].append(f)
        return f

    @setupmethod
    def errorhandler(
            self, code_or_exception: type[Exception] | int
    ) -> t.Callable[[T_error_handler], T_error_handler]:
        """
        装饰器工厂，用于注册错误处理器函数。

        此方法允许用户为特定的异常类型或HTTP状态码注册一个处理函数。
        当应用程序遇到指定的异常或状态码时，将调用注册的处理函数。

        参数:
        - self: 当前实例的引用。
        - code_or_exception: 要处理的HTTP状态码或异常类型。
          这允许应用程序针对不同的错误条件做出响应。

        返回:
        - Callable[[T_error_handler], T_error_handler]: 返回一个装饰器，用于包装错误处理函数。
          这使用户能够使用此方法作为装饰器，以注册他们的自定义错误处理逻辑。
        """

        def decorator(f: T_error_handler) -> T_error_handler:
            """
            装饰器，用于注册一个错误处理函数。

            参数:
            - f: 要注册的错误处理函数。
              这个函数将被调用来处理特定的异常或状态码。

            返回:
            - T_error_handler: 返回原始的错误处理函数。
              这确保了装饰器模式的透明性，使函数保持不变。
            """
            self.register_error_handler(code_or_exception, f)
            return f

        return decorator

    @setupmethod
    def register_error_handler(
            self,
            code_or_exception: type[Exception] | int,
            f: ft.ErrorHandlerCallable,
    ) -> None:
        """
        注册错误处理函数，用于处理特定异常或状态码。

        本方法旨在为特定的异常类型或状态码绑定一个处理函数，以便当该异常或状态码出现时，
        指定的处理函数会被调用，进行错误处理。

        参数:
        - code_or_exception (type[Exception] | int): 需要绑定处理函数的异常类型或状态码。
        - f (ft.ErrorHandlerCallable): 用于处理异常或状态码的可调用函数。

        返回:
        无返回值。

        通过本方法，可以灵活地定义和管理各种错误情况下的处理逻辑，提高程序的健壮性和可维护性。
        """
        # 解析给定的异常类型或状态码，以确定错误处理函数应如何注册
        exc_class, code = self._get_exc_class_and_code(code_or_exception)
        # 在错误处理规范中注册错误处理函数，以便后续在遇到对应错误时调用
        self.error_handler_spec[None][code][exc_class] = f

    @staticmethod
    def _get_exc_class_and_code(
            exc_class_or_code: type[Exception] | int,
    ) -> tuple[type[Exception], int | None]:
        """
        根据提供的异常类或错误代码，返回异常类和错误代码的元组。

        参数:
        - exc_class_or_code: 一个异常类或错误代码，用于识别异常类型。

        返回:
        - 一个元组，包含异常类和可能的错误代码。

        此函数旨在解析给定的异常类或错误代码，并返回相应的异常类和错误代码（如果有）。
        它首先检查输入是否为错误代码，如果是，则尝试将其映射到相应的异常类。
        如果输入已经是异常类，则直接使用。然后，它验证最终确定的异常类是否为Exception的子类，
        并根据是否是HTTPException的子类来决定是否返回错误代码。
        """
        # 初始化异常类变量
        exc_class: type[Exception]

        # 检查输入是否为错误代码
        if isinstance(exc_class_or_code, int):
            try:
                # 尝试根据错误代码获取对应的异常类
                exc_class = default_exceptions[exc_class_or_code]
            except KeyError:
                # 如果错误代码未被识别，抛出ValueError
                raise ValueError(
                    f"'{exc_class_or_code}' is not a recognized HTTP"
                    " error code. Use a subclass of HTTPException with"
                    " that code instead."
                ) from None
        else:
            # 如果输入是异常类，直接使用
            exc_class = exc_class_or_code

        # 检查确定的异常类是否为Exception实例，而不是类
        if isinstance(exc_class, Exception):
            raise TypeError(
                f"{exc_class!r} is an instance, not a class. Handlers"
                " can only be registered for Exception classes or HTTP"
                " error codes."
            )

        # 检查确定的异常类是否为Exception的子类
        if not issubclass(exc_class, Exception):
            raise ValueError(
                f"'{exc_class.__name__}' is not a subclass of Exception."
                " Handlers can only be registered for Exception classes"
                " or HTTP error codes."
            )

        # 根据异常类是否是HTTPException的子类，返回不同的结果
        if issubclass(exc_class, HTTPException):
            return exc_class, exc_class.code
        else:
            return exc_class, None


def _endpoint_from_view_func(view_func: ft.RouteCallable) -> str:
    """
    获取视图函数的端点名称。

    此函数用于提取视图函数的名称作为端点名称。如果未提供端点名称，则使用视图函数的名称。

    参数:
    - view_func: ft.RouteCallable类型，一个视图函数。

    返回:
    - str类型，视图函数的名称。

    异常:
    - AssertionError: 如果view_func为None，则抛出断言错误。
    """
    # 确保视图函数不为None，否则抛出断言错误
    assert view_func is not None, "expected view func if endpoint is not provided."
    # 返回视图函数的名称
    return view_func.__name__


def _path_is_relative_to(path: pathlib.PurePath, base: str) -> bool:
    """
    判断给定的路径是否是相对于指定基数路径的相对路径。

    参数:
    path (pathlib.PurePath): 需要检查的路径。
    base (str): 基数路径，用于确定给定路径是否是相对的。

    返回:
    bool: 如果给定路径是相对于基数路径的，则返回True；否则返回False。
    """
    # 尝试使用relative_to方法来判断路径是否是相对于基数路径的
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _find_package_path(import_name: str) -> str:
    """
    根据导入名称找到包的路径。

    参数:
    import_name (str): 导入名称，用于查找包的路径。

    返回:
    str: 包的路径。如果找不到包，则返回当前工作目录。
    """
    # 分解导入名称，获取根模块名称
    root_mod_name, _, _ = import_name.partition(".")

    try:
        # 尝试查找根模块的规格信息
        root_spec = importlib.util.find_spec(root_mod_name)

        # 如果根模块规格信息为空，则抛出 ValueError
        if root_spec is None:
            raise ValueError("not found")
    except (ImportError, ValueError):
        # 如果发生 ImportError 或 ValueError，则返回当前工作目录
        return os.getcwd()

    # 检查根模块是否有子模块搜索位置
    if root_spec.submodule_search_locations:
        # 如果根模块的起源为 None 或 "namespace"，则进一步查找包的规格信息
        if root_spec.origin is None or root_spec.origin == "namespace":
            # 查找特定导入名称的包规格信息
            package_spec = importlib.util.find_spec(import_name)

            # 如果包规格信息存在且有子模块搜索位置，则计算包的路径
            if package_spec is not None and package_spec.submodule_search_locations:
                package_path = pathlib.Path(
                    os.path.commonpath(package_spec.submodule_search_locations)
                )
                # 查找符合条件的子模块搜索位置
                search_location = next(
                    location
                    for location in root_spec.submodule_search_locations
                    if _path_is_relative_to(package_path, location)
                )
            else:
                # 如果包规格信息不符合条件，则使用根模块的第一个子模块搜索位置
                search_location = root_spec.submodule_search_locations[0]

            # 返回子模块搜索位置的目录
            return os.path.dirname(search_location)
        else:
            # 如果根模块的起源不是 None 或 "namespace"，则返回根模块起源的父目录
            return os.path.dirname(os.path.dirname(root_spec.origin))
    else:
        # 如果根模块没有子模块搜索位置，则返回根模块起源的目录
        return os.path.dirname(root_spec.origin)  # type: ignore[type-var, return-value]


def find_package(import_name: str) -> tuple[str | None, str]:
    """
    根据导入名称查找包的路径。

    该函数尝试找到给定导入名称的包的路径，并返回有关包的安装位置和包路径的信息。
    如果包位于Python标准库或第三方包的site-packages目录下，它会返回包的根目录和包路径。

    参数:
    import_name (str): 要查找的包的导入名称。

    返回:
    tuple[str | None, str]: 一个元组，包含包的根目录（如果找到）和包路径。
    """

    # 查找包的路径
    package_path = _find_package_path(import_name)
    # 获取Python环境的前缀路径
    py_prefix = os.path.abspath(sys.prefix)

    # 检查包路径是否相对于Python环境的前缀路径
    if _path_is_relative_to(pathlib.PurePath(package_path), py_prefix):
        return py_prefix, package_path

    # 获取包路径的父目录和文件夹名
    site_parent, site_folder = os.path.split(package_path)

    # 如果包路径是"site-packages"目录的一部分
    if site_folder.lower() == "site-packages":
        parent, folder = os.path.split(site_parent)

        # 如果父目录的文件夹名是"lib"，则返回其父目录和包路径
        if folder.lower() == "lib":
            return parent, package_path

        # 如果父目录的父目录的文件夹名是"lib"，则返回父目录的父目录的父目录和包路径
        if os.path.basename(parent).lower() == "lib":
            return os.path.dirname(parent), package_path

        # 如果上述条件都不满足，返回包路径的父目录和包路径
        return site_parent, package_path

    # 如果包路径不是"site-packages"目录的一部分，返回None和包路径
    return None, package_path
