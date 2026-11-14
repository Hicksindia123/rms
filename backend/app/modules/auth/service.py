import json

from sqlalchemy import text

from app.core.db import UnitOfWork
from app.core.permissions import EffectivePermissions, step_codes_for
from app.core.security import CurrentUser
from app.modules.auth.schemas import (
    DepartmentOut,
    MeResponse,
    PermissionOut,
    ProfileOut,
    RoleOut,
)


class AuthService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def get_me(self, user: CurrentUser, perms: EffectivePermissions) -> MeResponse:
        """Profile, roles, effective permissions and PERFORM step codes for the frontend."""
        with self._uow.transaction(user.id) as session:
            step_codes = step_codes_for(session, user, "PERFORM")
            # Record sign-in event into user_activity (P4-04 item 5)
            has_recent_signin = session.execute(
                text("""
                    select exists (
                        select 1 from public.user_activity
                        where user_id = :uid and activity_type = 'SIGN_IN'
                          and created_at > now() - interval '15 minutes'
                    )
                """),
                {"uid": user.id},
            ).scalar()
            if not has_recent_signin:
                session.execute(
                    text("""
                        insert into public.user_activity (
                            user_id, activity_type, details
                        ) values (
                            :uid, 'SIGN_IN', cast(:details as jsonb)
                        )
                    """),
                    {
                        "uid": user.id,
                        "details": json.dumps({"source": "get_me", "client": "web_app"}),
                    },
                )
        dept = user.department
        return MeResponse(
            profile=ProfileOut(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                employee_code=user.employee_code,
                phone=user.phone,
                is_super_admin=user.is_super_admin,
                department=DepartmentOut(id=dept.id, code=dept.code, name=dept.name)
                if dept
                else None,
                must_change_password=user.must_change_password,
            ),
            roles=[RoleOut(code=r.code, name=r.name) for r in user.roles],
            permissions=[
                PermissionOut(module_code=m, action=a, scope=s)
                for (m, a), s in sorted(perms.grants.items())
            ],
            step_codes=step_codes,
        )
