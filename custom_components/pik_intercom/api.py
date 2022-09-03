__all__ = (
    "PikIntercomAPI",
    "PikAccount",
    "PikPropertyDevice",
    "PikCallSession",
    "PikIntercomException",
    "PikIotRelaySettings",
    "PikIotRelay",
    "PikProperty",
    "PikIotIntercom",
    "PikObjectWithVideo",
    "PikObjectWithSnapshot",
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
from abc import abstractmethod, ABC
from datetime import date, datetime
from types import MappingProxyType
from typing import (
    Any,
    ClassVar,
    Dict,
    Final,
    Mapping,
    Optional,
    Tuple,
    List,
    NamedTuple,
)

import aiohttp
import attr
from multidict import CIMultiDict, CIMultiDictProxy, MultiDict

_LOGGER = logging.getLogger(__name__)

DEFAULT_USER_AGENT: Final = "okhttp/4.9.0"
DEFAULT_CLIENT_APP: Final = "alfred"
DEFAULT_CLIENT_VERSION: Final = "2021.10.2"
DEFAULT_CLIENT_OS: Final = "Android"

# These are arbitrary, and never seen before
VIDEO_QUALITY_TYPES: Final = ("high", "medium", "low")


class PikIntercomException(Exception):
    """Base class for exceptions"""


class PikIntercomAPI:
    BASE_PIK_URL: ClassVar[str] = "https://intercom.pik-comfort.ru"
    BASE_RUBETEK_URL: ClassVar[str] = "https://iot.rubetek.com"

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

        if not device_id:
            device_id = "".join(
                random.choices(
                    string.ascii_uppercase + string.digits,
                    k=16,
                )
            )

        self._session = aiohttp.ClientSession(
            headers={
                aiohttp.hdrs.USER_AGENT: user_agent,
                "API-VERSION": "2",
                "device-client-app": client_app,
                "device-client-version": client_version,
                "device-client-os": client_os,
                "device-client-uid": device_id,
            }
        )

        self._authorization: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._request_counter: int = 0

        self._account: Optional[PikAccount] = None
        self._properties: Dict[int, PikProperty] = {}
        self._devices: Dict[int, PikPropertyDevice] = {}
        self._iot_intercoms: Dict[int, PikIotIntercom] = {}
        self._iot_relays: Dict[int, PikIotRelay] = {}
        self._call_sessions: Dict[int, PikCallSession] = {}

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
    def account(self) -> Optional["PikAccount"]:
        return self._account

    @property
    def is_authenticated(self) -> bool:
        return self._authorization is not None

    @property
    def properties(self) -> Mapping[int, "PikProperty"]:
        return MappingProxyType(self._properties)

    @property
    def devices(self) -> Mapping[int, "PikPropertyDevice"]:
        return MappingProxyType(self._devices)

    @property
    def iot_intercoms(self) -> Mapping[int, "PikIotIntercom"]:
        return MappingProxyType(self._iot_intercoms)

    @property
    def iot_relays(self) -> Mapping[int, "PikIotRelay"]:
        return MappingProxyType(self._iot_relays)

    async def async_close(self) -> None:
        await self._session.close()

    @property
    def _masked_username(self) -> str:
        return "..." + self._username[-3:]

    def increment_request_counter(self) -> int:
        request_counter = self._request_counter + 1
        self._request_counter = request_counter
        return request_counter

    async def _async_req(
        self,
        method: str,
        sub_url: str,
        headers: Optional[CIMultiDict] = None,
        authenticated: bool = False,
        title: str = "request",
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Any, CIMultiDictProxy[str], int]:
        if headers is None:
            headers = CIMultiDict()

        if authenticated:
            if not self.is_authenticated:
                raise PikIntercomException("API not authenticated")

            headers[aiohttp.hdrs.AUTHORIZATION] = self._authorization

        url = (base_url or self.BASE_PIK_URL) + sub_url

        request_counter = self.increment_request_counter()
        log_prefix = f"[{request_counter}] "

        _LOGGER.debug(
            log_prefix + f"Performing {title} with "
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
                        log_prefix + f"Could not perform {title}, "
                        f"status {request.status}, body: {await request.text()}"
                    )
                    raise PikIntercomException(
                        f"Could not perform {title} (status code {request.status})"
                    )

                resp_data = await request.json()

        except json.JSONDecodeError:
            _LOGGER.error(
                log_prefix + f"Could not perform {title}, "
                f"invalid JSON body: {await request.text()}"
            )
            raise PikIntercomException(
                f"Could not perform {title} (body decoding failed)"
            )

        except asyncio.TimeoutError:
            _LOGGER.error(
                log_prefix + f"Could not perform {title}, "
                f"waited for {self._session.timeout.total} seconds"
            )
            raise PikIntercomException(
                f"Could not perform {title} (timed out)"
            )

        except aiohttp.ClientError as e:
            _LOGGER.error(
                log_prefix + f"Could not perform {title}, client error: {e}"
            )
            raise PikIntercomException(
                f"Could not perform {title} (client error)"
            )

        else:
            if isinstance(resp_data, dict) and resp_data.get("error"):
                code, description = resp_data.get(
                    "code", "unknown"
                ), resp_data.get("description", "none provided")

                _LOGGER.error(
                    log_prefix + f"Could not perform {title}, "
                    f"code: {code}, "
                    f"description: {description}"
                )
                raise PikIntercomException(
                    f"Could not perform {title} ({code})"
                )

            _LOGGER.debug(
                log_prefix + f"Performed {title}, response: {resp_data}"
            )

            return resp_data, request.headers, request_counter

    async def _async_get(
        self,
        sub_url: str,
        headers: Optional[CIMultiDict] = None,
        authenticated: bool = False,
        title: str = "request",
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Any, CIMultiDictProxy[str], int]:
        """GET request wrapper"""
        return await self._async_req(
            aiohttp.hdrs.METH_GET,
            sub_url,
            headers,
            authenticated,
            title,
            base_url,
            **kwargs,
        )

    async def _async_post(
        self,
        sub_url: str,
        headers: Optional[CIMultiDict] = None,
        authenticated: bool = False,
        title: str = "request",
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Any, CIMultiDictProxy[str], int]:
        """POST request wrapper"""
        return await self._async_req(
            aiohttp.hdrs.METH_POST,
            sub_url,
            headers,
            authenticated,
            title,
            base_url,
            **kwargs,
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

        authorization = headers.get(aiohttp.hdrs.AUTHORIZATION)
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
            account = PikAccount(
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

        for property_type, properties_data in resp_data.items():
            for property_data in properties_data:
                property_id = property_data["id"]
                try:
                    property_ = self._properties[property_id]
                except KeyError:
                    self._properties[property_id] = PikProperty(
                        api=self,
                        category=property_type,
                        id=property_id,
                        scheme_id=property_data["scheme_id"],
                        number=property_data["number"],
                        section=property_data["section"],
                        building_id=property_data["building_id"],
                        district_id=property_data["district_id"],
                        account_number=property_data.get("account_number"),
                    )
                else:
                    if property_.category != property_type:
                        _LOGGER.warning(
                            f"[{request_counter}] Property category changed on {property_id} "
                            f"({property_.category} => {property_type})"
                        )
                    property_.api = self
                    property_.id = property_id
                    property_.category = property_type
                    property_.scheme_id = property_data["scheme_id"]
                    property_.number = property_data["number"]
                    property_.section = property_data["section"]
                    property_.building_id = property_data["building_id"]
                    property_.district_id = property_data["district_id"]
                    property_.account_number = property_data.get(
                        "account_number"
                    )

        # @TODO: add other properties

        _LOGGER.debug(
            f"[{request_counter}] Properties fetching successful {resp_data}"
        )

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
                    f"[{request_counter}] Property intercoms page {page_number} does not contain data"
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
                    intercoms[intercom_id] = PikPropertyDevice(
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
                    intercom.face_detection = intercom_data.get(
                        "face_detection"
                    )
                    intercom.video = video_data
                    intercom.photo_url = intercom_data.get("photo_url") or None

            _LOGGER.debug(
                f"[{request_counter}] Property intercoms fetching successful"
            )

    async def async_update_personal_intercoms(self) -> None:
        sub_url = f"/api/alfred/v1/personal/intercoms"
        intercoms = self._iot_intercoms
        relays = self._iot_relays
        page_number = 0
        found_relay_ids = set()

        while True:
            page_number += 1

            resp_data, headers, request_counter = await self._async_get(
                sub_url,
                title="IoT intercoms fetching",
                authenticated=True,
                base_url=self.BASE_RUBETEK_URL,
                params={"page": page_number},
            )

            if not resp_data:
                _LOGGER.debug(
                    f"[{request_counter}] IoT intercoms page "
                    f"{page_number} does not contain data"
                )
                break

            for iot_intercom_data in resp_data:
                iot_intercom_id = iot_intercom_data["id"]

                face_detection = bool(
                    iot_intercom_data.get("is_face_detection")
                )

                geo_unit_data = iot_intercom_data.get("geo_unit")
                geo_unit = (
                    PikIotIntercomGeoUnit(
                        id=geo_unit_data["id"],
                        full_name=geo_unit_data["full_name"],
                        short_name=geo_unit_data["short_name"],
                    )
                    if geo_unit_data
                    else None
                )

                try:
                    iot_intercom = intercoms[iot_intercom_id]

                except KeyError:
                    iot_intercom = PikIotIntercom(
                        api=self,
                        id=iot_intercom_id,
                        name=iot_intercom_data["name"],
                        client_id=iot_intercom_data["client_id"],
                        status=iot_intercom_data["status"],
                        photo_url=iot_intercom_data.get("live_snapshot_url"),
                        geo_unit=geo_unit,
                        face_detection=face_detection,
                        # sip_account=iot_intercom_data.get("sip_account"),
                    )
                    intercoms[iot_intercom_id] = iot_intercom
                else:
                    iot_intercom.api = self
                    iot_intercom.id = iot_intercom_id
                    iot_intercom.name = iot_intercom_data["name"]
                    iot_intercom.client_id = iot_intercom_data["client_id"]
                    iot_intercom.status = iot_intercom_data["status"]
                    iot_intercom.photo_url = iot_intercom_data.get(
                        "live_snapshot_url"
                    )
                    iot_intercom.geo_unit = geo_unit
                    iot_intercom.face_detection = face_detection

                iot_intercom_relays = iot_intercom.relays
                iot_intercom_relays.clear()

                for relay_data in sorted(
                    iot_intercom_data.get("relays") or (),
                    key=lambda x: x["id"],
                ):
                    iot_relay_id = relay_data["id"]
                    found_relay_ids.add(iot_relay_id)

                    relay_settings_data = relay_data.get("user_settings") or {}
                    relay_settings = PikIotRelaySettings(
                        custom_name=relay_settings_data.get("custom_name"),
                        is_favorite=bool(
                            relay_settings_data.get("is_favorite")
                        ),
                        is_hidden=bool(relay_settings_data.get("is_hidden")),
                    )

                    geo_unit_data = relay_data.get("geo_unit")
                    geo_unit = (
                        PikIotRelayGeoUnit(
                            id=geo_unit_data["id"],
                            full_name=geo_unit_data["full_name"],
                        )
                        if geo_unit_data
                        else None
                    )

                    try:
                        iot_relay = relays[iot_relay_id]
                    except KeyError:
                        iot_relay = PikIotRelay(
                            api=self,
                            id=iot_relay_id,
                            name=relay_data["name"],
                            user_settings=relay_settings,
                            geo_unit=geo_unit,
                            stream_url=relay_data.get("rtsp_url"),
                            photo_url=relay_data.get("live_snapshot_url"),
                        )
                        relays[iot_relay_id] = iot_relay
                    else:
                        iot_relay.api = self
                        iot_relay.id = iot_relay_id
                        iot_relay.name = relay_data["name"]
                        iot_relay.user_settings = relay_settings
                        iot_relay.geo_unit = geo_unit
                        iot_relay.stream_url = relay_data.get("rtsp_url")
                        iot_relay.photo_url = relay_data.get(
                            "live_snapshot_url"
                        )

                    iot_intercom_relays.append(iot_relay)

            _LOGGER.debug(
                f"[{request_counter}] Property intercoms fetching successful"
            )

        # Clean up old relay data
        for key in relays.keys() - found_relay_ids:
            del relays[key]

    async def async_device_unlock(self, intercom_id: int, mode: str) -> None:
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
            raise PikIntercomException(
                "Could not unlock intercom (result is False)"
            )

        _LOGGER.debug(f"[{request_counter}] Intercom unlocking successful")

    async def async_iot_relay_unlock(self, iot_relay_id: int) -> None:
        resp_data, headers, request_counter = await self._async_post(
            f"/api/alfred/v1/personal/relays/{iot_relay_id}/unlock",
            title="IoT relay unlocking",
            base_url=self.BASE_RUBETEK_URL,
            authenticated=True,
        )

        # @TODO: rule out correct response

        _LOGGER.debug(
            f"[{request_counter}] Intercom unlocking successful (assumed)"
        )

    @property
    def last_call_session(self) -> Optional["PikCallSession"]:
        try:
            return next(
                iter(
                    sorted(
                        self._call_sessions.values(),
                        key=lambda x: x.notified_at,
                        reverse=True,
                    )
                )
            )
        except StopIteration:
            return None

    async def async_update_call_sessions(
        self, max_pages: Optional[int] = 10
    ) -> None:
        sub_url = "/api/alfred/v1/personal/call_sessions"
        call_sessions = self._call_sessions
        page_number = 0
        last_call_session = self.last_call_session
        requires_further_updates = True

        while requires_further_updates and (
            max_pages is None or page_number < max_pages
        ):
            page_number += 1

            call_sessions_list, headers, request_counter = await self._async_get(
                sub_url,
                base_url=self.BASE_RUBETEK_URL,
                title=f"call sessions fetching (page {page_number})",
                authenticated=True,
                params={"page": page_number, "q[s]": "created_at DESC"},
            )

            if not call_sessions_list:
                _LOGGER.debug(
                    f"[{request_counter}] Call sessions page {page_number} does not contain data"
                )
                break

            for session_data in call_sessions_list:
                call_session_id = session_data["id"]

                notified_at = datetime.fromisoformat(session_data["notified_at"])

                if (
                    requires_further_updates
                    and last_call_session
                    and last_call_session.notified_at > notified_at
                ):
                    requires_further_updates = False

                finished_at = (
                    datetime.fromisoformat(session_data["finished_at"])
                    if session_data.get("finished_at")
                    else None
                )

                pickedup_at = (
                    datetime.fromisoformat(session_data["pickedup_at"])
                    if session_data.get("pickedup_at")
                    else None
                )

                if call_session_id not in call_sessions:
                    call_sessions[call_session_id] = PikCallSession(
                        api=self,
                        id=session_data["id"],
                        property_id=session_data["geo_unit_id"],
                        property_name=session_data["geo_unit_short_name"],
                        intercom_id=session_data["intercom_id"],
                        notified_at=notified_at,
                        finished_at=finished_at,
                        pickedup_at=pickedup_at,
                        intercom_name=session_data["intercom_name"],
                        photo_url=session_data.get("snapshot_url") or None
                    )
                else:
                    call_session = call_sessions[call_session_id]
                    call_session.api = self
                    call_session.id = session_data["id"]
                    call_session.property_id = session_data["geo_unit_id"]
                    call_session.property_name = session_data["geo_unit_short_name"]
                    call_session.intercom_id = session_data["intercom_id"]
                    call_session.intercom_name = session_data["intercom_name"]
                    call_session.notified_at = notified_at
                    call_session.finished_at = finished_at
                    call_session.pickedup_at = pickedup_at
                    call_session.photo_url = (
                        session_data.get("snapshot_url") or None
                    )

            _LOGGER.debug(
                f"[{request_counter}] Call sessions fetching successful"
            )

        if not requires_further_updates:
            _LOGGER.debug(
                f"[{self._request_counter}] Stopped due to list truncation"
            )


@attr.s(slots=True)
class _BaseObject:
    """Base class for PIK Intercom Objects"""

    api: PikIntercomAPI = attr.ib()


@attr.s(slots=True)
class PikObjectWithSnapshot(_BaseObject, ABC):
    @property
    @abstractmethod
    def photo_url(self) -> Optional[str]:
        raise NotImplementedError

    async def async_get_snapshot(self) -> bytes:
        photo_url = self.photo_url
        api = self.api

        if not photo_url:
            # @TODO: add diversion to get snapshot off RTSP
            raise PikIntercomException("Photo URL is empty")

        request_counter = api.increment_request_counter()
        log_prefix = f"[{request_counter}] "

        title = "camera snapshot retrieval"
        try:
            async with api.session.get(
                photo_url, raise_for_status=True
            ) as request:
                return await request.read()

        except asyncio.TimeoutError:
            _LOGGER.error(
                log_prefix + f"Could not perform {title}, "
                f"waited for {api.session.timeout.total} seconds"
            )
            raise PikIntercomException(
                f"Could not perform {title} (timed out)"
            )

        except aiohttp.ClientError as e:
            _LOGGER.error(
                log_prefix + f"Could not perform {title}, client error: {e}"
            )
            raise PikIntercomException(
                f"Could not perform {title} (client error)"
            )


@attr.s(slots=True)
class PikObjectWithVideo(_BaseObject, ABC):
    @property
    @abstractmethod
    def stream_url(self) -> Optional[str]:
        raise NotImplementedError


@attr.s(slots=True)
class PikAccount(_BaseObject):
    id: int = attr.ib()
    phone: str = attr.ib()
    email: Optional[str] = attr.ib(default=None)
    apartment_id: Optional[int] = attr.ib(default=None)
    number: Optional[str] = attr.ib(default=None)
    first_name: Optional[str] = attr.ib(default=None)
    last_name: Optional[str] = attr.ib(default=None)
    middle_name: Optional[str] = attr.ib(default=None)


@attr.s(slots=True)
class PikProperty(_BaseObject):
    category: str = attr.ib()
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
    def intercoms(self) -> Mapping[int, "PikPropertyDevice"]:
        return {
            intercom_id: intercom_device
            for intercom_id, intercom_device in self.api.devices.items()
            if intercom_device.property_id == self.id
        }  # @TODO: make into api-bound mapping


@attr.s(slots=True)
class PikCallSession(_BaseObject):
    id: int = attr.ib()
    property_id: int = attr.ib()
    property_name: str = attr.ib()
    intercom_id: int = attr.ib()
    intercom_name: str = attr.ib()
    photo_url: Optional[str] = attr.ib()
    notified_at: Optional[datetime] = attr.ib(default=None)
    pickedup_at: Optional[datetime] = attr.ib(default=None)
    finished_at: Optional[datetime] = attr.ib(default=None)

    @property
    def full_photo_url(self) -> Optional[str]:
        return self.photo_url


@attr.s(slots=True)
class PikPropertyDevice(PikObjectWithSnapshot, PikObjectWithVideo):
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
    property_id: Optional[int] = attr.ib(
        default=None
    )  # Non-standard attribute

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
        await self.api.async_device_unlock(self.id, self.mode)


class PikIotRelaySettings(NamedTuple):
    custom_name: Optional[str]
    is_favorite: bool
    is_hidden: bool


class PikIotRelayGeoUnit(NamedTuple):
    id: int
    full_name: str


@attr.s(slots=True)
class PikIotRelay(PikObjectWithSnapshot, PikObjectWithVideo):
    id: int = attr.ib()
    name: str = attr.ib()
    user_settings: PikIotRelaySettings = attr.ib()
    geo_unit: Optional[PikIotRelayGeoUnit] = attr.ib(default=None)
    stream_url: Optional[str] = attr.ib(default=None)
    photo_url: Optional[str] = attr.ib(default=None)

    @property
    def friendly_name(self) -> str:
        return self.user_settings.custom_name or self.name

    async def async_unlock(self) -> None:
        """Unlock IoT relay"""
        return await self.api.async_iot_relay_unlock(self.id)


class PikIotIntercomGeoUnit(NamedTuple):
    id: int
    full_name: str
    short_name: str


@attr.s(slots=True)
class PikIotIntercom(PikObjectWithSnapshot):
    id: int = attr.ib()
    name: str = attr.ib()
    client_id: int = attr.ib()
    status: str = attr.ib()
    photo_url: Optional[str] = attr.ib(default=None)
    geo_unit: Optional[PikIotIntercomGeoUnit] = attr.ib(default=None)
    face_detection: bool = attr.ib(default=False)
    relays: List[PikIotRelay] = attr.ib(factory=list)
