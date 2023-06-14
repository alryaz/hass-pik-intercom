__all__ = (
    "PikIntercomAPI",
    "PikAccount",
    "PikPropertyDevice",
    "PikCallSession",
    "PikIntercomException",
    "PikIotRelay",
    "PikIotMeter",
    "PikIotCamera",
    "PikProperty",
    "PikIotIntercom",
    "PikObjectWithVideo",
    "PikObjectWithSnapshot",
    "PikObjectWithSIP",
    "PikObjectWithUnlocker",
    "PikCustomerDevice",
    "PikActiveCallSession",
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
from dataclasses import dataclass, field
from datetime import datetime
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
    MutableMapping,
    TypeVar,
)

import aiohttp
from multidict import CIMultiDict, CIMultiDictProxy, MultiDict

_LOGGER = logging.getLogger(__name__)

DEFAULT_DEVICE_MODEL: Final = "Python API"
DEFAULT_USER_AGENT: Final = "okhttp/4.9.0"
DEFAULT_CLIENT_APP: Final = "alfred"
DEFAULT_CLIENT_VERSION: Final = "2023.5.1"
DEFAULT_CLIENT_OS: Final = "Android"

# These are arbitrary, and never seen before
VIDEO_QUALITY_TYPES: Final = ("high", "medium", "low")

_T = TypeVar("_T")


class PikIntercomException(Exception):
    """Base class for exceptions"""


