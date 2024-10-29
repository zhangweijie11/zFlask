"""
Tagged JSON
~~~~~~~~~~~

A compact representation for lossless serialization of non-standard JSON
types. :class:`~flask.sessions.SecureCookieSessionInterface` uses this
to serialize the session data, but it may be useful in other places. It
can be extended to support other types.

.. autoclass:: TaggedJSONSerializer
    :members:

.. autoclass:: JSONTag
    :members:

Let's see an example that adds support for
:class:`~collections.OrderedDict`. Dicts don't have an order in JSON, so
to handle this we will dump the items as a list of ``[key, value]``
pairs. Subclass :class:`JSONTag` and give it the new key ``' od'`` to
identify the type. The session serializer processes dicts first, so
insert the new tag at the front of the order since ``OrderedDict`` must
be processed before ``dict``.

.. code-block:: python

    from flask.json.tag import JSONTag

    class TagOrderedDict(JSONTag):
        __slots__ = ('serializer',)
        key = ' od'

        def check(self, value):
            return isinstance(value, OrderedDict)

        def to_json(self, value):
            return [[k, self.serializer.tag(v)] for k, v in iteritems(value)]

        def to_python(self, value):
            return OrderedDict(value)

    app.session_interface.serializer.register(TagOrderedDict, index=0)
"""

from __future__ import annotations

import typing as t
from base64 import b64decode
from base64 import b64encode
from datetime import datetime
from uuid import UUID

from markupsafe import Markup
from werkzeug.http import http_date
from werkzeug.http import parse_date

from ..json import dumps
from ..json import loads

# 这段代码定义了一个名为 JSONTag 的类，用于为特定类型的对象添加标签，以便在序列化和反序列化过程中识别这些对象。具体功能如下：
# 初始化：__init__ 方法接收一个 TaggedJSONSerializer 对象作为参数，并将其存储在实例变量 self.serializer 中。
# 检查：check 方法用于检查给定值是否应该被当前标签标记，但具体实现需要子类提供。
# 转换为 JSON：to_json 方法将 Python 对象转换为有效的 JSON 类型，但具体实现需要子类提供。
# 转换为 Python 对象：to_python 方法将 JSON 表示转换回原始的 Python 类型，但具体实现需要子类提供。
# 添加标签：tag 方法将值转换为有效的 JSON 类型，并添加标签结构。
class JSONTag:
    """
    JSONTag类是一个基类，用于定义将Python对象转换为JSON对象时的标签行为。
    它通过`TaggedJSONSerializer`提供的序列化器来处理特定类型的Python对象的转换。

    属性:
    - `serializer`: 一个`TaggedJSONSerializer`实例，用于实际的序列化和反序列化工作。

    `__slots__`用于优化内存使用，限制实例属性的动态性，确保只能设置`serializer`属性。
    """

    __slots__ = ("serializer",)

    # `key`是一个类变量，表示在JSON中使用的键名。
    key: str = ""

    def __init__(self, serializer: TaggedJSONSerializer) -> None:
        """
        初始化JSONTag实例。

        参数:
        - `serializer`: 一个`TaggedJSONSerializer`实例，用于处理对象的序列化和反序列化。
        """
        self.serializer = serializer

    def check(self, value: t.Any) -> bool:
        """
        检查给定的值是否可以由当前标签转换为JSON。

        参数:
        - `value`: 任意类型的值，用于检查是否可以被转换。

        返回:
        - `bool`: 如果值可以被转换，则返回True；否则返回False。

        此方法需要在子类中实现具体逻辑。
        """
        raise NotImplementedError

    def to_json(self, value: t.Any) -> t.Any:
        """
        将给定的Python对象转换为JSON兼容的格式。

        参数:
        - `value`: 任意类型的Python对象，将被转换为JSON格式。

        返回:
        - `t.Any`: 转换后的JSON兼容对象。

        此方法需要在子类中实现具体逻辑。
        """
        raise NotImplementedError

    def to_python(self, value: t.Any) -> t.Any:
        """
        将JSON兼容的格式转换回Python对象。

        参数:
        - `value`: JSON兼容的格式，将被转换回Python对象。

        返回:
        - `t.Any`: 转换后的Python对象。

        此方法需要在子类中实现具体逻辑。
        """
        raise NotImplementedError

    def tag(self, value: t.Any) -> dict[str, t.Any]:
        """
        将给定的值转换为带有标签的JSON字典。

        参数:
        - `value`: 任意类型的值，将被转换为带有标签的JSON字典。

        返回:
        - `dict[str, t.Any]`: 包含转换后的JSON对象的字典，键为`self.key`。
        """
        return {self.key: self.to_json(value)}



