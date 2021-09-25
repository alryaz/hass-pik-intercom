__all__ = (
    "PikIntercomAPI",
    "PikIntercomAccount",
    "PikIntercomDevice",
    "PikIntercomApartment",
    "PikIntercomCallSession",
    "PikIntercomException",
    "VIDEO_QUALITY_TYPES",
    "DEFAULT_CLIENT_VERSION",
    "DEFAULT_CLIENT_APP",
    "DEFAULT_CLIENT_OS",
    "DEFAULT_USER_AGENT",
)

import asyncio
import json
import logging
import random
import string
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar, Dict, Final, Mapping, Optional, Tuple

import aiohttp
import attr
from multidict import CIMultiDict, CIMultiDictProxy, MultiDict

_LOGGER = logging.getLogger(__name__)

DEFAULT_USER_AGENT: Final = "okhttp/4.9.0"
DEFAULT_CLIENT_APP: Final = "alfred"
DEFAULT_CLIENT_VERSION: Final = "2021.6.1"
DEFAULT_CLIENT_OS: Final = "Android"


class PikIntercomException(Exception):
    pass


class PikIntercomAPI:
    BASE_PIK_URL: ClassVar[str] = "https://intercom.pik-comfort.ru"

    def __init__(
        self,
        username: str,
        password: str,
        device_id: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        client_app: str = DEFAULT_CLIENT_APP,
        client_version: str = DEFAULT_CLIENT_VERSION,
        client_os: str = DEFAULT_CLIENT_OS,
    ) -> None:
        self._username = username
        self._password = password

        if device_id is None:
            device_id = "".join(
                random.choices(
                    string.ascii_uppercase + string.digits,
                    k=16,
                )
            )

        self._session = aiohttp.ClientSession(
            headers={
                aiohttp.hdrs.USER_AGENT: user_agent,
                "api-version": "2",
                "device-client-app": client_app,
                "device-client-version": client_version,
                "device-client-os": client_os,
                "device-client-uid": device_id,
            }
        )

        self._authorization: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._request_counter: int = 0

        self._account: Optional[PikIntercomAccount] = None
        self._apartments: Dict[int, PikIntercomApartment] = {}
        self._devices: Dict[int, PikIntercomDevice] = {}
        self._call_sessions: Dict[int, PikIntercomCallSession] = {}

        # @TODO: add other properties

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._session.__aexit__(*args)

    @property
    def username(self) -> str:
        return self._username

    @property
    def device_id(self) -> str:
        return self._session.headers["device-client-uid"]

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._session

    @property
    def account(self) -> Optional["PikIntercomAccount"]:
        return self._account

    @property
    def is_authenticated(self) -> bool:
        return self._authorization is not None

    @property
    def apartments(self) -> Mapping[int, "PikIntercomApartment"]:
        return MappingProxyType(self._apartments)

    @property
    def devices(self) -> Mapping[int, "PikIntercomDevice"]:
        return MappingProxyType(self._devices)

    async def async_close(self) -> None:
        await self._session.close()

    @property
    def _masked_username(self) -> str:
        return "..." + self._username[-3:]

    async def _async_req(
        self,
        method: str,
        sub_url: str,
        headers: Optional[CIMultiDict] = None,
        authenticated: bool = False,
        title: str = "request",
        **kwargs: Any,
    ) -> Tuple[Any, CIMultiDictProxy[str], int]:
        if headers is None:
            headers = CIMultiDict()

        if authenticated:
            if not self.is_authenticated:
                raise PikIntercomException("API not authenticated")

            headers[aiohttp.hdrs.AUTHORIZATION] = self._authorization

        url = self.BASE_PIK_URL + sub_url

        self._request_counter += 1
        request_counter = self._request_counter

        _LOGGER.debug(
            f"[{request_counter}] Performing {title} with "
            f'username "{self._masked_username}", url: {url}'
        )

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                **kwargs,
            ) as request:
                if request.status != 200:
                    _LOGGER.error(
                        f"[{request_counter}] Could not perform {title}, "
                        f"status {request.status}, body: {await request.text()}"
                    )
                    raise PikIntercomException(
                        f"Could not perform {title} (status code {request.status})"
                    )

                resp_data = await request.json()

        except json.JSONDecodeError:
            _LOGGER.error(
                f"[{request_counter}] Could not perform {title}, "
                f"invalid JSON body: {await request.text()}"
            )
            raise PikIntercomException(
                f"Could not perform {title} (body decoding failed)"
            )

        except asyncio.TimeoutError:
            _LOGGER.error(
                f"[{request_counter}] Could not perform {title}, "
                f"waited for {self._session.timeout.total} seconds"
            )
            raise PikIntercomException(f"Could not perform {title} (timed out)")

        except aiohttp.ClientError as e:
            _LOGGER.error(
                f"[{request_counter}] Could not perform {title}, " f"client error: {e}"
            )
            raise PikIntercomException(f"Could not perform {title} (client error)")

        else:
            if isinstance(resp_data, dict) and resp_data.get("error"):
                _LOGGER.error(
                    f"Could not perform {title}, "
                    f"code: {resp_data.get('code', 'unknown')}, "
                    f"description: {resp_data.get('description', 'none provided')}"
                )
                raise PikIntercomException(
                    f"Could not perform {title} ({resp_data.get('code', 'unknown')})"
                )

            return resp_data, request.headers, request_counter

    async def _async_get(
        self,
        sub_url: str,
        headers: Optional[CIMultiDict] = None,
        authenticated: bool = False,
        title: str = "request",
        **kwargs: Any,
    ) -> Tuple[Any, CIMultiDictProxy[str], int]:
        return await self._async_req(
            aiohttp.hdrs.METH_GET, sub_url, headers, authenticated, title, **kwargs
        )

    async def _async_post(
        self,
        sub_url: str,
        headers: Optional[CIMultiDict] = None,
        authenticated: bool = False,
        title: str = "request",
        **kwargs: Any,
    ) -> Tuple[Any, CIMultiDictProxy[str], int]:
        return await self._async_req(
            aiohttp.hdrs.METH_POST, sub_url, headers, authenticated, title, **kwargs
        )

    async def async_authenticate(self) -> None:
        resp_data, headers, request_counter = await self._async_post(
            "/api/customers/sign_in",
            data={
                "account[phone]": self._username,
                "account[password]": self._password,
                "customer_device[uid]": self.device_id,
            },
            title="authentication",
        )

        authorization = headers.get("Authorization")
        if not authorization:
            _LOGGER.error(
                f"[{request_counter}] Could not perform authentication, "
                f"({aiohttp.hdrs.AUTHORIZATION} header not found)"
            )
            raise PikIntercomException(
                f"Could not perform authentication "
                f"({aiohttp.hdrs.AUTHORIZATION} header not found)"
            )

        self._authorization = authorization

        account = self._account
        account_data = resp_data["account"]

        if account is None:
            account = PikIntercomAccount(
                api=self,
                id=account_data["id"],
                phone=account_data["phone"],
                email=account_data.get("email"),
                number=account_data.get("number"),
                apartment_id=account_data.get("apartment_id"),
                first_name=account_data.get("first_name"),
                last_name=account_data.get("last_name"),
                middle_name=account_data.get("middle_name"),
            )
            self._account = account
        else:
            account.api = self
            account.id = account_data["id"]
            account.phone = account_data["phone"]
            account.email = account_data.get("email")
            account.number = account_data.get("number")
            account.apartment_id = account_data.get("apartment_id")
            account.first_name = account_data.get("first_name")
            account.last_name = account_data.get("last_name")
            account.middle_name = account_data.get("middle_name")

        _LOGGER.debug(f"[{request_counter}] Authentication successful")

    async def async_update_properties(self):
        resp_data, headers, request_counter = await self._async_get(
            "/api/customers/properties",
            title="properties fetching",
            authenticated=True,
        )

        for apartment_data in resp_data.get("apartments", []):
            apartment_id = apartment_data["id"]
            try:
                apartment = self._apartments[apartment_id]
            except KeyError:
                self._apartments[apartment_id] = PikIntercomApartment(
                    api=self,
                    id=apartment_id,
                    scheme_id=apartment_data["scheme_id"],
                    number=apartment_data["number"],
                    section=apartment_data["section"],
                    building_id=apartment_data["building_id"],
                    district_id=apartment_data["district_id"],
                    account_number=apartment_data.get("account_number"),
                )
            else:
                apartment.api = self
                apartment.id = apartment_id
                apartment.scheme_id = apartment_data["scheme_id"]
                apartment.number = apartment_data["number"]
                apartment.section = apartment_data["section"]
                apartment.building_id = apartment_data["building_id"]
                apartment.district_id = apartment_data["district_id"]
                apartment.account_number = apartment_data.get("account_number")

        # @TODO: add other properties

        _LOGGER.debug(f"[{request_counter}] Properties fetching successful {resp_data}")

    async def async_update_property_intercoms(self, property_id: int) -> None:
        sub_url = f"/api/customers/properties/{property_id}/intercoms"
        intercoms = self._devices
        page_number = 0

        while True:
            page_number += 1

            resp_data, headers, request_counter = await self._async_get(
                sub_url,
                title="property intercoms fetching",
                authenticated=True,
                params={"page": page_number},
            )

            if not resp_data:
                _LOGGER.debug(
                    f"[{request_counter}] Page {page_number} does not contain data"
                )
                break

            for intercom_data in resp_data:
                intercom_id = intercom_data["id"]

                video_data = intercom_data.get("video")
                if video_data is not None:
                    video_data = MultiDict(
                        [(v["quality"], v["source"]) for v in video_data]
                    )

                try:
                    intercom = intercoms[intercom_id]

                except KeyError:
                    intercoms[intercom_id] = PikIntercomDevice(
                        api=self,
                        property_id=property_id,
                        id=intercom_data["id"],
                        scheme_id=intercom_data["scheme_id"],
                        building_id=intercom_data["building_id"],
                        kind=intercom_data["kind"],
                        device_category=intercom_data["device_category"],
                        mode=intercom_data["mode"],
                        name=intercom_data["name"],
                        human_name=intercom_data["human_name"],
                        renamed_name=intercom_data["renamed_name"],
                        checkpoint_relay_index=intercom_data.get(
                            "checkpoint_relay_index"
                        ),
                        relays=intercom_data["relays"],
                        entrance=intercom_data.get("entrance"),
                        sip_account=intercom_data.get("sip_account"),
                        can_address=intercom_data.get("can_address"),
                        face_detection=intercom_data.get("face_detection"),
                        video=video_data,
                        photo_url=intercom_data.get("photo_url") or None,
                    )

                else:
                    intercom.api = self
                    intercom.property_id = property_id
                    intercom.id = intercom_data["id"]
                    intercom.scheme_id = intercom_data["scheme_id"]
                    intercom.building_id = intercom_data["building_id"]
                    intercom.kind = intercom_data["kind"]
                    intercom.device_category = intercom_data["device_category"]
                    intercom.mode = intercom_data["mode"]
                    intercom.name = intercom_data["name"]
                    intercom.human_name = intercom_data["human_name"]
                    intercom.renamed_name = intercom_data["renamed_name"]
                    intercom.checkpoint_relay_index = intercom_data.get(
                        "checkpoint_relay_index"
                    )
                    intercom.relays = intercom_data["relays"]
                    intercom.entrance = intercom_data.get("entrance")
                    intercom.sip_account = intercom_data.get("sip_account")
                    intercom.can_address = intercom_data.get("can_address")
                    intercom.face_detection = intercom_data.get("face_detection")
                    intercom.video = video_data
                    intercom.photo_url = intercom_data.get("photo_url") or None

            _LOGGER.debug(f"[{request_counter}] Property intercoms fetching successful")

    async def async_intercom_unlock(self, intercom_id: int, mode: str) -> None:
        resp_data, headers, request_counter = await self._async_post(
            f"/api/customers/intercoms/{intercom_id}/unlock",
            data={"id": intercom_id, "door": mode},
            title="intercom unlocking",
            authenticated=True,
        )

        if resp_data.get("request") is not True:
            _LOGGER.error(
                f"[{request_counter}] Intercom unlocking failed, waited "
                f"for {self._session.timeout.total} seconds"
            )
            raise PikIntercomException("Could not unlock intercom (result is False)")

        _LOGGER.debug(f"[{request_counter}] Intercom unlocking successful")

    @property
    def last_call_session(self) -> Optional["PikIntercomCallSession"]:
        try:
            return next(
                iter(
                    sorted(
                        self._call_sessions.values(),
                        key=lambda x: x.updated_at,
                        reverse=True,
                    )
                )
            )
        except StopIteration:
            return None

    async def async_update_call_sessions(self, max_pages: Optional[int] = 10) -> None:
        sub_url = "/api/call_sessions"
        call_sessions = self._call_sessions
        page_number = 0
        last_call_session = self.last_call_session
        requires_further_updates = True

        while requires_further_updates and (
            max_pages is None or page_number < max_pages
        ):
            page_number += 1

            resp_data, headers, request_counter = await self._async_get(
                sub_url,
                title=f"call sessions fetching (page {page_number})",
                authenticated=True,
                params={"page": page_number},
            )

            call_sessions_list = resp_data.get("call_sessions", ())

            if not call_sessions_list:
                _LOGGER.debug(
                    f"[{request_counter}] Page {page_number} does not contain data"
                )
                break

            for call_session_data in call_sessions_list:
                session_data = call_session_data["call_session"]
                call_session_id = session_data["id"]

                updated_at = datetime.fromisoformat(session_data["updated_at"])

                if (
                    requires_further_updates
                    and last_call_session
                    and last_call_session.updated_at > updated_at
                ):
                    requires_further_updates = False

                created_at = datetime.fromisoformat(session_data["created_at"])

                finished_at = (
                    datetime.fromisoformat(session_data["finished_at"])
                    if session_data.get("finished_at")
                    else None
                )

                notified_at = (
                    datetime.fromisoformat(session_data["notified_at"])
                    if session_data.get("notified_at")
                    else None
                )

                answered_customer_device_ids = tuple(
                    call_session_data.get("answered_customer_device_ids") or ()
                )

                try:
                    call_session = call_sessions[call_session_id]

                except KeyError:
                    call_sessions[call_session_id] = PikIntercomCallSession(
                        api=self,
                        id=session_data["id"],
                        property_id=session_data["property_id"],
                        intercom_id=session_data["intercom_id"],
                        call_number=session_data["call_number"],
                        notified_at=notified_at,
                        updated_at=updated_at,
                        created_at=created_at,
                        finished_at=finished_at,
                        hangup=call_session_data["hangup"],
                        intercom_name=call_session_data["intercom_name"],
                        photo_url=call_session_data.get("photo_url") or None,
                        answered_customer_device_ids=answered_customer_device_ids,
                    )

                else:
                    call_session.api = self
                    call_session.id = session_data["id"]
                    call_session.property_id = session_data["property_id"]
                    call_session.intercom_id = session_data["intercom_id"]
                    call_session.call_number = session_data["call_number"]
                    call_session.notified_at = notified_at
                    call_session.updated_at = updated_at
                    call_session.created_at = created_at
                    call_session.finished_at = finished_at
                    call_session.hangup = call_session_data["hangup"]
                    call_session.intercom_name = call_session_data["intercom_name"]
                    call_session.photo_url = call_session_data.get("photo_url") or None
                    call_session.answered_customer_device_ids = (
                        answered_customer_device_ids
                    )

            _LOGGER.debug(f"[{request_counter}] Call sessions fetching successful")

        if not requires_further_updates:
            _LOGGER.debug(f"[{self._request_counter}] Stopped due to list truncation")


