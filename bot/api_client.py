import httpx
from bot.config import settings


class ApiClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._client = httpx.AsyncClient(base_url=settings.api_base_url, timeout=10.0)

    async def _login(self) -> None:
        resp = await self._client.post(
            "/api/v1/auth/login",
            json={"email": settings.api_email, "password": settings.api_password},
        )
        resp.raise_for_status()
        self._token = resp.json()["token"]

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, path: str, **kwargs) -> dict | list:
        if not self._token:
            await self._login()
        resp = await self._client.get(path, headers=self._auth_headers(), **kwargs)
        if resp.status_code == 401:
            await self._login()
            resp = await self._client.get(path, headers=self._auth_headers(), **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, **kwargs) -> dict | list | None:
        if not self._token:
            await self._login()
        resp = await self._client.post(path, headers=self._auth_headers(), **kwargs)
        if resp.status_code == 401:
            await self._login()
            resp = await self._client.post(path, headers=self._auth_headers(), **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    async def get_groups(self) -> list:
        return await self._get("/api/v1/groups")

    async def get_cabinet(self, group_id: int) -> dict:
        return await self._get(f"/api/v1/groups/{group_id}/cabinet")

    async def get_plan(self, group_id: int, date: str) -> dict | None:
        try:
            return await self._get(f"/api/v1/groups/{group_id}/plans/date/{date}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_group_members(self, group_id: int) -> list:
        return await self._get(f"/api/v1/groups/{group_id}/members")

    async def record_attendance(
        self, group_id: int, meeting_date: str, entries: list[dict]
    ) -> None:
        await self._post(
            "/api/v1/attendance",
            json={
                "homeGroupId": group_id,
                "meetingDate": meeting_date,
                "entries": entries,
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()


api_client = ApiClient()