class TagDict(JSONTag):
    """
    TagDict类继承自JSONTag，用于处理特定格式的字典数据。
    它提供了检查数据格式、将数据转换为JSON格式和将JSON格式数据转换回Python格式的功能。
    """

    # 定义__slots__以限制实例可以添加的属性，这里不需要额外的属性，所以为空元组
    __slots__ = ()
    # 定义一个类变量key，用于标识和处理字典中的键
    key = " di"

    def check(self, value: t.Any) -> bool:
        """
        检查输入的值是否为字典类型，且只有一个键值对，该键存在于序列化器的标签中。

        参数:
        - value: t.Any 类型，待检查的数据。

        返回:
        - bool 类型，如果数据满足条件则返回True，否则返回False。
        """
        return (
            isinstance(value, dict)  # 检查是否为字典类型
            and len(value) == 1  # 检查字典是否只有一个键值对
            and next(iter(value)) in self.serializer.tags  # 检查键是否在序列化器的标签中
        )

    def to_json(self, value: t.Any) -> t.Any:
        """
        将符合特定格式的字典数据转换为JSON格式。

        参数:
        - value: t.Any 类型，待转换的字典数据。

        返回:
        - t.Any 类型，转换后的JSON格式数据。
        """
        # 获取字典的键，由于只有一个键，使用next(iter(value))获取
        key = next(iter(value))
        # 将字典的键值对按照特定格式转换为JSON格式
        return {f"{key}__": self.serializer.tag(value[key])}

    def to_python(self, value: t.Any) -> t.Any:
        """
        将特定格式的JSON数据转换回Python的字典格式。

        参数:
        - value: t.Any 类型，待转换的JSON数据。

        返回:
        - t.Any 类型，转换后的Python字典数据。
        """
        # 获取JSON数据的键，使用next(iter(value))获取
        key = next(iter(value))
        # 将JSON数据的键值对按照特定格式转换回Python字典格式
        return {key[:-2]: value[key]}



class PassDict(JSONTag):
    """
    PassDict类继承自JSONTag，用于处理字典类型的对象转换为JSON格式。
    它提供了检查对象是否为字典类型的方法，以及将字典对象转换为JSON格式的方法。
    """
    __slots__ = ()  # 定义__slots__属性，限制实例可以添加的属性列表，这里不需要添加任何属性。

    def check(self, value: t.Any) -> bool:
        """
        检查给定的值是否为字典类型。

        参数:
        value: t.Any - 待检查的值，可以是任意类型。

        返回:
        bool - 如果给定的值是字典类型，则返回True，否则返回False。
        """
        return isinstance(value, dict)

    def to_json(self, value: t.Any) -> t.Any:
        """
        将字典对象转换为JSON格式。

        此方法通过遍历字典的键值对，使用序列化器的tag方法将每个值转换为相应的JSON格式，
        并保持键不变，最终返回一个新的字典，其中包含转换后的键值对。

        参数:
        value: t.Any - 待转换为JSON格式的字典对象。

        返回:
        t.Any - 转换后的JSON格式的字典对象。
        """
        return {k: self.serializer.tag(v) for k, v in value.items()}

    tag = to_json  # tag方法引用to_json方法，提供了一种通过tag名称访问to_json功能的方式。



class TagTuple(JSONTag):
    """
    TagTuple类继承自JSONTag，用于处理tuple类型的数据。
    它实现了将tuple类型的数据转换为JSON格式和将JSON格式的数据转换回tuple的功能。
    """
    __slots__ = ()  # 表示该类没有额外的属性，节省内存。
    key = " t"  # 定义一个键，可能用于标识或查找。

    def check(self, value: t.Any) -> bool:
        """
        检查给定的值是否为tuple类型。

        参数:
        - value: t.Any 类型，表示可以接受任何类型的值。

        返回:
        - bool 类型，如果value是tuple类型，则返回True，否则返回False。
        """
        return isinstance(value, tuple)

    def to_json(self, value: t.Any) -> t.Any:
        """
        将tuple类型的值转换为JSON格式的数组。

        参数:
        - value: t.Any 类型，表示可以接受任何类型的值。

        返回:
        - t.Any 类型，返回一个列表，其中每个元素都是value中对应元素的JSON表示。
        """
        return [self.serializer.tag(item) for item in value]

    def to_python(self, value: t.Any) -> t.Any:
        """
        将JSON格式的数组转换回tuple类型。

        参数:
        - value: t.Any 类型，表示可以接受任何类型的值。

        返回:
        - t.Any 类型，返回一个元组，包含原始JSON数组中的元素。
        """
        return tuple(value)