@attr.s(slots=True)
class _BasePikIntercomObject:
    api: PikIntercomAPI = attr.ib()


@attr.s(slots=True)
class PikIntercomAccount(_BasePikIntercomObject):
    id: int = attr.ib()
    phone: str = attr.ib()
    email: Optional[str] = attr.ib(default=None)
    apartment_id: Optional[int] = attr.ib(default=None)
    number: Optional[str] = attr.ib(default=None)
    first_name: Optional[str] = attr.ib(default=None)
    last_name: Optional[str] = attr.ib(default=None)
    middle_name: Optional[str] = attr.ib(default=None)


@attr.s(slots=True)
class PikIntercomApartment(_BasePikIntercomObject):
    id: int = attr.ib()
    scheme_id: int = attr.ib()
    number: str = attr.ib()
    section: int = attr.ib()
    building_id: int = attr.ib()
    district_id: int = attr.ib()
    account_number: Optional[str] = attr.ib(default=None)

    async def async_update_intercoms(self) -> None:
        await self.api.async_update_property_intercoms(self.id)

    @property
    def intercoms(self) -> Mapping[int, "PikIntercomDevice"]:
        return {
            intercom_id: intercom_device
            for intercom_id, intercom_device in self.api.devices.items()
            if intercom_device.property_id == self.id
        }  # @TODO: make into api-bound mapping


