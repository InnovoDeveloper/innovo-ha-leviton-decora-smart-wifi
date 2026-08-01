"""Leviton API."""

from collections.abc import Callable
from http import HTTPMethod
import json
import logging
from pathlib import Path
from typing import Any

import requests

from .const import API_ENDPOINT, FIRMWARE_APP_MAP, FirmwareAppID, LoginResult
from .firmware import Firmware
from .residence import Residence
from .throttle import LoginThrottle

_LOGGER = logging.getLogger(__name__)


class LevitonData:
    """LevitonData."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        """Initialize."""
        self.data = data if data is not None else {}

    @property
    def firmware(self) -> dict[str, Firmware]:
        """Firmware."""
        return self.data.get("firmware", {})

    @property
    def residences(self) -> list[Residence]:
        """Residences."""
        return self.data.get("residences", [])


class LevitonException(Exception):
    """LevitonException."""

    def __init__(self, status_code: int, name: str, message: str) -> None:
        """Initialize."""
        self.status_code = status_code
        self.name = name
        self.message = message
        super().__init__(f"[{status_code}] {name}: {message}")
        _LOGGER.error(
            "\n- LevitonException\n- Status: %s\n- Name: %s\n- Message: %s",
            self.status_code,
            self.name,
            self.message,
        )


class LevitonAPI:
    """LevitonAPI."""

    def __init__(
        self,
        authorization: str | None = None,
        save_location: str | None = None,
        user_id: str | None = None,
        email: str | None = None,
        password: str | None = None,
        code: str | None = None,
        on_token_refreshed: Callable[[str, dict[str, Any] | None], None] | None = None,
    ) -> None:
        """Initialize.

        ``email``/``password`` seed the stored credentials so that an
        expired access token can be renewed without the user having to
        reconfigure the integration. ``on_token_refreshed`` is invoked
        with the new bearer and login response whenever that happens, so
        the caller can persist them.
        """
        self.authorization = authorization
        self.save_location = save_location
        self.user_id = user_id

        self.credentials: dict = {}
        if email and password:
            self.credentials = {"email": email, "password": password}
            if code:
                self.credentials["code"] = code
        self.on_token_refreshed = on_token_refreshed
        self.login_throttle = LoginThrottle()
        self.data: LevitonData = LevitonData()
        self.session = requests.Session()
        self.user_name: str | None = None
        self.login_response: dict[str, Any] | None = None
        self._login_in_progress: bool = False

    def call(
        self,
        method: HTTPMethod,
        url: str,
        headers: dict | None = None,
        authenticated: bool = True,
        **kwargs,
    ) -> list[dict] | dict[str, Any] | None:
        """Call."""
        if headers is None:
            headers = {}
        if authenticated and self.authorization:
            headers["authorization"] = self.authorization
        _LOGGER.debug("Calling API with method: %s and URL: %s", method, url)
        response = self.refresh(
            lambda: self.session.request(
                method=method, url=f"{API_ENDPOINT}/{url}", headers=headers, **kwargs
            )
        )
        response = self.parse_response(response=response)
        self.save_response(response=response, name=url)
        return response

    def login(self, email: str, password: str, code: str | None = None) -> LoginResult:
        """Login."""
        try:
            data = {"email": email, "password": password}
            if code:
                data["code"] = code
            response = self.call(
                method=HTTPMethod.POST,
                url="person/login",
                params={"include": "user"},
                data=data,
                # Never present the old bearer here: when it is the very
                # token being replaced, the server rejects the request
                # before it looks at the credentials.
                authenticated=False,
            )
            if response and isinstance(response, dict):
                self.authorization = response["id"]
                self.user_id = response["user"]["id"]
                self.user_name = "{} {}".format(
                    response["user"]["firstName"],
                    response["user"]["lastName"],
                )
                self.login_response = response
        except LevitonException as exception:
            if all(
                [
                    exception.status_code == 401,
                    exception.message == "Login Failed",
                ]
            ):
                return LoginResult.FAILED
            if all(
                [
                    exception.status_code == 403,
                    exception.message == "Too many failed attempts",
                ]
            ):
                return LoginResult.TOO_MANY_ATTEMPTS
            if all(
                [
                    exception.status_code == 406,
                    exception.message
                    == "Insufficient Data: Person uses two factor authentication. Requires code.",
                ]
            ):
                return LoginResult.CODE_REQUIRED
            if all(
                [
                    exception.status_code == 408,
                    exception.message == "Error: Invalid code",
                ]
            ):
                return LoginResult.CODE_INVALID
            return LoginResult.FAILED
        self.credentials = data
        return LoginResult.SUCCESS

    def parse_response(self, response: requests.Response) -> dict[str, Any] | None:
        """Parse the response."""
        text = json.loads(response.text)
        if response.status_code != 200:
            error = text["error"]
            raise LevitonException(
                status_code=error.get("statusCode"),
                name=error.get("name"),
                message=error.get("message"),
            )
        return text

    def refresh(self, function: Callable) -> requests.Response:
        """Refresh login authorization, retrying once on a stale connection.

        Leviton's REST endpoint silently closes pooled keep-alive
        connections; the next request on a stale connection fails with
        ``ConnectionError``/``RemoteDisconnected`` and HA marks every
        coordinator-bound entity unavailable until the next cycle. Retry
        once after rotating the requests.Session so the client gets a
        fresh socket.
        """
        try:
            response = function()
        except requests.exceptions.ConnectionError:
            _LOGGER.debug(
                "Leviton REST connection dropped; retrying with fresh session"
            )
            self.session = requests.Session()
            response = function()
        if response.status_code == 401 and self.refresh_authorization():
            response = function()
        return response

    def refresh_authorization(self) -> bool:
        """Re-authenticate after a 401, subject to the login rate limit.

        Any 401 is treated as "this bearer is no longer good". Leviton
        has used more than one message for it -- ``Invalid Access Token``
        and ``Authorization Required`` -- so matching on the text leaves
        the integration permanently unauthenticated the moment the
        wording changes.

        Returns True only when a fresh token was obtained, meaning the
        caller may retry its request.
        """
        if self._login_in_progress:
            # Reached via the login call's own response; nothing to renew.
            return False

        if not self.credentials.get("email") or not self.credentials.get("password"):
            _LOGGER.warning(
                "Leviton rejected the access token but no stored credentials are "
                "available to re-authenticate; reconfigure the integration"
            )
            return False

        if not self.login_throttle.acquire():
            _LOGGER.warning(
                "Leviton rejected the access token; re-authentication is rate "
                "limited for another %.0fs",
                self.login_throttle.retry_after(),
            )
            return False

        _LOGGER.info("Leviton rejected the access token; re-authenticating")
        self._login_in_progress = True
        try:
            result = self.login(
                email=self.credentials["email"],
                password=self.credentials["password"],
                code=self.credentials.get("code"),
            )
        except Exception:
            self.login_throttle.record_failure()
            _LOGGER.exception("Leviton re-authentication raised")
            return False
        finally:
            self._login_in_progress = False

        if result == LoginResult.SUCCESS:
            self.login_throttle.record_success()
            _LOGGER.info("Leviton re-authentication succeeded")
            if self.on_token_refreshed and self.authorization:
                try:
                    self.on_token_refreshed(self.authorization, self.login_response)
                except Exception:
                    _LOGGER.exception("Leviton token persistence callback failed")
            return True

        self.login_throttle.record_failure(
            locked_out=result == LoginResult.TOO_MANY_ATTEMPTS
        )
        _LOGGER.error(
            "Leviton re-authentication failed (%s); next attempt permitted in %.0fs",
            result,
            self.login_throttle.retry_after(),
        )
        return False

    def save_response(
        self, response: dict[str, Any] | None, name: str = "response"
    ) -> None:
        """Save the response to a file."""
        if self.save_location and response:
            if not Path(self.save_location).is_dir():
                _LOGGER.debug("Creating directory: %s", self.save_location)
                Path(self.save_location).mkdir()
            name = name.replace("/", "_").replace(".", "_")
            file_path_name = f"{self.save_location}/{name}.json"
            _LOGGER.debug("Saving response: %s", file_path_name)
            with Path(file_path_name).open(mode="w", encoding="utf-8") as file:
                json.dump(
                    obj=response,
                    fp=file,
                    indent=4,
                    default=lambda o: "not-serializable",
                    sort_keys=True,
                )
            file.close()

    def update(self, target_residences: list[int] | None = None) -> LevitonData:
        """Update."""
        try:
            data = {}
            data["residences"] = self.get_residences(target_residences)
            data["firmware"] = self.get_firmware(data["residences"])
            self.data = LevitonData(data)
        except LevitonException:
            return self.data
        return self.data

    def get_residences(
        self, target_residences: list[int] | None = None
    ) -> list[Residence]:
        """Get residences."""
        data = []
        permissions = self.call(
            method=HTTPMethod.GET,
            url=f"person/{self.user_id}/residentialpermissions",
        )
        if permissions and isinstance(permissions, list):
            for permission in permissions:
                residential_account_id = permission["residentialAccountId"]
                residences = self.call(
                    method=HTTPMethod.GET,
                    url=f"residentialaccounts/{residential_account_id}/residences",
                )
                if residences and isinstance(residences, list):
                    for residence in residences:
                        if residence and isinstance(residence, dict):
                            residence_id = residence["id"]
                            if any(
                                [
                                    target_residences is None,
                                    target_residences
                                    and residence_id in target_residences,
                                ]
                            ):
                                residence["activities"] = self.call(
                                    method=HTTPMethod.GET,
                                    url=f"residences/{residence_id}/residentialactivities",
                                )
                                residence["devices"] = self.call(
                                    method=HTTPMethod.GET,
                                    url=f"residences/{residence_id}/iotswitches",
                                    headers={
                                        "filter": json.dumps(
                                            obj={"include": ["iotButtons"]}
                                        )
                                    },
                                )
                                residence["rooms"] = self.call(
                                    method=HTTPMethod.GET,
                                    url=f"residences/{residence_id}/residentialrooms",
                                    headers={
                                        "filter": json.dumps(
                                            obj={"include": ["residentialScenes"]}
                                        )
                                    },
                                )
                                residence["schedules"] = self.call(
                                    method=HTTPMethod.GET,
                                    url=f"residences/{residence_id}/residentialschedules",
                                )
                                data.append(Residence(self, residence))
        return data

    def get_firmware(self, residences: list[Residence]) -> dict[str, Firmware]:
        """Get firmware."""
        devices: dict[str, FirmwareAppID] = {}
        for residence in residences:
            for device in residence.devices:
                if device.model and device.model not in devices:
                    devices[device.model] = FIRMWARE_APP_MAP[device.generation]

        firmware: dict[str, Firmware] = {}
        for model, app_id in devices.items():
            app_firmware = self.call(
                method=HTTPMethod.GET,
                url="lcsapps/getfirmware",
                params={
                    "appId": app_id,
                    "model": model,
                    "data": json.dumps(
                        {
                            "condensed": False,
                        }
                    ).encode("ascii"),
                },
            )
            if app_firmware and isinstance(app_firmware, list):
                firmware[model] = Firmware(app_firmware[0])
        return firmware
