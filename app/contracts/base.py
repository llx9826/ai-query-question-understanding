"""仅放跨模块技术契约；业务定义由所属模块维护。"""

from pydantic import BaseModel, ConfigDict


class DTO(BaseModel):
    """拒绝多余字段，避免模型偷偷添加 SQL、权限等未声明参数。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AppError(Exception):
    """可安全展示的错误；底层异常不得直接返回客户端。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
