from __future__ import annotations

import ast
import collections.abc as cabc
import importlib.metadata
import inspect
import os
import platform
import re
import sys
import traceback
import typing as t
import click

from functools import update_wrapper
from operator import itemgetter
from types import ModuleType
from click.core import ParameterSource
from .globals import current_app
from werkzeug import run_simple
from werkzeug.utils import import_string
from werkzeug.serving import is_running_from_reloader

# 仅在类型检查时导入特定模块，以支持类型提示
if t.TYPE_CHECKING:
    # 导入ssl模块，用于SSL/TLS通信
    import ssl

    # 从_wsgi类型库中导入类型提示相关类和类型
    from _typeshed.wsgi import StartResponse
    from _typeshed.wsgi import WSGIApplication
    from _typeshed.wsgi import WSGIEnvironment

    # 从当前项目的app模块中导入Flask类，提供Web服务
    from .app import Flask


class NoAppException(click.UsageError):
    """Raised if an application cannot be found or loaded."""


def find_best_app(module: ModuleType) -> Flask:
    """
    寻找模块中最佳的Flask应用实例。

    该函数首先检查模块的`app`和`application`属性，以寻找Flask实例。
    如果这些属性不存在或不是Flask实例，它将尝试从模块的所有属性中查找单个Flask实例。
    如果找到多个Flask实例，将抛出异常，因为无法确定使用哪一个。
    如果没有直接找到Flask实例，它将尝试调用`create_app`或`make_app`函数来创建Flask实例。

    :param module: 要检查的模块，可以是导入的模块或通过其他方式获取的模块对象。
    :return: Flask实例，如果找到的话。
    :raises NoAppException: 如果在模块中找不到Flask应用实例或工厂，或者找到多个实例时抛出此异常。
    """
    from . import Flask

    # 遍历模块的属性，寻找是否有Flask实例
    for attr_name in ("app", "application"):
        app = getattr(module, attr_name, None)

        # 如果找到一个Flask实例，则返回该实例
        if isinstance(app, Flask):
            return app

    # 如果没有直接找到Flask实例，从模块的所有属性中查找
    matches = [v for v in module.__dict__.values() if isinstance(v, Flask)]

    # 如果找到一个Flask实例，则返回该实例
    if len(matches) == 1:
        return matches[0]
    # 如果找到多个Flask实例，抛出异常
    elif len(matches) > 1:
        raise NoAppException(
            "Detected multiple Flask applications in module"
            f" '{module.__name__}'. Use '{module.__name__}:name'"
            " to specify the correct one."
        )

    # 尝试查找并调用`create_app`或`make_app`工厂函数
    for attr_name in ("create_app", "make_app"):
        app_factory = getattr(module, attr_name, None)

        # 如果找到工厂函数，尝试调用它来创建Flask实例
        if inspect.isfunction(app_factory):
            try:
                app = app_factory()

                # 如果创建了Flask实例，则返回该实例
                if isinstance(app, Flask):
                    return app
            except TypeError as e:
                # 如果工厂函数调用失败，检查是否因为参数错误
                if not _called_with_wrong_args(app_factory):
                    raise

                # 如果不能调用工厂函数，抛出异常说明问题所在
                raise NoAppException(
                    f"Detected factory '{attr_name}' in module '{module.__name__}',"
                    " but could not call it without arguments. Use"
                    f" '{module.__name__}:{attr_name}(args)'"
                    " to specify arguments."
                ) from e

    # 如果所有尝试都失败，抛出异常说明找不到Flask应用或工厂
    raise NoAppException(
        "Failed to find Flask application or factory in module"
        f" '{module.__name__}'. Use '{module.__name__}:name'"
        " to specify one."
    )


def _called_with_wrong_args(f: t.Callable[..., Flask]) -> bool:
    """
    判断工厂函数是否被错误地调用。

    此函数通过检查当前的异常信息，确定错误是否源自工厂函数的不当调用。

    参数:
    f: t.Callable[..., Flask] - 一个工厂函数，期望返回一个Flask实例。

    返回:
    bool - 如果工厂函数被错误地调用，则返回True，否则返回False。
    """
    # 获取当前异常的traceback对象
    tb = sys.exc_info()[2]

    try:
        # 判断错误是否来自工厂函数调用
        while tb is not None:
            # 如果当前帧的代码对象与工厂函数的代码对象相同，表示错误即来源于此
            if tb.tb_frame.f_code is f.__code__:
                return False

            # 继续遍历下一个traceback项
            tb = tb.tb_next

        # 如果遍历结束都没有找到错误来源，则认为是错误调用
        return True
    finally:
        # 释放traceback对象，避免循环引用导致的内存泄漏
        del tb


def find_app_by_string(module: ModuleType, app_name: str) -> Flask:
    """
    根据字符串表达式在指定模块中查找Flask应用。

    该函数尝试解析字符串表达式以找到或生成一个Flask应用实例。
    它支持直接通过属性名访问或调用模块中的函数来创建应用实例。

    参数:
    - module: ModuleType, 要在其中查找应用的模块。
    - app_name: str, 表达式字符串，用于描述如何访问或生成应用。

    返回:
    - Flask, 返回一个Flask应用实例。

    异常:
    - NoAppException, 如果解析失败或找不到有效的Flask应用时抛出。
    """
    from . import Flask

    try:
        # 解析字符串为Python表达式
        expr = ast.parse(app_name.strip(), mode="eval").body
    except SyntaxError:
        raise NoAppException(
            f"Failed to parse {app_name!r} as an attribute name or function call."
        ) from None

    if isinstance(expr, ast.Name):
        # 处理简单属性访问
        name = expr.id
        args = []
        kwargs = {}
    elif isinstance(expr, ast.Call):
        # 处理函数调用
        if not isinstance(expr.func, ast.Name):
            raise NoAppException(
                f"Function reference must be a simple name: {app_name!r}."
            )

        name = expr.func.id

        try:
            # 将函数参数解析为字面值
            args = [ast.literal_eval(arg) for arg in expr.args]
            kwargs = {
                kw.arg: ast.literal_eval(kw.value)
                for kw in expr.keywords
                if kw.arg is not None
            }
        except ValueError:
            raise NoAppException(
                f"Failed to parse arguments as literal values: {app_name!r}."
            ) from None
    else:
        # 如果表达式不是属性访问或函数调用，则抛出异常
        raise NoAppException(
            f"Failed to parse {app_name!r} as an attribute name or function call."
        )

    try:
        # 从模块中获取属性
        attr = getattr(module, name)
    except AttributeError as e:
        raise NoAppException(
            f"Failed to find attribute {name!r} in {module.__name__!r}."
        ) from e

    if inspect.isfunction(attr):
        # 如果属性是函数，则尝试调用它
        try:
            app = attr(*args, **kwargs)
        except TypeError as e:
            if not _called_with_wrong_args(attr):
                raise

            raise NoAppException(
                f"The factory {app_name!r} in module"
                f" {module.__name__!r} could not be called with the"
                " specified arguments."
            ) from e
    else:
        # 如果属性不是函数，则直接赋值
        app = attr

    if isinstance(app, Flask):
        # 确保找到或生成的对象是一个Flask应用实例
        return app

    raise NoAppException(
        "A valid Flask application was not obtained from"
        f" '{module.__name__}:{app_name}'."
    )