class PassList(JSONTag):
    """
    PassList类继承自JSONTag，用于处理列表类型的标签。
    它提供了检查数据类型和将数据转换为JSON格式的功能。
    """

    # 定义__slots__属性，防止动态添加属性，确保内存安全。
    __slots__ = ()

    def check(self, value: t.Any) -> bool:
        """
        检查输入值是否为列表类型。

        参数:
        - value: 待检查的值，类型为任意。

        返回:
        - 如果值是列表类型，返回True；否则返回False。
        """
        return isinstance(value, list)

    def to_json(self, value: t.Any) -> t.Any:
        """
        将列表中的每个项目转换为JSON格式。

        参数:
        - value: 待转换的值，类型为任意。

        返回:
        - 转换后的列表，其中每个项目都转换为JSON格式。
        """
        # 使用列表推导式，对每个项目应用serializer的tag方法进行转换。
        return [self.serializer.tag(item) for item in value]

    # tag方法指向to_json方法，提供一个别名以支持一致的接口。
    tag = to_json



class TagBytes(JSONTag):
    """
    一个用于处理bytes类型数据的类，继承自JSONTag。
    它提供了检查数据类型以及在JSON和Python字节对象之间转换的功能。
    """
    __slots__ = ()  # 表示该类没有额外的属性，节省内存。
    key = " b"  # 标识符，用于在序列化格式中标识这种类型的数据。

    def check(self, value: t.Any) -> bool:
        """
        检查给定的值是否为bytes类型。

        参数:
        - value: t.Any 任何类型的值。

        返回:
        - bool 如果值是bytes类型，则返回True，否则返回False。
        """
        return isinstance(value, bytes)

    def to_json(self, value: t.Any) -> t.Any:
        """
        将Python的bytes类型值转换为JSON兼容的格式。
        具体来说，是将字节串编码为Base64格式的字符串，以便在JSON中表示。

        参数:
        - value: t.Any 任何类型的值，预期为bytes类型。

        返回:
        - t.Any Base64编码后的字符串。
        """
        return b64encode(value).decode("ascii")

    def to_python(self, value: t.Any) -> t.Any:
        """
        将JSON中的Base64格式字符串转换回Python的bytes类型。

        参数:
        - value: t.Any Base64格式的字符串，预期为JSON中的表示。

        返回:
        - t.Any 解码后的字节串。
        """
        return b64decode(value)


class TagMarkup(JSONTag):
    """
    一个表示标记语言（如HTML）的标签类，继承自JSONTag。
    这个类用于处理和转换包含标记语言的对象。
    """

    # 定义类的特殊属性，防止动态添加其他属性，以优化内存使用
    __slots__ = ()
    # 定义类的键属性，用于标识或索引，这里命名为" m"，可能用于特定的查找或解析场景
    key = " m"

    def check(self, value: t.Any) -> bool:
        """
        检查给定值是否具有__html__方法，以确定它是否可以被转换为HTML标记语言。

        参数:
            value (t.Any): 待检查的值。

        返回:
            bool: 如果值具有__html__方法且该方法可调用，则返回True，否则返回False。
        """
        return callable(getattr(value, "__html__", None))

    def to_json(self, value: t.Any) -> t.Any:
        """
        将具有__html__方法的对象转换为JSON格式。
        实际操作是调用对象的__html__方法，将其结果转换为字符串。

        参数:
            value (t.Any): 待转换的对象。

        返回:
            t.Any: 转换后的字符串，准备被进一步转换为JSON格式。
        """
        return str(value.__html__())

    def to_python(self, value: t.Any) -> t.Any:
        """
        将表示HTML标记语言的字符串安全地转换为Python中的Markup对象。
        这允许在Python环境中安全地处理和显示HTML内容。

        参数:
            value (t.Any): 待转换的表示HTML标记语言的字符串或其他形式的值。

        返回:
            t.Any: 转换后的Markup对象，用于在Python中安全地处理HTML内容。
        """
        return Markup(value)



class TagUUID(JSONTag):
    """
    一个继承自JSONTag的类，用于处理UUID类型的标签。
    这个类实现了检查UUID类型、将UUID转换为JSON格式、
    以及将JSON格式转换回UUID类型的功能。
    """
    __slots__ = ()  # 表示该类没有定义额外的属性。
    key = " u"  # 定义了该类的键值标识。

    def check(self, value: t.Any) -> bool:
        """
        检查给定的值是否为UUID类型。

        参数:
        - value: 待检查的值，可以是任意类型。

        返回:
        - bool: 如果给定的值是UUID类型，则返回True，否则返回False。
        """
        return isinstance(value, UUID)

    def to_json(self, value: t.Any) -> t.Any:
        """
        将UUID类型的值转换为JSON格式。

        参数:
        - value: UUID类型的值。

        返回:
        - t.Any: 返回UUID值的十六进制字符串表示。
        """
        return value.hex

    def to_python(self, value: t.Any) -> t.Any:
        """
        将JSON格式的值转换回UUID类型。

        参数:
        - value: JSON格式（字符串）的UUID值。

        返回:
        - t.Any: 返回从字符串转换得到的UUID对象。
        """
        return UUID(value)



