"""媒体存储抽象。

数据库只保存对象键（例如 `uploads/m_xxx.jpg`），不保存完整地址。
本地开发把对象键映射到 `MEDIA_ROOT` 下的文件，通过 `/media/<key>` 访问；
迁移到云时新增一个后端实现（对象存储接口兼容 S3 协议即可），
把 `MEDIA_BACKEND` 改掉，业务代码与数据库都不需要改动。
"""

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Final

from app.core.config import settings

LOCAL_URL_PREFIX: Final = "/media/"


class StorageBackend(ABC):
    """对象存储后端接口。

    新增云厂商时只需要实现这些方法，媒体服务与序列化层不感知具体实现。
    """

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        """写入对象。对象键由调用方生成，重复写入覆盖原对象。"""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """读取对象内容。

        知识库重新切片时需要把原始文件重新读出来；
        对象不存在时抛出 FileNotFoundError，由业务层决定如何提示。
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除对象。对象不存在时视为成功，便于重试。"""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """判断对象是否存在，用于迁移后的完整性校验。"""

    @abstractmethod
    def url(self, key: str) -> str:
        """生成可访问地址。本地返回相对路径，云端返回完整地址。"""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """删除某个对象键前缀下的全部对象。

        知识库文档可以把多张图片放在同一个目录下，删除文档时需要按目录
        整体清理；前缀下没有对象时视为成功，便于重复调用和失败重试。
        """


class LocalStorage(StorageBackend):
    """本地磁盘实现。

    目录结构与对象键一一对应，日后可按对象键批量上传到对象存储，
    不会出现“数据库里存的是完整网址、迁移后无法改写”的问题。
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        # 规范化后必须仍位于根目录内，防止对象键中出现 .. 造成目录穿越。
        path = (self._root / key.lstrip("/")).resolve()
        if path != self._root and self._root not in path.parents:
            raise ValueError("非法的对象键")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def url(self, key: str) -> str:
        return f"{LOCAL_URL_PREFIX}{key.lstrip('/')}"

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix)
        # 只允许删除目录，避免误传单个对象键时把文件当成目录处理。
        if path.is_dir():
            shutil.rmtree(path)


def _build_storage() -> StorageBackend:
    if settings.media_backend == "local":
        return LocalStorage(Path(settings.media_root))
    # 迁移到云时在这里返回对象存储实现，其余代码不变。
    raise RuntimeError(
        f"MEDIA_BACKEND={settings.media_backend} 尚未实现，当前仅支持 local"
    )


_storage: StorageBackend = _build_storage()


def get_storage() -> StorageBackend:
    return _storage


def object_url(value: str | None) -> str | None:
    """把数据库中的值转换成可访问地址。

    兼容三类历史数据：
    1. 完整外链（http/https/data）原样返回；
    2. 旧版本写入的 `/media/<key>` 先还原为对象键，再交给当前后端生成地址；
    3. 其余值按对象键处理。
    这样从本地磁盘切换到对象存储后，旧记录也能正确指向新地址。
    """

    if not value:
        return None
    if value.startswith(("http://", "https://", "data:")):
        return value
    key = value[len(LOCAL_URL_PREFIX) :] if value.startswith(LOCAL_URL_PREFIX) else value
    return _storage.url(key)