def prepare_import(path: str) -> str:
    """
    根据给定的路径准备导入模块的名称。

    该函数将给定的文件路径转换为Python模块名称，用于导入。
    如果路径以".py"结尾，将删除扩展名。
    如果路径的最后一个部分是"__init__.py"，将使用其父目录作为模块名称。
    通过检查每个目录是否有 "__init__.py" 文件，构建模块名称。
    如果路径不在系统的模块搜索路径中，将其添加到搜索路径的最前面。

    参数:
    path (str): 文件或目录的路径。

    返回:
    str: 准备导入的模块名称。
    """
    # 获取路径的真实路径，以处理任何符号链接或其他形式的路径规范
    path = os.path.realpath(path)

    # 分离文件名和扩展名
    fname, ext = os.path.splitext(path)
    # 如果是Python文件，移除扩展名
    if ext == ".py":
        path = fname

    # 如果文件名是__init__，使用其父目录作为模块名称
    if os.path.basename(path) == "__init__":
        path = os.path.dirname(path)

    # 初始化模块名称列表
    module_name = []

    # 循环以构建模块名称
    while True:
        # 分离路径和名称
        path, name = os.path.split(path)
        # 将名称添加到模块名称列表
        module_name.append(name)

        # 如果当前路径没有__init__.py文件，跳出循环
        if not os.path.exists(os.path.join(path, "__init__.py")):
            break

    # 检查路径是否在系统模块搜索路径中，如果不是，则添加
    if sys.path[0] != path:
        sys.path.insert(0, path)

    # 构建并返回模块名称字符串
    return ".".join(module_name[::-1])


@t.overload
def locate_app(
        module_name: str, app_name: str | None, raise_if_not_found: t.Literal[True] = True
) -> Flask: ...


@t.overload
def locate_app(
        module_name: str, app_name: str | None, raise_if_not_found: t.Literal[False] = ...
) -> Flask | None: ...


def locate_app(
        module_name: str, app_name: str | None, raise_if_not_found: bool = True
) -> Flask | None:
    """
    根据模块名和应用名定位Flask应用。

    参数:
    - module_name: 待导入的模块名。
    - app_name: 待查找的应用名，如果为None，则自动寻找最佳应用。
    - raise_if_not_found: 如果未找到应用且此参数为True，则抛出异常。

    返回:
    - 返回找到的Flask应用实例，如果没有找到且raise_if_not_found为False，则返回None。
    """
    # 尝试导入模块
    try:
        __import__(module_name)
    except ImportError:
        # 检查ImportError是否在当前模块导入过程中发生
        if sys.exc_info()[2].tb_next:  # type: ignore[union-attr]
            # 如果是，则提供详细的错误信息
            raise NoAppException(
                f"While importing {module_name!r}, an ImportError was"
                f" raised:\n\n{traceback.format_exc()}"
            ) from None
        elif raise_if_not_found:
            # 如果不是，且允许抛出未找到应用的异常，则抛出异常
            raise NoAppException(f"Could not import {module_name!r}.") from None
        else:
            # 如果不是，且不允许抛出异常，则返回None
            return None

    # 获取导入的模块
    module = sys.modules[module_name]

    # 根据应用名是否为空，选择不同的应用查找策略
    if app_name is None:
        # 如果应用名为空，则使用find_best_app函数寻找最佳应用
        return find_best_app(module)
    else:
        # 如果应用名不为空，则使用find_app_by_string函数按名查找应用
        return find_app_by_string(module, app_name)


def get_version(ctx: click.Context, param: click.Parameter, value: t.Any) -> None:
    """
    回调函数，用于打印当前的Python版本、Flask版本和Werkzeug版本。

    当用户请求版本信息时，此函数会从click.Context中提取相关信息，并输出版本信息。

    参数:
    - ctx: click.Context对象，提供命令行工具的上下文信息。
    - param: click.Parameter对象，提供当前处理的参数信息。
    - value: 用户输入的参数值，用于判断是否触发版本信息的打印。

    返回:
    无返回值，但会根据用户请求打印版本信息并退出程序。
    """
    # 检查用户是否请求了版本信息，或者是否在解析命令行参数
    if not value or ctx.resilient_parsing:
        return

    # 使用importlib.metadata获取Flask和Werkzeug的版本信息
    flask_version = importlib.metadata.version("flask")
    werkzeug_version = importlib.metadata.version("werkzeug")

    # 打印Python、Flask和Werkzeug的版本信息
    click.echo(
        f"Python {platform.python_version()}\n"
        f"Flask {flask_version}\n"
        f"Werkzeug {werkzeug_version}",
        color=ctx.color,
    )
    # 打印完版本信息后，退出程序
    ctx.exit()


version_option = click.Option(
    ["--version"],
    help="Show the Flask version.",
    expose_value=False,
    callback=get_version,
    is_flag=True,
    is_eager=True,
)