class TagDateTime(JSONTag):
    """
    `TagDateTime` 类继承自 `JSONTag`，用于处理日期时间的转换。

    该类实现了将 Python 的 `datetime` 对象转换为 JSON 格式以及从 JSON 格式转换回 Python 的 `datetime` 对象的功能。
    """
    __slots__ = ()  # 表明该类没有额外的属性，节省内存。
    key = " d"  # 定义一个用于标识日期时间的键。

    def check(self, value: t.Any) -> bool:
        """
        检查给定的值是否为 `datetime` 类型。

        参数:
        - value: t.Any 类型，待检查的值。

        返回:
        - bool 类型，如果值是 `datetime` 类型则返回 True，否则返回 False。
        """
        return isinstance(value, datetime)

    def to_json(self, value: t.Any) -> t.Any:
        """
        将 Python 的 `datetime` 对象转换为 JSON 格式的日期时间字符串。

        参数:
        - value: t.Any 类型，待转换的 `datetime` 对象。

        返回:
        - t.Any 类型，符合 HTTP 日期时间格式的字符串。
        """
        return http_date(value)

    def to_python(self, value: t.Any) -> t.Any:
        """
        将 JSON 格式的日期时间字符串转换为 Python 的 `datetime` 对象。

        参数:
        - value: t.Any 类型，待转换的日期时间字符串。

        返回:
        - t.Any 类型，转换后的 `datetime` 对象。
        """
        return parse_date(value)


