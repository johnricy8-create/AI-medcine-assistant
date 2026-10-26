"""演示级 ACL：用户、项目、可见 scope。"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ProjectRecord(BaseModel):
    project_id: str
    name: str = ""
    description: str = ""
    acl_scope: str


class UserRecord(BaseModel):
    user_id: str
    name: str = ""
    groups: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)


class AccessContext(BaseModel):
    user_id: str
    project_id: str
    allowed_scopes: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    project_allowed: bool = False
    user_known: bool = False

    def can_access(self, acl_scope: str) -> bool:
        return acl_scope in self.allowed_scopes


class AccessService:
    def __init__(self, users: list[UserRecord], projects: list[ProjectRecord]) -> None:
        self.users = {user.user_id: user for user in users}
        self.projects = {project.project_id: project for project in projects}

    @classmethod
    def from_files(cls, users_path: Path, projects_path: Path) -> "AccessService":
        users_data = yaml.safe_load(users_path.read_text(encoding="utf-8")) or {}
        projects_data = (
            yaml.safe_load(projects_path.read_text(encoding="utf-8")) or {}
        )
        users = [UserRecord.model_validate(row) for row in users_data.get("users", [])]
        projects = [
            ProjectRecord.model_validate(row)
            for row in projects_data.get("projects", [])
        ]
        return cls(users, projects)

    def context(self, user_id: str, project_id: str) -> AccessContext:
        user = self.users.get(user_id)
        project = self.projects.get(project_id)
        if user is None:
            return AccessContext(
                user_id=user_id,
                project_id=project_id,
                allowed_scopes=["public"],
                project_ids=[],
                project_allowed=False,
                user_known=False,
            )
        project_allowed = bool(
            project and project.project_id in user.groups and project.acl_scope in user.allowed_scopes
        )
        allowed = list(dict.fromkeys(user.allowed_scopes or ["public"]))
        if "public" not in allowed:
            allowed.insert(0, "public")
        return AccessContext(
            user_id=user_id,
            project_id=project_id,
            allowed_scopes=allowed,
            project_ids=list(user.groups),
            project_allowed=project_allowed,
            user_known=True,
        )

    def project_ids(self) -> list[str]:
        return list(self.projects.keys())
