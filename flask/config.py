from __future__ import annotations

import errno
import json
import os
import types
import typing as t

from werkzeug.utils import import_string

if t.TYPE_CHECKING:
    import typing_extensions as te

    from .sansio.app import App


T = t.TypeVar("T")


class ConfigAttribute(t.Generic[T]):
    """
    一个描述符类，用于管理应用程序配置属性。

    该类允许通过应用程序配置字典访问和设置属性，同时支持在获取属性值时进行类型转换。
    """

    def __init__(
        self, name: str, get_converter: t.Callable[[t.Any], T] | None = None
    ) -> None:
        """
        初始化ConfigAttribute实例。

        参数:
        - name: 配置属性的名称。
        - get_converter: 一个可选的函数，用于在获取配置属性值时将其转换为所需的类型。
        """
        self.__name__ = name
        self.get_converter = get_converter

    @t.overload
    def __get__(self, obj: None, owner: None) -> te.Self: ...

    @t.overload
    def __get__(self, obj: App, owner: type[App]) -> T: ...

    def __get__(self, obj: App | None, owner: type[App] | None = None) -> T | te.Self:
        """
        描述符的获取方法，用于访问配置属性。

        参数:
        - obj: 拥有该配置属性的应用程序实例，如果通过类访问则为None。
        - owner: 拥有该配置属性的应用程序类，如果通过实例访问则忽略。

        返回:
        - 如果通过类访问，返回ConfigAttribute实例。
        - 如果通过实例访问，返回配置属性的值，如果指定了get_converter，则进行类型转换。
        """
        if obj is None:
            return self

        rv = obj.config[self.__name__]

        if self.get_converter is not None:
            rv = self.get_converter(rv)

        return rv  # type: ignore[no-any-return]

    def __set__(self, obj: App, value: t.Any) -> None:
        """
        描述符的设置方法，用于设置配置属性。

        参数:
        - obj: 拥有该配置属性的应用程序实例。
        - value: 要设置给配置属性的值。
        """
        obj.config[self.__name__] = value



class Config(dict):  # type: ignore[type-arg]
    """
    继承自dict的配置类，为应用程序提供灵活的配置选项。
    """

    def __init__(
        self,
        root_path: str | os.PathLike[str],
        defaults: dict[str, t.Any] | None = None,
    ) -> None:
        """
        初始化配置对象。

        :param root_path: 配置文件的根路径。
        :param defaults: 默认配置值，可选。
        """
        super().__init__(defaults or {})
        self.root_path = root_path

    def from_envvar(self, variable_name: str, silent: bool = False) -> bool:
        """
        从环境变量中加载配置。

        :param variable_name: 包含配置文件路径的环境变量名。
        :param silent: 如果环境变量未设置，是否静默失败而不抛出异常。
        :return: 成功加载配置返回True，否则返回False。
        """
        rv = os.environ.get(variable_name)
        if not rv:
            if silent:
                return False
            raise RuntimeError(
                f"The environment variable {variable_name!r} is not set"
                " and as such configuration could not be loaded. Set"
                " this variable and make it point to a configuration"
                " file"
            )
        return self.from_pyfile(rv, silent=silent)

    def from_prefixed_env(
        self, prefix: str = "FLASK", *, loads: t.Callable[[str], t.Any] = json.loads
    ) -> bool:
        """
        从以特定前缀开头的环境变量中加载配置。

        :param prefix: 环境变量前缀。
        :param loads: 用于解析环境变量值的函数，默认为json.loads。
        :return: 成功加载配置返回True。
        """
        prefix = f"{prefix}_"
        len_prefix = len(prefix)

        for key in sorted(os.environ):
            if not key.startswith(prefix):
                continue

            value = os.environ[key]

            try:
                value = loads(value)
            except Exception:
                pass

            key = key[len_prefix:]

            if "__" not in key:
                # A non-nested key, set directly.
                self[key] = value
                continue

            current = self
            *parts, tail = key.split("__")

            for part in parts:
                if part not in current:
                    current[part] = {}

                current = current[part]

            current[tail] = value

        return True

    def from_pyfile(
        self, filename: str | os.PathLike[str], silent: bool = False
    ) -> bool:
        """
        从Python文件中加载配置。

        :param filename: 配置文件名。
        :param silent: 如果文件未找到，是否静默失败而不抛出异常。
        :return: 成功加载配置返回True，否则返回False。
        """
        filename = os.path.join(self.root_path, filename)
        d = types.ModuleType("config")
        d.__file__ = filename
        try:
            with open(filename, mode="rb") as config_file:
                exec(compile(config_file.read(), filename, "exec"), d.__dict__)
        except OSError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR, errno.ENOTDIR):
                return False
            e.strerror = f"Unable to load configuration file ({e.strerror})"
            raise
        self.from_object(d)
        return True

    def from_object(self, obj: object | str) -> None:
        """
        从Python对象中加载配置。

        :param obj: 包含配置的Python对象或其导入路径。
        """
        if isinstance(obj, str):
            obj = import_string(obj)
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)

    def from_file(
        self,
        filename: str | os.PathLike[str],
        load: t.Callable[[t.IO[t.Any]], t.Mapping[str, t.Any]],
        silent: bool = False,
        text: bool = True,
    ) -> bool:
        """
        从文件中加载配置，使用自定义的加载函数。

        :param filename: 配置文件名。
        :param load: 用于加载配置文件的函数。
        :param silent: 如果文件未找到，是否静默失败而不抛出异常。
        :param text: 是否以文本模式打开文件。
        :return: 成功加载配置返回True，否则返回False。
        """
        filename = os.path.join(self.root_path, filename)

        try:
            with open(filename, "r" if text else "rb") as f:
                obj = load(f)
        except OSError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR):
                return False

            e.strerror = f"Unable to load configuration file ({e.strerror})"
            raise

        return self.from_mapping(obj)

    def from_mapping(
        self, mapping: t.Mapping[str, t.Any] | None = None, **kwargs: t.Any
    ) -> bool:
        """
        从映射对象中加载配置。

        :param mapping: 包含配置的映射对象，可选。
        :param kwargs: 额外的配置项。
        :return: 成功更新配置返回True。
        """
        mappings: dict[str, t.Any] = {}
        if mapping is not None:
            mappings.update(mapping)
        mappings.update(kwargs)
        for key, value in mappings.items():
            if key.isupper():
                self[key] = value
        return True

    def get_namespace(
        self, namespace: str, lowercase: bool = True, trim_namespace: bool = True
    ) -> dict[str, t.Any]:
        """
        获取特定命名空间的配置项。

        :param namespace: 命名空间前缀。
        :param lowercase: 是否将配置键转换为小写。
        :param trim_namespace: 是否移除配置键的命名空间前缀。
        :return: 包含指定命名空间配置项的字典。
        """
        rv = {}
        for k, v in self.items():
            if not k.startswith(namespace):
                continue
            if trim_namespace:
                key = k[len(namespace) :]
            else:
                key = k
            if lowercase:
                key = key.lower()
            rv[key] = v
        return rv

    def __repr__(self) -> str:
        """
        返回配置对象的字符串表示。

        :return: 配置对象的字符串表示。
        """
        return f"<{type(self).__name__} {dict.__repr__(self)}>"