VIDEO_QUALITY_TYPES: Final = ("high", "medium", "low")


@attr.s(slots=True)
class PikIntercomDevice(_BasePikIntercomObject):
    id: int = attr.ib()
    scheme_id: int = attr.ib()
    building_id: int = attr.ib()
    kind: str = attr.ib()
    device_category: str = attr.ib()
    mode: str = attr.ib()
    name: str = attr.ib()
    human_name: str = attr.ib()
    renamed_name: str = attr.ib()
    relays: Dict[str, str] = attr.ib()
    checkpoint_relay_index: Optional[int] = attr.ib(default=None)
    entrance: Optional[int] = attr.ib(default=None)
    sip_account: Optional[Any] = attr.ib(default=None)
    can_address: Optional[Any] = attr.ib(default=None)
    face_detection: Optional[bool] = attr.ib(default=None)
    video: Optional[MultiDict[str]] = attr.ib(default=None)
    photo_url: Optional[str] = attr.ib(default=None)
    property_id: Optional[int] = attr.ib(default=None)  # Non-standard attribute

    @property
    def has_camera(self) -> bool:
        return bool(self.video or self.photo_url)

    @property
    def stream_url(self) -> Optional[str]:
        """Return URL for video stream"""
        video_streams = self.video
        if not video_streams:
            return None

        for quality in VIDEO_QUALITY_TYPES:
            video_stream_url = video_streams.get(quality)
            if video_stream_url:
                return video_stream_url

        return next(iter(video_streams.values()))

    async def async_unlock(self) -> None:
        """Unlock intercom"""
        await self.api.async_intercom_unlock(self.id, self.mode)

    async def async_get_snapshot(self) -> bytes:
        photo_url = self.photo_url
        if not photo_url:
            # @TODO: add diversion to get snapshot off RTSP
            raise PikIntercomException("Photo URL is empty")

        async with self.api.session.get(photo_url) as request:
            if request.status != 200:
                raise PikIntercomException(
                    f"Photo could not be retrieved ({request.status})"
                )

            return await request.read()


@attr.s(slots=True)
class PikIntercomCallSession(_BasePikIntercomObject):
    id: int = attr.ib()
    property_id: int = attr.ib()
    intercom_id: int = attr.ib()
    call_number: str = attr.ib()
    intercom_name: str = attr.ib()
    photo_url: Optional[str] = attr.ib()
    answered_customer_device_ids: Tuple[str] = attr.ib()
    hangup: bool = attr.ib()
    created_at: datetime = attr.ib()
    updated_at: datetime = attr.ib()
    notified_at: Optional[datetime] = attr.ib(default=None)
    finished_at: Optional[datetime] = attr.ib(default=None)

    @property
    def full_photo_url(self) -> Optional[str]:
        photo_url = self.photo_url
        if photo_url is None:
            return None

        return self.api.BASE_PIK_URL + photo_url
