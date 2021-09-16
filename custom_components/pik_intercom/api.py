import logging
import random
import string
from types import MappingProxyType
from typing import Any, ClassVar, Dict, Mapping, Optional

import aiohttp
import attr
from multidict import MultiDict

_LOGGER = logging.getLogger(__name__)


class PikDomofonException(Exception):
    pass


class PikDomofonAPI:
    BASE_PIK_URL: ClassVar[str] = "https://intercom.pik-comfort.ru"

    def __init__(self, username: str, password: str, device_id: Optional[str] = None):
        self._username = username
        self._password = password
        self._device_id = device_id or "".join(
            random.choices(string.ascii_uppercase + string.digits, k=16)
        )
        self._session = aiohttp.ClientSession()

        self._authorization: Optional[str] = None
        self._refresh_token: Optional[str] = None

        self._account: Optional[PDAccount] = None
        self._apartments: Dict[int, PDApartment] = {}
        self._intercoms: Dict[int, PikDomofonIntercom] = {}

        # @TODO: add other properties

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._session.__aexit__(*args)

    async def async_close(self):
        await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._session

    async def async_authenticate(self):
        async with self._session.post(
            self.BASE_PIK_URL + "/api/customers/sign_in",
            data={
                "account[phone]": self._username,
                "account[password]": self._password,
                "customer_device[uid]": self._device_id,
            },
            headers={
                "api-version": "2",
            },
        ) as request:
            authorization = request.headers.get("Authorization")
            if not authorization:
                raise PikDomofonException("Could not authorize")

            self._authorization = authorization

            resp_data = await request.json()

            account = self._account
            account_data = resp_data["account"]
            if account is None:
                account = PDAccount(
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

    @property
    def account(self) -> Optional["PDAccount"]:
        return self._account

    @property
    def is_authenticated(self) -> bool:
        return self._authorization is not None

    async def async_update_properties(self):
        if not self.is_authenticated:
            raise PikDomofonException("API not authenticated")

        async with self._session.get(
            self.BASE_PIK_URL + "/api/customers/properties",
            headers={
                "api-version": "2",
                "authorization": self._authorization,
            },
        ) as request:
            resp_data = await request.json()

            for apartment_data in resp_data.get("apartments", []):
                apartment_id = apartment_data["id"]
                try:
                    apartment = self._apartments[apartment_id]
                except KeyError:
                    self._apartments[apartment_id] = PDApartment(
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

    @property
    def apartments(self) -> Mapping[int, "PDApartment"]:
        return MappingProxyType(self._apartments)

    @property
    def intercoms(self) -> Mapping[int, "PikDomofonIntercom"]:
        return MappingProxyType(self._intercoms)

    async def async_update_property_intercoms(self, property_id: int) -> None:
        if not self.is_authenticated:
            raise PikDomofonException("API not authenticated")

        intercoms = self._intercoms
        page_number = 0
        while True:
            page_number += 1

            async with self._session.get(
                self.BASE_PIK_URL
                + f"/api/customers/properties/{property_id}/intercoms",
                headers={
                    "api-version": "2",
                    "authorization": self._authorization,
                },
                params={
                    "page": page_number,
                },
            ) as request:
                resp_data = await request.json()

                if not resp_data:
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
                        intercoms[intercom_id] = PikDomofonIntercom(
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

    async def async_intercom_unlock(self, intercom_id: int, mode: str) -> None:
        if not self.is_authenticated:
            raise PikDomofonException("API not authenticated")

        async with self._session.post(
            self.BASE_PIK_URL + f"/api/customers/intercoms/{intercom_id}/unlock",
            headers={
                "api-version": "2",
                "authorization": self._authorization,
            },
            data={
                "id": intercom_id,
                "door": mode,
            },
        ) as request:
            resp_data = await request.json()

            if resp_data.get("request") is not True:
                raise PikDomofonException("Error occurred while unlocking intercom")


@attr.s(slots=True)
class BasePDEntity:
    api: PikDomofonAPI = attr.ib()


@attr.s(slots=True)
class PDAccount(BasePDEntity):
    id: int = attr.ib()
    phone: str = attr.ib()
    email: Optional[str] = attr.ib(default=None)
    apartment_id: Optional[int] = attr.ib(default=None)
    number: Optional[str] = attr.ib(default=None)
    first_name: Optional[str] = attr.ib(default=None)
    last_name: Optional[str] = attr.ib(default=None)
    middle_name: Optional[str] = attr.ib(default=None)


@attr.s(slots=True)
class PDApartment(BasePDEntity):
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
    def intercoms(self) -> Mapping[int, "PikDomofonIntercom"]:
        return {
            intercom_id: intercom_object
            for intercom_id, intercom_object in self.api.intercoms.items()
            if intercom_object.property_id == self.id
        }  # @TODO: make into api-bound mapping


VIDEO_QUALITY_TYPES = ("high", "medium", "low")


@attr.s(slots=True)
class PikDomofonIntercom(BasePDEntity):
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
            raise PikDomofonException("Photo URL is empty")

        async with self.api.session.get(photo_url) as request:
            if request.status != 200:
                raise PikDomofonException(
                    f"Photo could not be retrieved ({request.status})"
                )

            return await request.read()
