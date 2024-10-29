from __future__ import annotations

import os
import typing as t
from datetime import timedelta

from .cli import AppGroup
from .globals import current_app
from .helpers import send_from_directory
from .sansio.blueprints import Blueprint as SansioBlueprint
from .sansio.blueprints import BlueprintSetupState as BlueprintSetupState  # noqa
from .sansio.scaffold import _sentinel

if t.TYPE_CHECKING:  # pragma: no cover
    from .wrappers import Response


class Blueprint(SansioBlueprint):
    """
    自定义蓝图类，继承自SansioBlueprint。
    用于创建带有特定配置的蓝图，如静态文件夹、模板文件夹等。
    """

    def __init__(
        self,
        name: str,
        import_name: str,
        static_folder: str | os.PathLike[str] | None = None,
        static_url_path: str | None = None,
        template_folder: str | os.PathLike[str] | None = None,
        url_prefix: str | None = None,
        subdomain: str | None = None,
        url_defaults: dict[str, t.Any] | None = None,
        root_path: str | None = None,
        cli_group: str | None = _sentinel,  # type: ignore
    ) -> None:
        """
        初始化蓝图的配置。
        :param name: 蓝图的名称。
        :param import_name: 用于导入的名称。
        :param static_folder: 静态文件的路径。
        :param static_url_path: 静态资源的URL路径。
        :param template_folder: 模板文件的路径。
        :param url_prefix: URL的前缀。
        :param subdomain: 子域名。
        :param url_defaults: URL的默认值。
        :param root_path: 根路径。
        :param cli_group: CLI组的名称。
        """
        super().__init__(
            name,
            import_name,
            static_folder,
            static_url_path,
            template_folder,
            url_prefix,
            subdomain,
            url_defaults,
            root_path,
            cli_group,
        )

        # 初始化CLI对象，并设置其名称为当前蓝图的名称
        self.cli = AppGroup()
        self.cli.name = self.name

    def get_send_file_max_age(self, filename: str | None) -> int | None:
        """
        获取发送文件的最大年龄。
        :param filename: 文件名。
        :return: 文件的最大年龄，以秒为单位，或者None。
        """
        # 从当前应用的配置中获取文件发送的最大年龄默认值
        value = current_app.config["SEND_FILE_MAX_AGE_DEFAULT"]

        # 如果配置的值为None，则直接返回None
        if value is None:
            return None

        # 如果配置的值是timedelta类型，则将其转换为秒
        if isinstance(value, timedelta):
            return int(value.total_seconds())

        # 直接返回配置的值，忽略类型检查
        return value  # type: ignore[no-any-return]

    def send_static_file(self, filename: str) -> Response:
        """
        发送静态文件。
        :param filename: 要发送的文件名。
        :return: 包含文件的Response对象。
        """
        # 检查蓝图是否配置了静态文件夹，如果没有则抛出异常
        if not self.has_static_folder:
            raise RuntimeError("'static_folder' must be set to serve static_files.")

        # 获取文件发送的最大年龄
        max_age = self.get_send_file_max_age(filename)
        # 从静态文件夹中发送文件，并设置最大年龄
        return send_from_directory(
            t.cast(str, self.static_folder), filename, max_age=max_age
        )

    def open_resource(
        self, resource: str, mode: str = "rb", encoding: str | None = "utf-8"
    ) -> t.IO[t.AnyStr]:
        """
        打开资源文件。
        :param resource: 资源文件的路径。
        :param mode: 文件打开模式。
        :param encoding: 文件编码。
        :return: 文件对象。
        """
        # 检查文件打开模式是否为只读模式，如果不是则抛出异常
        if mode not in {"r", "rt", "rb"}:
            raise ValueError("Resources can only be opened for reading.")

        # 拼接资源文件的绝对路径
        path = os.path.join(self.root_path, resource)

        # 根据模式打开文件并返回文件对象
        if mode == "rb":
            return open(path, mode)

        return open(path, mode, encoding=encoding)
