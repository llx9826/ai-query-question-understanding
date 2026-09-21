"""Server-owned identities and workspace authorization."""

import secrets

from pydantic import Field, SecretStr, TypeAdapter

from app.contracts.base import DTO, AppError


class Principal(DTO):
    user_id: str
    workspace_ids: tuple[str, ...]


class UserCredential(DTO):
    user_id: str = Field(min_length=1, max_length=128)
    api_token: SecretStr
    workspace_ids: tuple[str, ...] | None = None


class IdentityProvider:
    def __init__(
        self,
        default_workspace_id: str,
        users: tuple[UserCredential, ...],
    ) -> None:
        self.default_workspace_id = default_workspace_id
        self.users = users
        tokens = [user.api_token.get_secret_value() for user in self.users]
        if (
            not tokens
            or any(len(token) < 12 for token in tokens)
            or len(tokens) != len(set(tokens))
            or len({user.user_id for user in self.users}) != len(self.users)
        ):
            raise ValueError("用户配置需要唯一的user_id及至少12字符的独立token")

    def authenticate(self, token: str) -> Principal:
        matched = None
        for user in self.users:
            if secrets.compare_digest(token, user.api_token.get_secret_value()):
                matched = user
        if matched is None:
            raise AppError("UNAUTHORIZED", "需要有效的API Bearer Token。", 401)
        workspaces = matched.workspace_ids or (self.default_workspace_id,)
        return Principal(user_id=matched.user_id, workspace_ids=workspaces)

    def principal_for_user(self, user_id: str) -> Principal:
        user = next((item for item in self.users if item.user_id == user_id), None)
        if user is None:
            raise AppError("UNAUTHORIZED", "用户身份不存在。", 401)
        return Principal(
            user_id=user.user_id,
            workspace_ids=user.workspace_ids or (self.default_workspace_id,),
        )

    @staticmethod
    def require_workspace(principal: Principal, workspace_id: str) -> None:
        if workspace_id not in principal.workspace_ids:
            raise AppError("WORKSPACE_NOT_FOUND", "数据空间不存在或不可访问。", 404)


def load_identity_provider(settings) -> IdentityProvider:
    """Load credentials explicitly at the composition boundary."""
    if settings.api_users_path:
        users = TypeAdapter(tuple[UserCredential, ...]).validate_json(
            settings.api_users_path.read_text(encoding="utf-8")
        )
    else:
        users = (
            UserCredential(
                user_id="local-user",
                api_token=settings.api_token,
                workspace_ids=(settings.workspace_id,),
            ),
        )
    return IdentityProvider(settings.workspace_id, users)
