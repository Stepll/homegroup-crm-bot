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

    async def _delete(self, path: str) -> None:
        if not self._token:
            await self._login()
        resp = await self._client.delete(path, headers=self._auth_headers())
        if resp.status_code == 401:
            await self._login()
            resp = await self._client.delete(path, headers=self._auth_headers())
        resp.raise_for_status()

    async def _put(self, path: str, **kwargs) -> dict | list | None:
        if not self._token:
            await self._login()
        resp = await self._client.put(path, headers=self._auth_headers(), **kwargs)
        if resp.status_code == 401:
            await self._login()
            resp = await self._client.put(path, headers=self._auth_headers(), **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    async def get_groups(self) -> list:
        return await self._get("/api/v1/groups")

    async def get_cabinet(self, group_id: int) -> dict:
        return await self._get(f"/api/v1/groups/{group_id}/cabinet")

    async def save_plan(self, group_id: int, payload: dict) -> dict:
        return await self._post(f"/api/v1/groups/{group_id}/plans", json=payload)

    async def get_plan(self, group_id: int, date: str) -> dict | None:
        try:
            return await self._get(f"/api/v1/groups/{group_id}/plans/date/{date}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_group_stats(self, group_id: int, period: str = "3m") -> dict:
        return await self._get(f"/api/v1/groups/{group_id}/stats", params={"period": period})

    async def get_people(self) -> list:
        return await self._get("/api/v1/people")

    async def get_admins(self) -> list:
        return await self._get("/api/v1/admins")

    async def get_admin(self, admin_id: int) -> dict:
        return await self._get(f"/api/v1/admins/{admin_id}")

    async def update_profile(self, admin_id: int, payload: dict) -> None:
        await self._put(f"/api/v1/admins/{admin_id}/profile", json=payload)

    async def get_person(self, person_id: int) -> dict:
        return await self._get(f"/api/v1/people/{person_id}")

    async def update_person(self, person_id: int, payload: dict) -> None:
        await self._put(f"/api/v1/people/{person_id}", json=payload)

    async def get_group(self, group_id: int) -> dict:
        return await self._get(f"/api/v1/groups/{group_id}")

    async def update_group(self, group_id: int, payload: dict) -> None:
        await self._put(f"/api/v1/groups/{group_id}", json=payload)

    async def skip_meeting(self, group_id: int) -> dict:
        return await self._put(f"/api/v1/groups/{group_id}/skip-meeting")

    async def set_next_meeting(self, group_id: int, date: str) -> None:
        await self._put(f"/api/v1/groups/{group_id}/next-meeting", json={"date": date})

    async def get_group_events(self, group_id: int) -> list:
        return await self._get(f"/api/v1/groups/{group_id}/events")

    async def create_event(self, group_id: int, data: dict) -> dict:
        return await self._post(f"/api/v1/groups/{group_id}/events", json=data)

    async def update_event(self, group_id: int, event_id: int, data: dict) -> dict:
        return await self._put(f"/api/v1/groups/{group_id}/events/{event_id}", json=data)

    async def delete_event(self, group_id: int, event_id: int) -> None:
        await self._delete(f"/api/v1/groups/{group_id}/events/{event_id}")

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

    async def save_attendance_meta(
        self, group_id: int, meeting_date: str, guest_count: int
    ) -> None:
        await self._post(
            "/api/v1/attendance/meta",
            json={"homeGroupId": group_id, "meetingDate": meeting_date, "guestCount": guest_count},
        )

    async def get_plan_templates(self) -> list:
        return await self._get("/api/v1/plan-templates")

    async def delete_plan(self, group_id: int, date: str) -> None:
        await self._delete(f"/api/v1/groups/{group_id}/plans/date/{date}")

    async def send_plan_to_telegram(self, group_id: int, date: str) -> None:
        await self._post(f"/api/v1/groups/{group_id}/plans/date/{date}/send-to-telegram")

    async def aclose(self) -> None:
        await self._client.aclose()


api_client = ApiClient()