# ScriptInfo 类用于处理 Flask 应用程序，主要用于内部与 Click 的调度。主要功能如下：
# 初始化：
# app_import_path: 应用程序的导入路径。
# create_app: 创建应用程序实例的函数。
# set_debug_flag: 是否设置调试标志。
# data: 存储任意数据的字典。
# _loaded_app: 已加载的应用程序实例。
# 方法：
# load_app: 加载 Flask 应用程序（如果尚未加载），并返回它。多次调用只会返回已加载的应用程序。
# 如果 create_app 函数存在，则调用该函数创建应用。
# 否则，尝试从 app_import_path 导入应用。
# 如果 app_import_path 不存在，尝试从 wsgi.py 或 app.py 文件中导入应用。
# 如果找不到应用，抛出 NoAppException 异常。
# 如果 set_debug_flag 为 True，设置应用的调试模式。
# 返回加载的应用程序实例。
class ScriptInfo:
    def __init__(
            self,
            app_import_path: str | None = None,
            create_app: t.Callable[..., Flask] | None = None,
            set_debug_flag: bool = True,
    ) -> None:
        """
        初始化函数，用于配置和启动Flask应用。

        :param app_import_path: 应用的导入路径，如'package.module:app'。如果提供，将使用此路径导入应用。
        :param create_app: 一个可调用的函数，用于创建Flask应用实例。如果提供，将优先使用此方法创建应用。
        :param set_debug_flag: 布尔值，指示是否设置调试标志。如果为True，将应用配置为调试模式。
        """
        # 存储应用的导入路径
        self.app_import_path = app_import_path
        # 存储创建应用实例的可调用对象
        self.create_app = create_app
        # 初始化一个空字典，用于存储任意数据
        self.data: dict[t.Any, t.Any] = {}
        # 存储调试标志的设置
        self.set_debug_flag = set_debug_flag
        # 初始化应用实例的存储，初始为None
        self._loaded_app: Flask | None = None

    def load_app(self) -> Flask:
        """
        加载Flask应用。

        此方法首先检查是否已经加载了应用，如果已加载，则直接返回该应用。
        如果未加载应用，它将尝试通过两种方式加载：
        1. 使用提供的create_app函数创建应用。
        2. 根据提供的app_import_path导入并定位应用。

        如果上述方法都失败，将尝试默认加载'wsgi.py'或'app.py'文件中的应用。
        如果无法找到应用，将抛出NoAppException异常。

        此外，如果设置了调试标志，将设置应用的调试模式。

        Returns:
            Flask: 加载的Flask应用实例。
        Raises:
            NoAppException: 当无法定位到Flask应用时抛出。
        """
        # 检查是否已加载应用，如果已加载，则直接返回
        if self._loaded_app is not None:
            return self._loaded_app

        # 尝试使用提供的create_app函数创建应用
        if self.create_app is not None:
            app: Flask | None = self.create_app()
        else:
            # 尝试根据提供的app_import_path导入并定位应用
            if self.app_import_path:
                path, name = (
                                     re.split(r":(?![\\/])", self.app_import_path, maxsplit=1) + [None]
                             )[:2]
                import_name = prepare_import(path)
                app = locate_app(import_name, name)
            else:
                # 尝试默认加载'wsgi.py'或'app.py'文件中的应用
                for path in ("wsgi.py", "app.py"):
                    import_name = prepare_import(path)
                    app = locate_app(import_name, None, raise_if_not_found=False)

                    if app is not None:
                        break

        # 如果无法找到应用，抛出异常
        if app is None:
            raise NoAppException(
                "Could not locate a Flask application. Use the"
                " 'flask --app' option, 'FLASK_APP' environment"
                " variable, or a 'wsgi.py' or 'app.py' file in the"
                " current directory."
            )

        # 如果设置了调试标志，设置应用的调试模式
        if self.set_debug_flag:
            app.debug = get_debug_flag()

        # 将加载的应用保存以便后续调用，并返回该应用实例
        self._loaded_app = app
        return app


pass_script_info = click.make_pass_decorator(ScriptInfo, ensure=True)

F = t.TypeVar("F", bound=t.Callable[..., t.Any])


def with_appcontext(f: F) -> F:
    """
    一个装饰器工厂函数，用于将Flask应用上下文添加到Click命令中。

    在Flask应用中，许多操作需要在应用上下文中执行，比如访问配置变量或数据库。
    当使用Click库编写命令行接口时，这些命令可能需要访问Flask应用上下文。
    这个装饰器的作用就是确保在Click命令执行时，能够正确地加载和使用Flask应用上下文。

    参数:
    f (F): 被装饰的函数，通常是一个Click命令函数。

    返回:
    F: 返回一个装饰过的函数，它能够在执行时自动推断出Flask应用上下文。
    """

    @click.pass_context
    def decorator(ctx: click.Context, /, *args: t.Any, **kwargs: t.Any) -> t.Any:
        """
        实际的装饰器函数，它会检查当前应用上下文是否存在。
        如果不存在，它会从Click上下文中加载Flask应用，并推断出应用上下文。

        参数:
        ctx (click.Context): Click上下文，用于存储和访问应用特定的数据。
        *args: 传递给被装饰函数的位置参数。
        **kwargs: 传递给被装饰函数的关键字参数。

        返回:
        t.Any: 被装饰函数的返回值，类型不定。
        """
        # 检查当前应用上下文是否已经存在
        if not current_app:
            # 如果不存在，从Click上下文中加载Flask应用
            app = ctx.ensure_object(ScriptInfo).load_app()
            # 将应用上下文推断到Click上下文中
            ctx.with_resource(app.app_context())

        # 调用被装饰的函数
        return ctx.invoke(f, *args, **kwargs)

    # 返回装饰过的函数，同时保留原函数的元数据，如文档字符串和名称
    return update_wrapper(decorator, f)  # type: ignore[return-value]


# 这个类 AppGroup 继承自 click.Group，并重写了 command 和 group 方法：
# command 方法：
# 定义一个命令装饰器，用于将函数转换为 Click 命令。
# 接受可变数量的位置参数和关键词参数，传递给 Click 的 Command 类。
# 提取 with_appcontext 参数（默认为 True），决定是否需要应用上下文。
# 如果需要应用上下文，使用 with_appcontext 函数包装传入的函数 f。
# 最后调用父类的 command 方法，生成并返回一个 Click 的 Command 对象。
# group 方法：
# 定义一个组装饰器，用于创建子命令组。
# 设置默认的类为 AppGroup。
# 调用父类的 group 方法，生成并返回一个 Click 的 Group 对象。
class AppGroup(click.Group):
    def command(  # type: ignore[override]
            self, *args: t.Any, **kwargs: t.Any
    ) -> t.Callable[[t.Callable[..., t.Any]], click.Command]:
        """
        定义一个命令装饰器，用于将函数转换为Click命令。

        此装饰器允许指定是否需要应用上下文。如果未指定或设置为True，它将包裹一个应用上下文管理器。
        这是为了确保在应用上下文中执行命令，这对于需要访问应用资源或配置的命令来说是必需的。

        参数:
        - *args: 可变数量的位置参数，传递给Click的Command类。
        - **kwargs: 可变数量的关键词参数，传递给Click的Command类。
        - with_appcontext: 关键词参数，用于指示是否需要应用上下文，默认为True。

        返回:
        - 一个装饰器函数，该函数接受一个函数作为输入，并返回一个Click的Command对象。
        """
        # 提取with_appcontext参数，决定是否需要应用上下文
        wrap_for_ctx = kwargs.pop("with_appcontext", True)

        def decorator(f: t.Callable[..., t.Any]) -> click.Command:
            """
            装饰器内部函数，用于将传入的函数f转换为一个Click命令。

            参数:
            - f: 一个可调用的函数，将被转换为Click命令。

            返回:
            - 一个Click的Command对象，该对象封装了函数f，并根据配置附加了额外的功能。
            """
            # 如果需要应用上下文，则使用with_appcontext函数包装f
            if wrap_for_ctx:
                f = with_appcontext(f)
            # 将包装后的f函数传递给父类的command方法，生成并返回Click的Command对象
            return super(AppGroup, self).command(*args, **kwargs)(f)  # type: ignore[no-any-return]

        # 返回装饰器函数
        return decorator

    def group(  # type: ignore[override]
            self, *args: t.Any, **kwargs: t.Any
    ) -> t.Callable[[t.Callable[..., t.Any]], click.Group]:
        # 设置默认的类为AppGroup
        kwargs.setdefault("cls", AppGroup)
        # 调用父类的group方法，并忽略类型提示问题
        return super().group(*args, **kwargs)  # type: ignore[no-any-return]


