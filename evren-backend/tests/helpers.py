from __future__ import annotations

from app.models import User
from app.models.enums import UserRole
from httpx import AsyncClient
from sqlalchemy import update

TEST_PASSWORD = "Passw0rd!123"


async def create_user(
    app, email: str, password: str = TEST_PASSWORD, role: UserRole = UserRole.USER
) -> User:
    from app.security import hash_password

    async with app.state.database.session() as session:
        user = User(email=email, password_hash=hash_password(password), role=role)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def upgrade_to_admin(app, email: str) -> None:
    async with app.state.database.session() as session:
        await session.execute(update(User).where(User.email == email).values(role=UserRole.ADMIN))
        await session.commit()


async def register_and_login(
    client: AsyncClient, email: str, password: str = TEST_PASSWORD
) -> dict[str, str]:
    response = await client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return await login_headers(client, email, password)


async def login_headers(
    client: AsyncClient, email: str, password: str = TEST_PASSWORD
) -> dict[str, str]:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