class PikIntercomAPI:
    BASE_ICM_URL: ClassVar[str] = "https://intercom.rubetek.com"
    BASE_IOT_URL: ClassVar[str] = "https://iot.rubetek.com"

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        device_id: Optional[str] = None,
        *,
        device_model: str = DEFAULT_DEVICE_MODEL,
        user_agent: str = DEFAULT_USER_AGENT,
        client_app: str = DEFAULT_CLIENT_APP,
        client_version: str = DEFAULT_CLIENT_VERSION,
        client_os: str = DEFAULT_CLIENT_OS,
    ) -> None:
        self._username = username
        self._password = password

        self.session = session

        self.device_id = device_id or "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=16,
            )
        )
        self.device_model = device_model
        self.user_agent = user_agent
        self.client_app = client_app
        self.client_version = client_version
        self.client_os = client_os

        self._authorization: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._request_counter: int = 0

        self._account: Optional[PikAccount] = None
        self._properties: Dict[int, PikProperty] = {}
        self._devices: Dict[int, PikPropertyDevice] = {}
        self._customer_devices: Dict[int, PikCustomerDevice] = {}

        # Placeholders for IoT requests
        self._iot_intercoms: Dict[int, PikIotIntercom] = {}
        self._iot_relays: Dict[int, PikIotRelay] = {}
        self._iot_cameras: Dict[int, PikIotCamera] = {}
        self._iot_meters: Dict[int, PikIotMeter] = {}
        self._call_sessions: Dict[int, PikCallSession] = {}

        # @TODO: add other properties

    def get_sip_password(self, ex_user: str) -> Optional[str]:
        for device in self._customer_devices.values():
            if device.ex_user == ex_user and (password := device.password):
                return password

    @property
    def username(self) -> str:
        return self._username

    @property
    def account(self) -> Optional["PikAccount"]:
        return self._account

    @property
    def is_authenticated(self) -> bool:
        return self._authorization is not None

    @property
    def customer_device(self) -> Optional["PikCustomerDevice"]:
        for device in self._customer_devices.values():
            if device.uid == self.device_id:
                return device

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
    def iot_cameras(self) -> Mapping[int, "PikIotCamera"]:
        return MappingProxyType(self._iot_cameras)

    @property
    def iot_relays(self) -> Mapping[int, "PikIotRelay"]:
        return MappingProxyType(self._iot_relays)

    @property
    def iot_meters(self) -> Mapping[int, "PikIotMeter"]:
        return MappingProxyType(self._iot_meters)

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
        elif not isinstance(headers, MutableMapping):
            headers = CIMultiDict(headers)

        headers.update(
            {
                aiohttp.hdrs.USER_AGENT: self.user_agent,
                "API-VERSION": "2",
                "device-client-app": self.client_app,
                "device-client-version": self.client_version,
                "device-client-os": self.client_os,
                "device-client-uid": self.device_id,
            }
        )

        if authenticated:
            if not self.is_authenticated:
                raise PikIntercomException("API not authenticated")

            headers[aiohttp.hdrs.AUTHORIZATION] = self._authorization

        url = (base_url or self.BASE_ICM_URL) + sub_url

        request_counter = self.increment_request_counter()
        log_prefix = f"[{request_counter}] "

        _LOGGER.debug(log_prefix + f"Performing {title} with " f'username "{self._masked_username}", url: {url}')

        try:
            async with self.session.request(
                method,
                url,
                headers=headers,
                **kwargs,
            ) as request:
                if request.status not in (200, 201):
                    _LOGGER.error(
                        log_prefix + f"Could not perform {title}, "
                        f"status {request.status}, body: {await request.text()}"
                    )
                    raise PikIntercomException(f"Could not perform {title} (status code {request.status})")

                resp_data = await request.json()

        except json.JSONDecodeError:
            _LOGGER.error(log_prefix + f"Could not perform {title}, " f"invalid JSON body: {await request.text()}")
            raise PikIntercomException(f"Could not perform {title} (body decoding failed)")

        except asyncio.TimeoutError:
            _LOGGER.error(
                log_prefix + f"Could not perform {title}, " f"waited for {self.session.timeout.total} seconds"
            )
            raise PikIntercomException(f"Could not perform {title} (timed out)")

        except aiohttp.ClientError as e:
            _LOGGER.error(log_prefix + f"Could not perform {title}, client error: {e}")
            raise PikIntercomException(f"Could not perform {title} (client error)")

        else:
            if isinstance(resp_data, dict) and resp_data.get("error"):
                code, description = resp_data.get("code", "unknown"), resp_data.get("description", "none provided")

                _LOGGER.error(
                    log_prefix + f"Could not perform {title}, " f"code: {code}, " f"description: {description}"
                )
                raise PikIntercomException(f"Could not perform {title} ({code})")

            _LOGGER.debug(log_prefix + f"Performed {title}, response: {resp_data}")

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

        if not (authorization := headers.get(aiohttp.hdrs.AUTHORIZATION)):
            _LOGGER.error(
                f"[{request_counter}] Could not perform authentication, "
                f"({aiohttp.hdrs.AUTHORIZATION} header not found)"
            )
            raise PikIntercomException(
                f"Could not perform authentication " f"({aiohttp.hdrs.AUTHORIZATION} header not found)"
            )

        self._authorization = authorization

        # Update account data
        account_data = resp_data["account"]

        if not (account := self._account):
            account = PikAccount(
                api=self,
                id=account_data["id"],
                phone=account_data["phone"],
            )
            self._account = account

        account.email = account_data.get("email")
        account.number = account_data.get("number")
        account.apartment_id = account_data.get("apartment_id")
        account.first_name = account_data.get("first_name")
        account.last_name = account_data.get("last_name")
        account.middle_name = account_data.get("middle_name")

        for device_data in resp_data.get("customer_devices") or ():
            self._deserialize_customer_device(device_data)

        _LOGGER.debug(f"[{request_counter}] Authentication successful")

    def _deserialize_customer_device(self, data: Mapping[str, Any]) -> Optional["PikCustomerDevice"]:
        try:
            customer_device_id = int(data["id"])
            customer_device_account_id = int(data["account_id"])
        except (TypeError, ValueError, LookupError):
            return None

        try:
            customer_device = self._customer_devices[customer_device_id]
        except KeyError:
            self._customer_devices[customer_device_id] = customer_device = PikCustomerDevice(
                api=self,
                id=customer_device_id,
                uid=data["uid"],
                account_id=customer_device_account_id,
            )

        customer_device.apartment_id = data.get("apartment_id") or None
        customer_device.model = data.get("model") or None
        customer_device.kind = data.get("kind") or None
        customer_device.firmware_version = data.get("firmware_version") or None
        customer_device.mac_address = data.get("mac_address") or None
        customer_device.os = data.get("os") or None
        customer_device.deleted_at = data.get("deleted_at") or None

        if sip_account_data := data.get("sip_account") or None:
            customer_device.ex_user = sip_account_data.get("ex_user") or None
            customer_device.proxy = sip_account_data.get("proxy") or None
            customer_device.realm = sip_account_data.get("realm") or None
            customer_device.ex_enable = bool(sip_account_data.get("ex_enable"))
            customer_device.alias = sip_account_data.get("alias") or None
            customer_device.remote_request_status = sip_account_data.get("remote_request_status") or None
            customer_device.password = sip_account_data.get("password") or None

        return customer_device

    async def async_update_customer_device(self) -> Any:
        if not (device_id := self.device_id):
            raise PikIntercomException("device ID not set")
        try:
            resp_data, headers, request_counter = await self._async_get(
                "/api/customers/devices/lookup",
                title="customer device lookup",
                authenticated=True,
                params={"customer_device[uid]": device_id},
            )
        except PikIntercomException:
            resp_data, headers, request_counter = await self._async_post(
                "/api/customers/devices",
                title="customer device initialization",
                authenticated=True,
                params={
                    "customer_device[model]": self.device_model,
                    "customer_device[kind]": "mobile",
                    "customer_device[uid]": device_id,
                    "customer_device[os]": self.client_os.lower(),
                    "customer_device[push_version]": "2.0.0",
                },
            )

        if self._deserialize_customer_device(resp_data) is None:
            raise PikIntercomException(f"could not create customer device for id {self.device_id}")

    async def async_set_customer_device_push_token(self, push_token: str) -> None:
        customer_device_id = None
        for device_id, device in self._customer_devices.items():
            if device.uid == self.device_id:
                customer_device_id = device_id
                break
        if customer_device_id is None:
            raise PikIntercomException("device by id not found")
        await self._async_req(
            aiohttp.hdrs.METH_PATCH,
            f"/api/customers/devices/{customer_device_id}",
            title="customer device push token update",
            authenticated=True,
            params={"customer_device[push_token]": push_token},
        )

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
                    property_.account_number = property_data.get("account_number")

        # @TODO: add other properties

        _LOGGER.debug(f"[{request_counter}] Properties fetching successful {resp_data}")

    async def async_update_property_intercoms(self, property_id: int) -> None:
        sub_url = f"/api/customers/properties/{property_id}/intercoms"
        page_number = 0

        intercoms = self._devices
        found_intercoms = set()

        while True:
            page_number += 1

            resp_data, headers, request_counter = await self._async_get(
                sub_url,
                title="property intercoms fetching",
                authenticated=True,
                params={"page": page_number},
            )

            if not resp_data:
                _LOGGER.debug(f"[{request_counter}] Property intercoms page {page_number} does not contain data")
                break

            for data in resp_data:
                try:
                    intercom_id = int(data["id"])
                except (TypeError, ValueError):
                    continue

                found_intercoms.add(intercom_id)

                try:
                    intercom = intercoms[intercom_id]
                except KeyError:
                    intercom = PikPropertyDevice(api=self, id=intercom_id)
                    intercoms[intercom_id] = intercom

                intercom.property_id = data.get("property_id") or None
                intercom.scheme_id = data.get("scheme_id") or None
                intercom.building_id = data.get("building_id") or None
                intercom.kind = data.get("kind") or None
                intercom.device_category = data.get("device_category") or None
                intercom.mode = data.get("mode") or None
                intercom.name = data.get("name") or None
                intercom.human_name = data.get("human_name") or None
                intercom.renamed_name = data.get("renamed_name") or None
                intercom.checkpoint_relay_index = data.get("checkpoint_relay_index")
                intercom.relays = data.get("relays") or None
                intercom.entrance = data.get("entrance")
                intercom.can_address = data.get("can_address")
                intercom.face_detection = data.get("face_detection")
                intercom.video = (
                    MultiDict([(v["quality"], v["source"]) for v in video_data])
                    if (video_data := data.get("video"))
                    else None
                )
                intercom.photo_url = data.get("photo_url") or None

                if sip_account_data := data.get("sip_account") or None:
                    intercom.ex_user = sip_account_data.get("ex_user")
                    intercom.proxy = sip_account_data.get("proxy")

            _LOGGER.debug(f"[{request_counter}] Property intercoms fetching successful")

    async def async_update_iot_intercoms(self) -> None:
        sub_url = f"/api/alfred/v1/personal/intercoms"
        page_number = 0

        # Prepare object placeholders
        intercoms, relays = self._iot_intercoms, self._iot_relays
        found_intercoms, found_relays = set(), set()

        while True:
            page_number += 1

            resp_data, headers, request_counter = await self._async_get(
                sub_url,
                title="IoT intercoms fetching",
                authenticated=True,
                base_url=self.BASE_IOT_URL,
                params={"page": page_number},
            )

            if not resp_data:
                # @TODO: use response header for count data
                _LOGGER.debug(f"[{request_counter}] IoT intercoms page " f"{page_number} does not contain data")
                break

            for intercom_data in resp_data:
                try:
                    intercom_id = int(intercom_data["id"])
                except (TypeError, ValueError):
                    continue

                found_intercoms.add(intercom_id)

                # Get old or create new intercom object
                try:
                    intercom = intercoms[intercom_id]
                except KeyError:
                    intercom = PikIotIntercom(api=self, id=intercom_id)
                    intercoms[intercom_id] = intercom

                # Set additional data
                intercom.name = intercom_data["name"]
                intercom.client_id = intercom_data.get("client_id") or None
                intercom.status = intercom_data.get("status") or None
                intercom.live_snapshot_url = intercom_data.get("live_snapshot_url") or None
                intercom.is_face_detection = bool(intercom_data.get("is_face_detection"))

                geo_unit_short_name = None
                if geo_unit_data := intercom_data.get("geo_unit"):
                    geo_unit_short_name = geo_unit_data.get("short_name") or None
                    intercom.geo_unit_id = geo_unit_data.get("id") or None
                    intercom.geo_unit_full_name = geo_unit_data.get("full_name") or None
                    intercom.geo_unit_short_name = geo_unit_short_name

                # Set / update relay data
                intercom.relays.clear()
                for relay_data in intercom_data.get("relays") or ():
                    try:
                        relay_id = int(relay_data["id"])
                    except (TypeError, ValueError):
                        continue

                    found_relays.add(relay_id)

                    # Get old or create new relay object
                    try:
                        relay = relays[relay_id]
                    except KeyError:
                        relay = PikIotRelay(api=self, id=relay_id)
                        relays[relay_id] = relay

                    # Set additional data
                    relay.name = relay_data.get("name") or None
                    relay.rtsp_url = relay_data.get("rtsp_url") or None
                    relay.live_snapshot_url = relay_data.get("live_snapshot_url") or None

                    # Parse geo_unit parameter
                    if geo_unit_data := relay_data.get("geo_unit"):
                        relay.geo_unit_id = geo_unit_data.get("id") or None
                        relay.geo_unit_full_name = geo_unit_data.get("full_name") or None

                    # Parse user_settings parameter
                    if relay_settings_data := relay_data.get("user_settings"):
                        relay.custom_name = relay_settings_data.get("custom_name") or None
                        relay.is_favorite = bool(relay_settings_data.get("is_favorite"))
                        relay.is_hidden = bool(relay_settings_data.get("is_hidden"))

                    # Propagated from related intercom
                    relay.geo_unit_short_name = geo_unit_short_name

            _LOGGER.debug(f"[{request_counter}] Property intercoms fetching successful")

        # Clean up obsolete data
        for key in intercoms.keys() - found_intercoms:
            del intercoms[key]
        for key in relays.keys() - found_relays:
            del relays[key]

    async def async_update_iot_cameras(self) -> None:
        sub_url = f"/api/alfred/v1/personal/cameras"
        page_number = 0

        # Prepare object placeholders
        cameras = self._iot_meters
        found_cameras = set()

        while True:
            page_number += 1

            resp_data, headers, request_counter = await self._async_get(
                sub_url,
                title="IoT cameras fetching",
                authenticated=True,
                base_url=self.BASE_IOT_URL,
                params={"page": page_number},
            )

            if not resp_data:
                # @TODO: use response header for count data
                _LOGGER.debug(f"[{request_counter}] IoT cameras page " f"{page_number} does not contain data")
                break

            for camera_data in resp_data:
                try:
                    camera_id = int(camera_data["id"])
                except (TypeError, ValueError):
                    return

                found_cameras.add(camera_id)

                try:
                    camera = self._iot_cameras[camera_id]
                except KeyError:
                    camera = PikIotCamera(api=self, id=camera_id)
                    self._iot_cameras[camera_id] = camera

                # Set additional data
                camera.name = camera_data["name"]
                camera.rtsp_url = camera_data.get("rtsp_url") or None
                camera.live_snapshot_url = camera_data.get("live_snapshot_url") or None
                camera.geo_unit_short_name = camera_data.get("geo_unit_short_name") or None

            _LOGGER.debug(f"[{request_counter}] Property intercoms fetching successful")

        # Clean up obsolete data
        for key in cameras.keys() - found_cameras:
            del cameras[key]

    async def async_update_iot_meters(self) -> None:
        sub_url = f"/api/alfred/v1/personal/meters"
        page_number = 0

        # Prepare object placeholders
        meters = self._iot_meters
        found_meters = set()

        while True:
            page_number += 1

            resp_data, headers, request_counter = await self._async_get(
                sub_url,
                title="IoT meters fetching",
                authenticated=True,
                base_url=self.BASE_IOT_URL,
                params={"page": page_number},
            )

            if not resp_data:
                # @TODO: use response header for count data
                _LOGGER.debug(f"[{request_counter}] IoT cameras page " f"{page_number} does not contain data")
                break

            for meter_data in resp_data:
                try:
                    meter_id = int(meter_data["id"])
                except (TypeError, ValueError):
                    continue

                found_meters.add(meter_id)

                # Get old or create new intercom object
                try:
                    meter = meters[meter_id]
                except KeyError:
                    meter = PikIotMeter(api=self, id=meter_id)
                    meters[meter_id] = meter

                # Set additional data
                try:
                    pipe_identifier = int(meter_data.get("pipe_identifier"))
                except (TypeError, ValueError):
                    pipe_identifier = None

                meter.serial = meter_data.get("serial") or None
                meter.kind = meter_data.get("kind") or None
                meter.pipe_identifier = pipe_identifier
                meter.status = meter_data.get("status") or None
                meter.title = meter_data.get("title") or None
                meter.current_value = meter_data.get("current_value") or None
                meter.month_value = meter_data.get("month_value") or None
                meter.geo_unit_short_name = meter_data.get("geo_unit_short_name") or None

            _LOGGER.debug(f"[{request_counter}] Property intercoms fetching successful")

        # Clean up obsolete data
        for key in meters.keys() - found_meters:
            del meters[key]

    async def async_unlock_property_intercom(self, intercom_id: int, mode: str) -> None:
        """
        Send command to property device to unlock.
        :param intercom_id: Property device identifier
        :param mode: <unknown parameter, comes from PropertyDevice data object>
        """
        resp_data, headers, request_counter = await self._async_post(
            f"/api/customers/intercoms/{intercom_id}/unlock",
            data={"id": intercom_id, "door": mode},
            title="intercom unlocking",
            authenticated=True,
        )

        if resp_data.get("request") is not True:
            _LOGGER.error(f"[{request_counter}] Timed out unlocking intercom")
            raise PikIntercomException("Timed out unlocking intercom")

        _LOGGER.debug(f"[{request_counter}] Intercom unlocking successful")

    async def async_unlock_iot_relay(self, iot_relay_id: int) -> None:
        """
        Send command to IoT relay to unlock.
        :param iot_relay_id: IoT relay identifier.
        """
        resp_data, headers, request_counter = await self._async_post(
            f"/api/alfred/v1/personal/relays/{iot_relay_id}/unlock",
            title="IoT relay unlocking",
            base_url=self.BASE_IOT_URL,
            authenticated=True,
        )

        # @TODO: rule out correct response

        _LOGGER.debug(f"[{request_counter}] Intercom unlocking successful (assumed)")

    async def async_get_current_call_session(self) -> Optional["PikActiveCallSession"]:
        resp_data, headers, request_counter = await self._async_get(
            "/api/alfred/v1/personal/call_sessions/current",
            title="current call session",
            base_url=self.BASE_IOT_URL,
            authenticated=True,
        )

        notified_at = datetime.fromisoformat(resp_data["notified_at"]) if resp_data.get("notified_at") else None
        pickedup_at = datetime.fromisoformat(resp_data["pickedup_at"]) if resp_data.get("pickedup_at") else None
        finished_at = datetime.fromisoformat(resp_data["finished_at"]) if resp_data.get("finished_at") else None
        deleted_at = datetime.fromisoformat(resp_data["deleted_at"]) if resp_data.get("deleted_at") else None
        created_at = datetime.fromisoformat(resp_data["created_at"]) if resp_data.get("created_at") else None

        target_relays = []
        for relay_data in resp_data.get("target_relays") or ():
            try:
                relay = self._iot_relays[int(relay_data["id"])]
            except (TypeError, ValueError, LookupError):
                continue
            else:
                target_relays.append(relay)

        return PikActiveCallSession(
            api=self,
            id=int(resp_data["id"]),
            intercom_id=int(resp_data["intercom_id"]),
            intercom_name=resp_data.get("intercom_name") or None,
            property_id=int(resp_data["property_id"]) if resp_data.get("property_id") else None,
            property_name=resp_data.get("property_name") or None,
            notified_at=notified_at,
            pickedup_at=pickedup_at,
            finished_at=finished_at,
            deleted_at=deleted_at,
            created_at=created_at,
            geo_unit_id=int(resp_data["geo_unit_id"]) if resp_data.get("geo_unit_id") else None,
            geo_unit_short_name=resp_data.get("geo_unit_name") or None,
            identifier=resp_data.get("identifier") or None,
            provider=resp_data.get("provider") or None,
            proxy=resp_data.get("proxy") or None,
            snapshot_url=resp_data.get("snapshot_url"),
            target_relays=target_relays,
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

    async def async_update_call_sessions(self, max_pages: Optional[int] = 10) -> None:
        sub_url = "/api/alfred/v1/personal/call_sessions"
        call_sessions = self._call_sessions
        page_number = 0
        last_call_session = self.last_call_session
        requires_further_updates = True

        while requires_further_updates and (max_pages is None or page_number < max_pages):
            page_number += 1

            (call_sessions_list, headers, request_counter,) = await self._async_get(
                sub_url,
                base_url=self.BASE_IOT_URL,
                title=f"call sessions fetching (page {page_number})",
                authenticated=True,
                params={"page": page_number, "q[s]": "created_at DESC"},
            )

            if not call_sessions_list:
                _LOGGER.debug(f"[{request_counter}] Call sessions page {page_number} does not contain data")
                break

            for session_data in call_sessions_list:
                call_session_id = session_data["id"]

                notified_at = datetime.fromisoformat(session_data["notified_at"])

                if requires_further_updates and last_call_session and last_call_session.notified_at > notified_at:
                    requires_further_updates = False

                finished_at = (
                    datetime.fromisoformat(session_data["finished_at"]) if session_data.get("finished_at") else None
                )

                pickedup_at = (
                    datetime.fromisoformat(session_data["pickedup_at"]) if session_data.get("pickedup_at") else None
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
                        photo_url=session_data.get("snapshot_url") or None,
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
                    call_session.photo_url = session_data.get("snapshot_url") or None

            _LOGGER.debug(f"[{request_counter}] Call sessions fetching successful")

        if not requires_further_updates:
            _LOGGER.debug(f"[{self._request_counter}] Stopped due to list truncation")


@dataclass(slots=True)
class _BaseObject:
    """Base class for PIK Intercom Objects"""

    api: PikIntercomAPI
    id: int


class PikObjectWithSnapshot(_BaseObject, ABC):
    @property
    @abstractmethod
    def snapshot_url(self) -> Optional[str]:
        raise NotImplementedError

    @property
    def has_camera(self) -> bool:
        return bool(self.snapshot_url) or getattr(super(), "has_camera", False)

    async def async_get_snapshot(self) -> bytes:
        snapshot_url = self.snapshot_url
        api = self.api

        if not snapshot_url:
            # @TODO: add diversion to get snapshot off RTSP
            raise PikIntercomException("Photo URL is empty")

        request_counter = api.increment_request_counter()
        log_prefix = f"[{request_counter}] "

        title = "camera snapshot retrieval"
        try:
            async with api.session.get(snapshot_url, raise_for_status=True) as request:
                return await request.read()

        except asyncio.TimeoutError:
            _LOGGER.error(log_prefix + f"Could not perform {title}, " f"waited for {api.session.timeout.total} seconds")
            raise PikIntercomException(f"Could not perform {title} (timed out)")

        except aiohttp.ClientError as e:
            _LOGGER.error(log_prefix + f"Could not perform {title}, client error: {e}")
            raise PikIntercomException(f"Could not perform {title} (client error)")


class PikObjectWithVideo(_BaseObject, ABC):
    @property
    @abstractmethod
    def stream_url(self) -> Optional[str]:
        raise NotImplementedError

    @property
    def has_camera(self) -> bool:
        return bool(self.stream_url) or getattr(super(), "has_camera", False)


class PikObjectWithUnlocker(_BaseObject, ABC):
    @abstractmethod
    async def async_unlock(self) -> None:
        raise NotImplementedError


class PikObjectWithSIP(_BaseObject, ABC):
    @property
    @abstractmethod
    def sip_user(self) -> Optional[str]:
        raise NotImplementedError

    @property
    def sip_password(self) -> Optional[str]:
        if user := self.sip_user:
            return self.api.get_sip_password(user)


@dataclass(slots=True)
class PikAccount(_BaseObject):
    phone: str
    email: Optional[str] = None
    apartment_id: Optional[int] = None
    number: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None


@dataclass(slots=True)
class PikProperty(_BaseObject):
    category: str
    scheme_id: int
    number: str
    section: int
    building_id: int
    district_id: int
    account_number: Optional[str] = None

    async def async_update_intercoms(self) -> None:
        await self.api.async_update_property_intercoms(self.id)

    @property
    def intercoms(self) -> Mapping[int, "PikPropertyDevice"]:
        return {
            intercom_id: intercom_device
            for intercom_id, intercom_device in self.api.devices.items()
            if intercom_device.property_id == self.id
        }  # @TODO: make into api-bound mapping


@dataclass(slots=True)
class _BasePikCallSession(PikObjectWithSnapshot, ABC):
    intercom_id: int
    intercom_name: Optional[str] = None
    property_id: Optional[int] = None
    property_name: Optional[str] = None
    notified_at: Optional[datetime] = None
    pickedup_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


@dataclass(slots=True)
class PikCallSession(_BasePikCallSession):
    photo_url: Optional[str] = None

    @property
    def snapshot_url(self) -> Optional[str]:
        return self.photo_url


@dataclass(slots=True)
class PikActiveCallSession(_BasePikCallSession, PikObjectWithUnlocker):
    geo_unit_id: Optional[int] = None
    geo_unit_short_name: Optional[str] = None
    identifier: Optional[str] = None
    provider: Optional[str] = None
    proxy: Optional[str] = None
    snapshot_url: Optional[str] = None
    target_relays: List["PikIotRelay"] = field(default_factory=list)

    async def async_unlock(self) -> None:
        if not self.target_relays:
            raise PikIntercomException("no target relays provided")

        errors = []
        for task in (
            await asyncio.wait(
                [asyncio.create_task(relay.async_unlock()) for relay in self.target_relays],
                return_when=asyncio.ALL_COMPLETED,
            )
        )[0]:
            if (exc := task.exception()) and not isinstance(exc, asyncio.CancelledError):
                _LOGGER.error(f"Error occurred on unlocking: {exc}", exc_info=exc)
                errors.append(exc)

        if errors:
            raise PikIntercomException(f"Error(s) occurred while unlocking: {', '.join(map(str, errors))}")


@dataclass(slots=True)
class PikPropertyDevice(PikObjectWithSnapshot, PikObjectWithVideo, PikObjectWithUnlocker, PikObjectWithSIP):
    scheme_id: Optional[int] = None
    building_id: Optional[int] = None
    kind: Optional[str] = None
    device_category: Optional[str] = None
    mode: Optional[str] = None
    name: Optional[str] = None
    human_name: Optional[str] = None
    renamed_name: Optional[str] = None
    relays: Optional[Dict[str, str]] = None
    checkpoint_relay_index: Optional[int] = None
    entrance: Optional[int] = None
    can_address: Optional[Any] = None
    face_detection: Optional[bool] = None
    video: Optional[MultiDict[str]] = None
    photo_url: Optional[str] = None
    property_id: Optional[int] = None  # Non-standard attribute

    # From sip_account parameter
    proxy: Optional[str] = None
    ex_user: Optional[str] = None

    @property
    def sip_user(self) -> Optional[str]:
        return self.ex_user

    @property
    def stream_url(self) -> Optional[str]:
        """Return URL for video stream"""
        if not (video_streams := self.video):
            return None

        for quality in VIDEO_QUALITY_TYPES:
            if video_stream_url := video_streams.get(quality):
                return video_stream_url

        return next(iter(video_streams.values()))

    @property
    def snapshot_url(self) -> Optional[str]:
        return self.photo_url

    async def async_unlock(self) -> None:
        """Unlock intercom"""
        await self.api.async_unlock_property_intercom(self.id, self.mode)


@dataclass(slots=True)
class PikIotMeter(_BaseObject):
    serial: Optional[str] = None
    kind: Optional[str] = None
    pipe_identifier: Optional[int] = None
    status: Optional[str] = None
    title: Optional[str] = None
    current_value: Optional[str] = None
    month_value: Optional[str] = None
    geo_unit_short_name: Optional[str] = None

    @staticmethod
    def _convert_value(value: Any) -> float:
        if value is None:
            raise TypeError("cannot convert NoneType to float")
        return float(str(value).rpartition(" ")[0].replace(" ", ""))

    @property
    def current_value_numeric(self) -> Optional[float]:
        return PikIotMeter._convert_value(value) if (value := self.current_value) else None

    @property
    def month_value_numeric(self) -> Optional[float]:
        return PikIotMeter._convert_value(value) if (value := self.month_value) else None


@dataclass(slots=True)
class _PikIotBaseCamera(PikObjectWithSnapshot):
    name: Optional[str] = None
    live_snapshot_url: Optional[str] = None

    @property
    def snapshot_url(self) -> Optional[str]:
        return self.live_snapshot_url


@dataclass(slots=True)
class _PikIotCameraWithRTSP(_PikIotBaseCamera, PikObjectWithVideo):
    rtsp_url: Optional[str] = None

    @property
    def stream_url(self) -> Optional[str]:
        return self.rtsp_url


@dataclass(slots=True)
class PikIotRelay(_PikIotCameraWithRTSP, PikObjectWithUnlocker):
    # From geo_unit parameter
    geo_unit_id: Optional[int] = None
    geo_unit_full_name: Optional[str] = None

    # From user_settings parameter
    custom_name: Optional[str] = None
    is_favorite: bool = False
    is_hidden: bool = False

    # Propagated from parent intercom
    geo_unit_short_name: Optional[str] = None

    @property
    def friendly_name(self) -> str:
        return self.custom_name or self.name

    async def async_unlock(self) -> None:
        """Unlock IoT relay"""
        return await self.api.async_unlock_iot_relay(self.id)


@dataclass(slots=True)
class PikIotCamera(_PikIotCameraWithRTSP):
    geo_unit_short_name: Optional[str] = None


@dataclass(slots=True)
class PikIotIntercom(_PikIotBaseCamera, PikObjectWithSIP):
    client_id: Optional[int] = None
    is_face_detection: bool = False
    relays: List[PikIotRelay] = field(default_factory=list)

    # From geo_unit parameter
    geo_unit_id: Optional[int] = None
    geo_unit_short_name: Optional[str] = None
    geo_unit_full_name: Optional[str] = None

    # From sip_account parameter
    proxy: Optional[str] = None
    ex_user: Optional[str] = None

    # Non-expected properties
    status: Optional[str] = None
    webrtc_supported: Optional[bool] = None

    @property
    def sip_user(self) -> Optional[str]:
        return self.ex_user

    @property
    def stream_url(self) -> Optional[str]:
        # Return relay matching snapshot url
        if snapshot_url := self.snapshot_url:
            for relay in self.relays:
                if relay.snapshot_url == snapshot_url:
                    return relay.stream_url

        # Return first relay
        for relay in self.relays:
            if relay.stream_url:
                return relay.stream_url


@dataclass(slots=True)
class PikCustomerDevice(PikObjectWithSIP):
    account_id: int
    uid: str
    apartment_id: Optional[int] = None
    model: Optional[str] = None
    kind: Optional[str] = None
    firmware_version: Optional[str] = None
    mac_address: Optional[str] = None
    os: Optional[str] = None
    deleted_at: Any = None

    # From sip_account parameter
    ex_user: Optional[str] = None
    proxy: Optional[str] = None
    realm: Optional[str] = None
    ex_enable: bool = False
    alias: Optional[str] = None
    remote_request_status: Optional[str] = None
    password: Optional[str] = None

    @property
    def sip_user(self) -> Optional[str]:
        return self.ex_user

    @property
    def sip_password(self) -> Optional[str]:
        return self.password