def _set_app(ctx: click.Context, param: click.Option, value: str | None) -> str | None:
    """
    设置应用程序的导入路径。

    此函数是一个Click选项回调函数，用于处理命令行参数中提供的应用程序导入路径。
    它将路径存储在click.Context对象的ScriptInfo对象中。

    参数:
    - ctx: click.Context - Click上下文对象，包含调用信息。
    - param: click.Option - 当前处理的Click选项对象。
    - value: str | None - 传递给选项的值，如果是None则表示选项未设置。

    返回:
    - str | None: 返回传递给选项的值或None，以保持回调函数的幂等性。

    注意:
    - 如果value是None，函数将直接返回None，不进行后续操作。
    - 通过ctx.ensure_object(ScriptInfo)获取ScriptInfo对象，并设置其app_import_path属性。
    """
    if value is None:
        return None

    info = ctx.ensure_object(ScriptInfo)
    info.app_import_path = value
    return value


_app_option = click.Option(
    ["-A", "--app"],
    metavar="IMPORT",
    help=(
        "The Flask application or factory function to load, in the form 'module:name'."
        " Module can be a dotted import or file path. Name is not required if it is"
        " 'app', 'application', 'create_app', or 'make_app', and can be 'name(args)' to"
        " pass arguments."
    ),
    is_eager=True,
    expose_value=False,
    callback=_set_app,
)


def _set_debug(ctx: click.Context, param: click.Option, value: bool) -> bool | None:
    """
    根据用户设置或者环境变量激活 Flask 调试模式。

    当用户通过命令行选项明确设置调试模式，或者在环境中明确设置 `FLASK_DEBUG`
    时，此函数将更新环境变量 `FLASK_DEBUG` 以激活或关闭 Flask 的调试模式。

    参数:
    - ctx: click.Context - Click 库的上下文对象，用于访问命令行参数和源信息。
    - param: click.Option - Click 库的选项对象，用于识别哪个参数被触发。
    - value: bool - 调试模式的布尔值，指示是否应该启用调试模式。

    返回:
    - bool | None: 根据情况返回 None 或者输入的布尔值。
      如果调试模式的设置来源于默认值或环境变量，则返回 None；
      如果用户明确设置了调试模式，则返回对应的布尔值。
    """
    # 忽略类型检查以获取参数源，因为 ctx.get_parameter_source 的类型注解不准确。
    source = ctx.get_parameter_source(param.name)  # type: ignore[arg-type]

    # 检查参数源是否为非用户输入（如默认值或环境变量设置）。
    if source is not None and source in (
            ParameterSource.DEFAULT,
            ParameterSource.DEFAULT_MAP,
    ):
        # 如果是默认值或环境变量设置，不进行任何操作，返回 None。
        return None

    # 根据提供的布尔值更新环境变量 FLASK_DEBUG。
    # 如果 value 为 True，设置 FLASK_DEBUG 为 "1" 以开启调试模式；
    # 如果 value 为 False，设置 FLASK_DEBUG 为 "0" 以关闭调试模式。
    os.environ["FLASK_DEBUG"] = "1" if value else "0"
    # 返回输入的布尔值，指示是否启用了调试模式。
    return value


_debug_option = click.Option(
    ["--debug/--no-debug"],
    help="Set debug mode.",
    expose_value=False,
    callback=_set_debug,
)


def _env_file_callback(
        ctx: click.Context, param: click.Option, value: str | None
) -> str | None:
    """
    处理环境文件路径的回调函数。

    该函数用于检查是否提供了环境文件路径，并在提供时加载环境文件。
    如果没有提供路径（即值为 None），则函数返回 None。
    如果提供了路径，但 python-dotenv 不在安装的模块中，则引发异常。

    参数:
    - ctx: click.Context 实例，包含命令行上下文信息。
    - param: click.Option 实例，表示触发该回调的命令行选项。
    - value: 提供的环境文件路径字符串，如果没有提供，则为 None。

    返回:
    - 如果成功，返回提供的环境文件路径（字符串）。
    - 如果没有提供路径，返回 None。

    引发:
    - click.BadParameter: 如果尝试加载环境文件但未安装 python-dotenv。
    """
    # 如果值为 none
    if value is None:
        return None

    import importlib

    # 尝试导入 dotenv 模块以检查是否安装了 python-dotenv
    try:
        importlib.import_module("dotenv")
    except ImportError:
        # 如果未安装 dotenv 模块，引发异常
        raise click.BadParameter(
            "python-dotenv must be installed to load an env file.",
            ctx=ctx,
            param=param,
        ) from None

    # 加载环境文件
    load_dotenv(value)
    return value


# This option is eager so env vars are loaded as early as possible to be
# used by other options.
_env_file_option = click.Option(
    ["-e", "--env-file"],
    type=click.Path(exists=True, dir_okay=False),
    help="Load environment variables from this file. python-dotenv must be installed.",
    is_eager=True,
    expose_value=False,
    callback=_env_file_callback,
)


