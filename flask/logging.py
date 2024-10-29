from __future__ import annotations

import logging
import sys
import typing as t

from werkzeug.local import LocalProxy

from .globals import request

if t.TYPE_CHECKING:  # pragma: no cover
    from .sansio.app import App


@LocalProxy
def wsgi_errors_stream() -> t.TextIO:
    """
    提供对当前请求的 WSGI 错误流的访问，如果可用。

    此函数用作 LocalProxy 的装饰器，旨在根据当前请求的上下文动态提供对 WSGI 错误流的访问。
    如果当前没有活动的请求，它将回退到 sys.stderr，确保总是有一个有效的错误输出流。

    :return: 当前请求的 WSGI 错误流，或者如果没有活动请求，则为 sys.stderr。
    :rtype: t.TextIO
    """
    if request:
        # 当前请求存在时，从其环境中获取 wsgi.errors 流。
        return request.environ["wsgi.errors"]  # type: ignore[no-any-return]

    # 如果没有活动的请求，回退到全局的错误流 sys.stderr。
    return sys.stderr



def has_level_handler(logger: logging.Logger) -> bool:
    """
    检查logger是否设置了有效级别的处理器。

    该函数通过检查logger及其父logger的有效级别来确定是否存在符合条件的处理器。
    它首先获取logger的有效日志级别，然后遍历logger及其父logger，检查它们的处理器是否满足该级别。

    参数:
    logger (logging.Logger): 需要检查的logger实例。

    返回:
    bool: 如果找到了满足有效级别的处理器则返回True，否则返回False。
    """
    # 获取logger的有效日志级别
    level = logger.getEffectiveLevel()
    current = logger

    # 遍历logger及其父logger
    while current:
        # 检查当前logger是否有满足有效级别的处理器
        if any(handler.level <= level for handler in current.handlers):
            return True

        # 如果当前logger不传播日志事件，则停止检查
        if not current.propagate:
            break

        # 移动到父logger
        current = current.parent  # type: ignore

    # 如果没有找到满足条件的处理器，返回False
    return False



default_handler = logging.StreamHandler(wsgi_errors_stream)  # type: ignore
default_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
)


def create_logger(app: App) -> logging.Logger:
    """
    创建一个日志记录器。

    根据应用程序的名称创建一个日志记录器，并根据应用程序的调试模式设置日志级别。
    如果日志记录器没有设置级别，则默认设置为DEBUG级别（仅当应用程序处于调试模式时）。
    此外，如果日志记录器没有设置处理程序，则添加一个默认的处理程序。

    参数:
    app: App - 一个表示应用程序的对象，包含应用程序的名称和调试模式。

    返回:
    logging.Logger - 一个配置好的日志记录器对象。
    """
    # 获取或创建一个以应用程序名称命名的日志记录器
    logger = logging.getLogger(app.name)

    # 如果应用程序处于调试模式且日志记录器尚未设置级别，则设置为DEBUG级别
    if app.debug and not logger.level:
        logger.setLevel(logging.DEBUG)

    # 如果日志记录器没有设置处理程序，则添加一个默认的处理程序
    if not has_level_handler(logger):
        logger.addHandler(default_handler)

    # 返回配置好的日志记录器
    return logger

