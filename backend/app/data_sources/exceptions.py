"""外部数据源适配器异常。"""


class DataSourceError(Exception):
    """数据源业务异常。"""

    def __init__(self, message: str, http_status: int = 400):
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class UnsupportedConnectorError(DataSourceError):
    def __init__(self, dialect: str, hint: str = ""):
        msg = f"不支持的连接器: {dialect or 'unknown'}"
        if hint:
            msg = f"{msg}；{hint}"
        super().__init__(msg, http_status=422)


class DriverMissingError(DataSourceError):
    def __init__(self, dialect: str, driver: str, package: str):
        super().__init__(
            f"连接器 {dialect} 需要驱动 {driver}，请安装依赖包 {package} 后重试",
            http_status=422,
        )


class DataSourceSecurityError(DataSourceError):
    def __init__(self, message: str):
        super().__init__(message, http_status=403)


class DataSourceQueryError(DataSourceError):
    def __init__(self, message: str = "外部数据库查询失败", http_status: int = 502):
        super().__init__(message, http_status=http_status)