# FlaskGroup 是 AppGroup 的子类，用于支持从配置的 Flask 应用加载更多命令。主要功能包括：
# 初始化：
# 接受多个参数，如是否添加默认命令、是否添加版本选项、是否加载 .env 和 .flaskenv 文件等。
# 初始化时设置上下文环境变量前缀为 FLASK。
# 如果 add_default_commands 为 True，则添加 run、shell 和 routes 命令。
# 加载插件命令：
# _load_plugin_commands 方法从 flask.commands 入口点加载插件命令。
# 获取命令：
# get_command 方法首先尝试从内置和插件命令中获取命令，如果失败则尝试从应用中获取命令。
# 如果应用加载失败，显示错误信息并继续。
# 列出命令：
# list_commands 方法返回所有可用命令的列表，包括内置、插件和应用提供的命令。
# 创建上下文：
# make_context 方法设置环境变量 FLASK_RUN_FROM_CLI 以防止 app.run 启动服务器。
# 加载 .env 和 .flaskenv 文件。
# 创建 ScriptInfo 对象并将其作为上下文对象。
# 解析参数：
# parse_args 方法在没有参数时尝试早期加载 --env-file 和 --app 选项。
class FlaskGroup(AppGroup):

    def __init__(
            self,
            add_default_commands: bool = True,
            create_app: t.Callable[..., Flask] | None = None,
            add_version_option: bool = True,
            load_dotenv: bool = True,
            set_debug_flag: bool = True,
            **extra: t.Any,
    ) -> None:
        """
        初始化Click命令行应用程序的基本配置。

        :param add_default_commands: 是否添加默认命令，如run、shell和routes。
        :param create_app: 一个可调用对象，用于创建Flask应用程序。
        :param add_version_option: 是否添加显示版本的选项。
        :param load_dotenv: 是否加载环境变量。
        :param set_debug_flag: 是否设置调试标志。
        :param extra: 用于Click命令的额外参数。
        """
        # 初始化命令行参数列表，包括默认参数和额外参数
        params = list(extra.pop("params", None) or ())
        # 添加环境文件、应用程序和调试选项
        params.extend((_env_file_option, _app_option, _debug_option))

        # 如果配置了添加版本选项，则添加版本选项
        if add_version_option:
            params.append(version_option)

        # 确保context_settings的存在，并设置自动环境变量前缀
        if "context_settings" not in extra:
            extra["context_settings"] = {}
        extra["context_settings"].setdefault("auto_envvar_prefix", "FLASK")

        # 调用父类初始化方法，传入处理后的参数和额外参数
        super().__init__(params=params, **extra)

        # 保存创建应用程序的函数和加载环境变量及调试标志的配置
        self.create_app = create_app
        self.load_dotenv = load_dotenv
        self.set_debug_flag = set_debug_flag

        # 如果配置了添加默认命令，则添加这些命令
        if add_default_commands:
            self.add_command(run_command)
            self.add_command(shell_command)
            self.add_command(routes_command)

        # 标记插件命令是否已加载
        self._loaded_plugin_commands = False

    def _load_plugin_commands(self) -> None:
        """
        加载插件命令。

        此方法用于加载Flask插件注册的命令。它通过入口点从安装的Python包中动态加载命令。
        只有当插件命令尚未加载时，才会执行加载操作。这可以防止重复加载同一命令。

        注意：
        - 此方法专为内部使用设计，不应由外部直接调用。
        - 它依赖于Python的入口点机制，特别是"flask.commands"组的入口点。
        - 方法会根据Python版本使用适当的模块来处理入口点，确保了向后兼容性。
        """
        # 如果插件命令已经加载，则无需进一步操作
        if self._loaded_plugin_commands:
            return

        # 根据Python版本选择合适的入口点处理模块
        if sys.version_info >= (3, 10):
            from importlib import metadata
        else:
            import importlib_metadata as metadata

        # 遍历"flask.commands"组的入口点，动态加载命令
        for ep in metadata.entry_points(group="flask.commands"):
            # 加载命令并以其名称注册到当前上下文中
            self.add_command(ep.load(), ep.name)

        # 标记插件命令已加载状态
        self._loaded_plugin_commands = True

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:
        """
        获取命令对象。

        此方法用于加载并返回指定名称的命令对象。它首先尝试加载已知的命令，
        如果没有找到，它将尝试从当前应用上下文中加载命令。

        参数:
        - ctx: click的上下文对象，用于操作点击命令。
        - name: 命令的名称。

        返回:
        - 如果找到命令，返回click.Command对象；否则返回None。
        """
        # 加载插件命令，以便在调用get_command时，所有命令都是可用的。
        self._load_plugin_commands()

        # 调用基类的get_command方法，尝试获取命令。
        rv = super().get_command(ctx, name)

        # 如果找到了命令，直接返回该命令。
        if rv is not None:
            return rv

        # 获取ScriptInfo对象，用于操作脚本信息。
        info = ctx.ensure_object(ScriptInfo)

        # 尝试加载应用实例。
        try:
            app = info.load_app()
        except NoAppException as e:
            # 如果加载失败，显示错误信息并返回None。
            click.secho(f"Error: {e.format_message()}\n", err=True, fg="red")
            return None

        # 检查当前应用实例，如果不存在或不是目标应用，为上下文添加应用上下文。
        if not current_app or current_app._get_current_object() is not app:  # type: ignore[attr-defined]
            ctx.with_resource(app.app_context())

        # 从应用的CLI中获取命令，并返回。
        return app.cli.get_command(ctx, name)

    def list_commands(self, ctx: click.Context) -> list[str]:
        """
        加载并返回所有命令的列表，包括插件命令和应用程序本身的命令。

        :param ctx: Click上下文对象，用于访问Click应用程序的元数据和状态。
        :return: 返回一个排序后的字符串列表，包含所有的命令。
        """
        # 加载插件命令，确保插件的命令已经被注册。
        self._load_plugin_commands()

        # 初始化命令集合，从超类获取已有的命令。
        rv = set(super().list_commands(ctx))

        # 获取当前应用程序的ScriptInfo对象，该对象包含了应用程序的状态和配置。
        info = ctx.ensure_object(ScriptInfo)

        # 尝试更新命令集合，包括从应用程序对象中加载的命令。
        try:
            rv.update(info.load_app().cli.list_commands(ctx))
        except NoAppException as e:
            # 如果没有应用程序对象，显示错误消息。
            click.secho(f"Error: {e.format_message()}\n", err=True, fg="red")
        except Exception:
            # 如果发生其他异常，显示异常追踪信息。
            click.secho(f"{traceback.format_exc()}\n", err=True, fg="red")

        # 返回排序后的命令列表。
        return sorted(rv)

    def make_context(
            self,
            info_name: str | None,
            args: list[str],
            parent: click.Context | None = None,
            **extra: t.Any,
    ) -> click.Context:
        """
        创建一个新的Click上下文对象。

        这个方法主要用于初始化Click应用程序的上下文。它允许在调用Click命令时，
        传递额外的信息和设置。此外，它还负责加载环境变量和设置应用程序对象。

        参数:
        - info_name (str | None): 命令的名称，用于在帮助信息中显示。
        - args (list[str]): 传递给命令的参数列表。
        - parent (click.Context | None): 父上下文对象，如果命令是在另一个命令的上下文中运行。
        - **extra (t.Any): 任意额外的关键字参数，用于传递额外的信息。

        返回:
        - click.Context: 创建的Click上下文对象。
        """

        # 设置环境变量，指示Flask应用程序是由CLI运行的
        os.environ["FLASK_RUN_FROM_CLI"] = "true"

        # 如果启用了加载环境变量功能，则加载环境变量
        if get_load_dotenv(self.load_dotenv):
            load_dotenv()

        # 如果额外信息中或上下文设置中没有'obj'，则创建并添加一个ScriptInfo对象
        if "obj" not in extra and "obj" not in self.context_settings:
            extra["obj"] = ScriptInfo(
                create_app=self.create_app, set_debug_flag=self.set_debug_flag
            )

        # 调用父类的make_context方法创建Click上下文对象，并传递修改后的参数
        return super().make_context(info_name, args, parent=parent, **extra)

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """
        自定义解析命令行参数的函数。

        当没有提供任何参数且配置属性 `no_args_is_help` 为 True 时，
        处理环境文件选项和应用选项的特殊逻辑。否则，调用父类的 `parse_args` 方法进行参数解析。

        :param ctx: Click 上下文对象，包含命令行信息。
        :param args: 命令行参数列表。
        :return: 解析后的参数列表。
        """
        # 当没有提供任何参数且配置属性 `no_args_is_help` 为 True 时，处理环境文件选项和应用选项
        if not args and self.no_args_is_help:
            _env_file_option.handle_parse_result(ctx, {}, [])
            _app_option.handle_parse_result(ctx, {}, [])

        # 调用父类的 `parse_args` 方法进行参数解析，并返回解析后的参数列表
        return super().parse_args(ctx, args)