# TaggedJSONSerializer 类用于实现自定义 JSON 序列化和反序列化功能。主要功能如下：
# 初始化：在 __init__ 方法中，初始化 tags 字典和 order 列表，并注册默认标签。
# 注册标签：register 方法用于注册新的标签类，确保标签唯一性并按顺序存储。
# 标记值：tag 方法遍历已注册的标签，找到合适的标签对值进行处理。
# 取消标记：untag 方法检查字典是否只有一个键，并使用相应的标签进行反序列化。
# 扫描取消标记：_untag_scan 方法递归地处理嵌套的字典和列表，调用 untag 方法。
# 序列化：dumps 方法将值标记后转换为 JSON 字符串。
# 反序列化：loads 方法将 JSON 字符串解析为 Python 对象，并取消标记。
class TaggedJSONSerializer:
    __slots__ = ("tags", "order")

    default_tags = [
        TagDict,
        PassDict,
        TagTuple,
        PassList,
        TagBytes,
        TagMarkup,
        TagUUID,
        TagDateTime,
    ]

    def __init__(self) -> None:
        """
        初始化JSONTagManager类的实例。

        该方法初始化了两个属性：tags和order。
        tags是一个字典，用于存储标签名和对应的JSONTag实例。
        order是一个列表，用于维护标签的注册顺序。
        """
        # 初始化tags字典为空，用于存储标签名和JSONTag实例的映射
        self.tags: dict[str, JSONTag] = {}
        # 初始化order列表为空，用于维护标签的注册顺序
        self.order: list[JSONTag] = []

        # 遍历默认标签类，将它们注册到标签管理器中
        for cls in self.default_tags:
            # 调用register方法注册每个默认标签类
            self.register(cls)

    def register(
        self,
        tag_class: type[JSONTag],
        force: bool = False,
        index: int | None = None,
    ) -> None:
        """
        注册一个标签类到标签库中。

        此方法允许动态添加新的标签类型到处理系统中，确保标签可以被正确识别和处理。

        参数:
        - tag_class: 要注册的标签类，必须是JSONTag的子类。
        - force: 如果设为True，则即使标签已存在，也会覆盖注册。默认为False。
        - index: 指定标签在顺序列表中的位置。如果未提供，则标签会被添加到列表末尾。

        返回:
        无返回值。

        抛出:
        - KeyError: 如果标签已经注册且force参数为False时，抛出此异常。
        """
        # 创建标签实例
        tag = tag_class(self)
        # 获取标签的唯一键
        key = tag.key

        # 如果标签键存在
        if key:
            # 如果标签已经注册且force为False，抛出异常
            if not force and key in self.tags:
                raise KeyError(f"Tag '{key}' is already registered.")

            # 将标签添加到标签字典中
            self.tags[key] = tag

        # 如果未指定索引位置，将标签添加到顺序列表末尾
        if index is None:
            self.order.append(tag)
        else:
            # 否则，将标签插入到指定位置
            self.order.insert(index, tag)

    def tag(self, value: t.Any) -> t.Any:
        """
        根据预定义的顺序，应用第一个匹配的标签到给定值上。

        此方法遍历一个标签顺序（`self.order`），对于给定的值，它找到第一个
        可以应用的标签并返回应用标签后的值。如果没有任何标签可以应用，它将
        返回原始值。

        参数:
        - value: t.Any 类型，表示可以是任何类型的值，该值将被标签化。

        返回:
        - t.Any 类型，表示标签化后的值或者原始值，具体取决于是否找到了适用的标签。
        """
        # 遍历预定义的标签顺序
        for tag in self.order:
            # 检查当前标签是否适用于给定的值
            if tag.check(value):
                # 如果适用，应用标签并返回结果
                return tag.tag(value)

        # 如果没有标签适用，返回原始值
        return value

    def untag(self, value: dict[str, t.Any]) -> t.Any:
        """
        将给定的值根据标签转换为相应的Python对象。

        如果值包含多个键或没有匹配的标签，则原样返回。

        参数:
        - value: 一个包含单个键值对的字典，表示一个带标签的值。

        返回:
        - 转换后的Python对象，如果无法进行转换则返回原始值。
        """
        # 检查字典中是否只有一个键值对
        if len(value) != 1:
            # 如果不是，直接返回原始值
            return value

        # 获取字典中的唯一键
        key = next(iter(value))

        # 检查键是否在预定义的标签中
        if key not in self.tags:
            # 如果不在，直接返回原始值
            return value

        # 使用标签对应的转换方法，将值转换为相应的Python对象并返回
        return self.tags[key].to_python(value[key])

    def _untag_scan(self, value: t.Any) -> t.Any:
        """
        递归扫描并移除字典或列表中的标签。

        该函数主要用于处理嵌套的字典或列表，移除其中的标签。如果是字典，它会先对字典的值进行递归调用，
        然后对整个字典调用`untag`方法；如果是列表，它会对列表中的每个元素进行递归调用。

        参数:
            value: t.Any - 输入的值，可以是字典、列表或其他任何类型。

        返回:
            t.Any - 处理后的值，结构与输入值相同，但其中的标签已被移除。
        """
        # 如果输入值是字典
        if isinstance(value, dict):
            # 对字典中的每个键值对进行递归调用
            value = {k: self._untag_scan(v) for k, v in value.items()}
            # 对整个字典调用untag方法
            value = self.untag(value)
        # 如果输入值是列表
        elif isinstance(value, list):
            # 对列表中的每个元素进行递归调用
            value = [self._untag_scan(item) for item in value]

        # 返回处理后的值
        return value

    def dumps(self, value: t.Any) -> str:
        """
        将给定的值转换为JSON字符串。

        该方法首先对输入值进行处理，将其与一个特定的标签关联（通过`self.tag(value)`方法实现），
        然后使用`dumps`函数（假设这个函数是之前定义的，用于序列化对象到JSON字符串）进行序列化。
        在序列化过程中，指定分隔符为逗号和冒号，以控制JSON字符串的格式。

        参数:
        - value: t.Any类型，表示可以接受任何类型的值。这是将要被序列化成JSON字符串的值。

        返回值:
        - 返回一个字符串，表示序列化后的JSON字符串。
        """
        return dumps(self.tag(value), separators=(",", ":"))

    def loads(self, value: str) -> t.Any:
        """
        解析给定的字符串值并返回解析后的结果。

        本函数旨在通过对字符串进行解析来转换其表示形式，具体来说，它会使用`loads`函数对输入的字符串进行解析，
        然后通过`_untag_scan`方法进一步处理解析结果。这个过程可能涉及到去除标签或进行特定的格式转换。

        参数:
        - value (str): 需要解析的字符串。

        返回:
        - t.Any: 解析后的结果，可能属于任意数据类型。

        注意:
        - `loads`函数是Python内置的json模块中的一个函数，用于解析JSON格式的字符串。
        - `_untag_scan`是当前类中的一个私有方法，具体实现未在代码片段中给出，负责进一步处理`loads`的结果。
        """
        # 使用`loads`函数解析输入的字符串值，然后通过`_untag_scan`方法处理解析结果。
        return self._untag_scan(loads(value))