def _path_is_ancestor(path: str, other: str) -> bool:
    """
    判断一个路径是否是另一个路径的前缀（祖先）路径。

    这个函数主要用于确定给定的路径 `path` 是否是另一个路径 `other` 的开始部分，
    即 `other` 是否以 `path` 开始，且两者之间的路径关系没有交叉（例如，'a/b' 是 'a/b/c' 的前缀）。

    参数:
    - path: str, 指定的潜在祖先路径。
    - other: str, 另一个路径，检查它是否以指定的 `path` 开始。

    返回值:
    - bool, 如果 `path` 是 `other` 的前缀，则返回 True，否则返回 False。
    """
    # 使用 os.path.join 来安全地拼接两个路径，并通过去除 `path` 部分和处理可能的多余路径分隔符，
    # 检查拼接后的路径是否与 `other` 路径相同，从而判断 `path` 是否是 `other` 的前缀。
    return os.path.join(path, other[len(path):].lstrip(os.sep)) == other


def load_dotenv(path: str | os.PathLike[str] | None = None) -> bool:
    """
    加载 .env 或 .flaskenv 文件中的环境变量。

    :param path: 要加载的 .env 文件的路径。如果未提供，则默认查找当前目录及其父目录中的 .env 或 .flaskenv 文件。
    :return: 返回一个布尔值，表示是否成功加载了环境变量文件。

    该函数首先尝试导入 dotenv 模块，如果导入失败且存在 .env 或 .flaskenv 文件，则提示用户安装 python-dotenv。
    如果成功导入 dotenv 模块且指定了文件路径，则尝试加载指定路径的文件。
    如果没有指定文件路径，则默认查找并加载 .env 或 .flaskenv 文件。
    最终返回一个布尔值，表示是否成功加载了至少一个环境变量文件。
    """
    try:
        # 导入 python-dotenv 模块
        import dotenv
    except ImportError:
        # 如果无法导入 dotenv 模块且存在 .env 或 .flaskenv 文件，则提示用户安装 python-dotenv
        if path or os.path.isfile(".env") or os.path.isfile(".flaskenv"):
            click.secho(
                " * Tip: There are .env or .flaskenv files present."
                ' Do "pip install python-dotenv" to use them.',
                fg="yellow",
                err=True,
            )

        return False

    # 如果指定了文件路径，则尝试加载该文件
    if path is not None:
        if os.path.isfile(path):
            return dotenv.load_dotenv(path, encoding="utf-8")

        return False

    loaded = False

    # 如果没有指定文件路径，则默认查找并加载 .env 或 .flaskenv 文件
    for name in (".env", ".flaskenv"):
        path = dotenv.find_dotenv(name, usecwd=True)

        if not path:
            continue

        dotenv.load_dotenv(path, encoding="utf-8")
        loaded = True

    # 返回一个布尔值，表示是否成功加载了至少一个环境变量文件
    return loaded


def show_server_banner(debug: bool, app_import_path: str | None) -> None:
    """
    显示服务器的启动横幅。

    此函数负责在服务器启动时打印相关信息到控制台。它会检查是否正在从重新加载器运行，
    如果是，则不显示横幅。然后，根据提供的参数，它会打印出Flask应用的导入路径和调试模式的状态。

    参数:
    - debug: 一个布尔值，指示调试模式是否开启。如果为True，调试模式为'on'，否则为'off'。
    - app_import_path: 一个字符串，表示Flask应用的导入路径。如果为None，则不打印应用路径信息。

    返回:
    无返回值。
    """
    # 检查是否正在从重新加载器运行，如果是，则不执行后续代码
    if is_running_from_reloader():
        return

    # 如果app_import_path不是None，则打印Flask应用的导入路径
    if app_import_path is not None:
        click.echo(f" * Serving Flask app '{app_import_path}'")

    # 如果debug不是None，则根据debug的值打印调试模式的状态
    if debug is not None:
        click.echo(f" * Debug mode: {'on' if debug else 'off'}")


# 该函数定义了一个自定义的参数类型 CertParamType，用于处理命令行工具中的证书路径或特定字符串（如 "adhoc"）。
# 初始化：__init__ 方法初始化一个 click.Path 对象，确保提供的路径存在且为文件。
# 转换：convert 方法尝试导入 ssl 模块，如果失败则抛出错误。接着，尝试将输入值转换为路径，如果失败，则将值转换为小写字符串：
# 如果值为 "adhoc"，检查是否安装了 cryptography 库，未安装则抛出错误。
# 尝试通过 import_string 导入值，如果导入的对象是 ssl.SSLContext 类型，则返回该对象，否则抛出错误。
class CertParamType(click.ParamType):
    name = "path"

    # 初始化函数，用于设置类的成员变量
    def __init__(self) -> None:
        # 设置成员变量path_type，用于指定文件路径的条件
        # 选择存在且是文件（非目录）的路径，并解析为绝对路径
        self.path_type = click.Path(exists=True, dir_okay=False, resolve_path=True)

    def convert(
            self, value: t.Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> t.Any:
        """
        转换函数，用于处理证书相关的命令行参数。

        本函数尝试导入 SSL 模块以支持证书相关操作。如果导入失败，将抛出错误提示。
        随后，函数将尝试使用 path_type 方法转换传入的 value。如果转换失败且 value 为字符串 "adhoc"，
        函数将尝试导入 cryptography 库以支持 ad-hoc 证书。如果导入失败，同样会抛出错误提示。
        对于其他字符串值，函数将尝试导入对应的对象。如果导入的对象是 SSLContext 实例，函数将返回该对象。

        :param value: 命令行参数值，可以是文件路径、字符串或 SSLContext 对象的标识。
        :param param: 命令行参数对象，用于提供额外的参数信息。
        :param ctx: 命令行上下文对象，用于提供更广泛的上下文信息。
        :return: 转换后的值，可以是文件路径、字符串或 SSLContext 对象。
        :raises: 如果导入 SSL 模块失败或转换参数失败且无法通过 ad-hoc 方式处理，将抛出 BadParameter 异常。
        """
        try:
            # 导入 SSL 模块
            import ssl
        except ImportError:
            # 如果 SSL 模块导入失败，抛出错误提示
            raise click.BadParameter(
                'Using "--cert" requires Python to be compiled with SSL support.',
                ctx,
                param,
            ) from None

        try:
            # 尝试使用 path_type 方法转换 value
            return self.path_type(value, param, ctx)
        except click.BadParameter:
            # 如果转换失败，将 value 转为小写字符串进行处理
            value = click.STRING(value, param, ctx).lower()

            if value == "adhoc":
                try:
                    # 导入 cryptography 库，用于支持 adhoc 证书
                    import cryptography  # noqa: F401
                except ImportError:
                    # 如果 cryptography 库导入失败，抛出错误提示
                    raise click.BadParameter(
                        "Using ad-hoc certificates requires the cryptography library.",
                        ctx,
                        param,
                    ) from None

                return value

            # 尝试从字符串导入对象
            obj = import_string(value, silent=True)

            if isinstance(obj, ssl.SSLContext):
                # 如果导入的对象是 SSLContext 实例，返回该对象
                return obj

            # 如果上述条件都不满足，重新抛出异常
            raise


def _validate_key(ctx: click.Context, param: click.Parameter, value: t.Any) -> t.Any:
    # 获取证书文件路径
    cert = ctx.params.get("cert")
    # 判断是否为临时证书
    is_adhoc = cert == "adhoc"

    try:
        # 导入 SSLContext 模块
        import ssl
    except ImportError:
        is_context = False
    else:
        # 判断导入的证书是否为 SSLContext 对象
        is_context = isinstance(cert, ssl.SSLContext)

    # 当密钥文件路径非空时进行验证
    if value is not None:
        # 如果是临时证书，则不需要密钥文件，抛出错误
        if is_adhoc:
            raise click.BadParameter(
                'When "--cert" is "adhoc", "--key" is not used.', ctx, param
            )

        # 如果是 SSLContext 对象，则不需要密钥文件，抛出错误
        if is_context:
            raise click.BadParameter(
                'When "--cert" is an SSLContext object, "--key" is not used.',
                ctx,
                param,
            )

        # 如果没有指定证书文件路径，抛出错误
        if not cert:
            raise click.BadParameter('"--cert" must also be specified.', ctx, param)

        # 将证书和密钥文件路径保存到上下文中
        ctx.params["cert"] = cert, value

    # 当证书文件路径为空时进行验证
    else:
        # 如果指定了证书文件路径，但不是临时证书或 SSLContext 对象，抛出错误
        if cert and not (is_adhoc or is_context):
            raise click.BadParameter('Required when using "--cert".', ctx, param)

    # 返回密钥文件路径
    return value


class SeparatedPathType(click.Path):

    def convert(
            self, value: t.Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> t.Any:
        """
        将给定的值根据环境变量的格式进行分割并转换为适当的类型。

        此方法首先使用自定义的split_envvar_value方法将输入的值进行分割，
        然后使用超类（父类）的convert方法对分割后的每个项进行转换，
        从而确保每个分割项都被正确地转换为所需的类型。

        参数:
        - value: t.Any 类型，待转换的值，可以是任何类型。
        - param: click.Parameter | None 类型，Click命令行参数的元数据，可选。
        - ctx: click.Context | None 类型，Click命令的上下文信息，可选。

        返回:
        - t.Any 类型：分割并转换后的值列表。

        注意：
        - 此方法依赖于super().convert方法来进行实际的类型转换。
        - 分割操作由self.split_envvar_value(value)完成，具体逻辑在此方法中未显示。
        """
        # 分割环境变量的值，为后续的转换做准备
        items = self.split_envvar_value(value)
        # 使用父类的convert方法进行转换
        super_convert = super().convert
        # 对每个分割项进行转换，并返回转换后的列表
        return [super_convert(item, param, ctx) for item in items]


@click.command("run", short_help="Run a development server.")
@click.option("--host", "-h", default="127.0.0.1", help="The interface to bind to.")
@click.option("--port", "-p", default=5000, help="The port to bind to.")
@click.option(
    "--cert",
    type=CertParamType(),
    help="Specify a certificate file to use HTTPS.",
    is_eager=True,
)
@click.option(
    "--key",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    callback=_validate_key,
    expose_value=False,
    help="The key file to use when specifying a certificate.",
)
@click.option(
    "--reload/--no-reload",
    default=None,
    help="Enable or disable the reloader. By default the reloader "
         "is active if debug is enabled.",
)
@click.option(
    "--debugger/--no-debugger",
    default=None,
    help="Enable or disable the debugger. By default the debugger "
         "is active if debug is enabled.",
)
@click.option(
    "--with-threads/--without-threads",
    default=True,
    help="Enable or disable multithreading.",
)
@click.option(
    "--extra-files",
    default=None,
    type=SeparatedPathType(),
    help=(
            "Extra files that trigger a reload on change. Multiple paths"
            f" are separated by {os.path.pathsep!r}."
    ),
)
@click.option(
    "--exclude-patterns",
    default=None,
    type=SeparatedPathType(),
    help=(
            "Files matching these fnmatch patterns will not trigger a reload"
            " on change. Multiple patterns are separated by"
            f" {os.path.pathsep!r}."
    ),
)
@pass_script_info
def run_command(
        info: ScriptInfo,
        host: str,
        port: int,
        reload: bool,
        debugger: bool,
        with_threads: bool,
        cert: ssl.SSLContext | tuple[str, str | None] | t.Literal["adhoc"] | None,
        extra_files: list[str] | None,
        exclude_patterns: list[str] | None,
) -> None:
    """
    运行WSGI应用的命令。

    此函数负责根据提供的配置加载应用，并使用指定的主机和端口运行它。
    它还支持自动重新加载、调试器、多线程以及SSL证书配置。

    参数:
    - info: 包含加载应用信息的对象。
    - host: 应用监听的主机名或IP地址。
    - port: 应用监听的端口号。
    - reload: 是否在代码变更时自动重启应用。
    - debugger: 是否使用调试器运行应用。
    - with_threads: 是否使用多线程执行应用。
    - cert: SSL证书配置，用于HTTPS连接。
    - extra_files: 额外监控以触发重新加载的文件列表。
    - exclude_patterns: 排除文件或目录的模式列表。

    返回:
    无返回值。
    """
    try:
        # 加载应用
        app: WSGIApplication = info.load_app()
    except Exception as e:
        # 如果应用加载失败，并且是由代码重新加载触发的，则处理异常
        if is_running_from_reloader():
            traceback.print_exc()
            err = e

            def app(
                    environ: WSGIEnvironment, start_response: StartResponse
            ) -> cabc.Iterable[bytes]:
                # 抛出原始异常
                raise err from None
        else:
            # 如果不是由重新加载触发的异常，则直接抛出
            raise e from None

    # 获取调试标志
    debug = get_debug_flag()

    # 如果未明确指定是否需要代码变更自动重启，则根据调试标志决定
    if reload is None:
        reload = debug

    # 如果未明确指定是否需要使用调试器，则根据调试标志决定
    if debugger is None:
        debugger = debug

    # 显示服务器横幅信息
    show_server_banner(debug, info.app_import_path)

    # 运行应用
    run_simple(
        host,
        port,
        app,
        use_reloader=reload,
        use_debugger=debugger,
        threaded=with_threads,
        ssl_context=cert,
        extra_files=extra_files,
        exclude_patterns=exclude_patterns,
    )


run_command.params.insert(0, _debug_option)


@click.command("shell", short_help="Run a shell in the app context.")
@with_appcontext
def shell_command() -> None:
    """
    创建一个交互式Python shell环境。

    这个函数设置了一个交互式Python shell的环境，包括设置横幅信息、初始化shell上下文、
    配置自动补全和调用系统的交互式钩子。最后，它使用code模块的interact函数启动一个
    交互式Python会话。

    参数:
        无

    返回:
        None
    """

    import code

    # 构建欢迎横幅信息
    banner = (
        f"Python {sys.version} on {sys.platform}\n"
        f"App: {current_app.import_name}\n"
        f"Instance: {current_app.instance_path}"
    )

    # 初始化上下文字典
    ctx: Dict[str, Any] = {}

    # 加载PYTHONSTARTUP文件中的命令
    startup = os.environ.get("PYTHONSTARTUP")
    if startup and os.path.isfile(startup):
        with open(startup) as f:
            eval(compile(f.read(), startup, "exec"), ctx)

    # 更新shell上下文
    ctx.update(current_app.make_shell_context())

    # 尝试获取并配置交互式钩子
    interactive_hook = getattr(sys, "__interactivehook__", None)

    if interactive_hook is not None:
        try:
            import readline
            from rlcompleter import Completer
        except ImportError:
            pass
        else:
            # 配置自动补全
            readline.set_completer(Completer(ctx).complete)

        # 调用交互式钩子
        interactive_hook()

    # 启动交互式Python会话
    code.interact(banner=banner, local=ctx)


@click.command("routes", short_help="Show the routes for the app.")
@click.option(
    "--sort",
    "-s",
    type=click.Choice(("endpoint", "methods", "domain", "rule", "match")),
    default="endpoint",
    help=(
            "Method to sort routes by. 'match' is the order that Flask will match routes"
            " when dispatching a request."
    ),
)
@click.option("--all-methods", is_flag=True, help="Show HEAD and OPTIONS methods.")
@with_appcontext
def routes_command(sort: str, all_methods: bool) -> None:
    """
    输出应用的所有路由信息。

    :param sort: 路由排序的依据。
    :param all_methods: 是否显示所有HTTP方法，包括HEAD和OPTIONS。
    :return: 无返回值。
    """
    # 获取应用中所有定义的路由规则
    rules = list(current_app.url_map.iter_rules())

    # 如果没有路由规则，则输出提示信息
    if not rules:
        click.echo("No routes were registered.")
        return

    # 初始化不需要显示的方法集合，如果all_methods为True，则不忽略任何方法
    ignored_methods = set() if all_methods else {"HEAD", "OPTIONS"}
    # 判断应用的路由是否启用了主机匹配
    host_matching = current_app.url_map.host_matching
    # 判断是否有规则绑定了特定的域名或子域名
    has_domain = any(rule.host if host_matching else rule.subdomain for rule in rules)
    # 初始化存储所有路由信息的列表
    rows = []

    # 遍历所有路由规则，收集路由信息
    for rule in rules:
        # 初始化当前路由的信息列表
        row = [
            rule.endpoint,
            ", ".join(sorted((rule.methods or set()) - ignored_methods)),
        ]

        # 如果路由规则绑定了特定的域名或子域名，则添加到信息列表中
        if has_domain:
            row.append((rule.host if host_matching else rule.subdomain) or "")

        # 添加路由规则到信息列表中
        row.append(rule.rule)
        # 将当前路由的信息添加到所有路由信息列表中
        rows.append(row)

    # 定义输出表头的标题
    headers = ["Endpoint", "Methods"]
    # 定义路由排序的依据
    sorts = ["endpoint", "methods"]

    # 如果路由规则绑定了特定的域名或子域名，则添加相应的表头和排序依据
    if has_domain:
        headers.append("Host" if host_matching else "Subdomain")
        sorts.append("domain")

    # 添加路由规则的路径作为表头和排序依据
    headers.append("Rule")
    sorts.append("rule")

    # 尝试根据用户指定的排序依据对路由信息进行排序
    try:
        rows.sort(key=itemgetter(sorts.index(sort)))
    except ValueError:
        pass

    # 在路由信息列表的最前面添加表头
    rows.insert(0, headers)
    # 计算每列的最大宽度，用于格式化输出
    widths = [max(len(row[i]) for row in rows) for i in range(len(headers))]
    # 在表头下面添加分隔行
    rows.insert(1, ["-" * w for w in widths])
    # 定义输出的格式模板
    template = "  ".join(f"{{{i}:<{w}}}" for i, w in enumerate(widths))

    # 遍历路由信息列表，格式化并输出每一行
    for row in rows:
        click.echo(template.format(*row))


cli = FlaskGroup(
    name="flask",
    help="""
    用于Flask应用程序的通用实用程序脚本。
    要加载的应用程序必须带有‘——app’选项，
    ‘FLASK_APP’环境变量，或者使用‘wsgi.py’或‘app.py’文件
    在当前目录中。
    """
)


def main() -> None:
    cli.main()


if __name__ == '__main__':
    main()
