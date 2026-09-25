from __future__ import annotations

import html as html_lib
import json
import logging
import re
import uuid
from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger(__name__)

BASE_URL = "https://contulmeu.reteleelectrice.ro"
LOGIN_PAGE = f"{BASE_URL}/PEDRO_SiteLogin"
AURA_URL = f"{BASE_URL}/s/sfsites/aura"
CURVE_VF_PAGE = "PED_ProxyCallWSAsync_Curve_VF"
READING_ARCHIVE_COMPONENT = "c:PED_Reading_Archive_Tab"
READING_ARCHIVE_CALLING_DESCRIPTOR = "markup://c:PED_Reading_Archive_Tab"

SAFE_DESCRIPTOR_RE = re.compile(
    r"(?:(?:apex|markup|aura)://[A-Za-z0-9_:.\-]+(?:/ACTION\$[A-Za-z0-9_]+)?)"
)
SAFE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$.:-]{0,127}$")

# Current Experience Cloud Aura identifiers. They are intentionally isolated here so
# a portal deployment can be updated without touching the collector logic.
AURA_FWUID = "TXFWNVprQUZzQnEtNXVXYTFLQ2ppdzJEa1N5enhOU3R5QWl2VzNveFZTbGcxMy4tMjE0NzQ4MzY0OC4xMzEwNzIwMA"
AURA_APP_UID = "1537_wmTAUxhOaM_47EClrN56Dw"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}


class PortalError(RuntimeError):
    pass


class AuthenticationError(PortalError):
    pass


class ReteleElectricePortal:
    def __init__(self, username: str, password: str, timeout: int = 60) -> None:
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            # Business POSTs are not retried on HTTP 5xx. A repeated
            # FindOutMeterLoadData call only hides the useful first failure.
            allowed_methods=frozenset({"GET"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.aura_token: str | None = None
        self.action_counter = 0

    def close(self) -> None:
        self.session.close()

    def login(self) -> None:
        if not self.username or not self.password:
            raise AuthenticationError("Rețele Electrice username/password are not configured")

        self.session.cookies.clear()
        self.aura_token = None
        login_url = (
            f"{LOGIN_PAGE}?startURL=%2Fs%2F"
            "&refURL=https%3A%2F%2Fcontulmeu.reteleelectrice.ro%2Fs%2F"
        )

        response = self.session.get(login_url, allow_redirects=True, timeout=self.timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        viewstate = self._extract_field(soup, "com.salesforce.visualforce.ViewState")
        viewstate_version = self._extract_field(soup, "com.salesforce.visualforce.ViewStateVersion")
        viewstate_mac = self._extract_field(soup, "com.salesforce.visualforce.ViewStateMAC")
        viewstate_csrf = self._extract_field(soup, "com.salesforce.visualforce.ViewStateCSRF")
        if not viewstate:
            raise AuthenticationError("Salesforce login ViewState not found")

        form = soup.find("form", id="loginPage:loginForm") or soup.find("form")
        form_id = form.get("id", "loginPage:loginForm") if form else "loginPage:loginForm"
        username_field = self._find_input_name(soup, ("username", "email"))
        password_field = self._find_input_name(soup, ("password", "pw"))
        submit_field = self._find_submit_name(soup)

        payload: dict[str, str] = {
            form_id: form_id,
            username_field: self.username,
            password_field: self.password,
            submit_field: submit_field,
            "com.salesforce.visualforce.ViewState": viewstate,
        }
        if viewstate_version:
            payload["com.salesforce.visualforce.ViewStateVersion"] = viewstate_version
        if viewstate_mac:
            payload["com.salesforce.visualforce.ViewStateMAC"] = viewstate_mac
        if viewstate_csrf:
            payload["com.salesforce.visualforce.ViewStateCSRF"] = viewstate_csrf

        post = self.session.post(
            login_url,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": str(response.url),
                "Cache-Control": "max-age=0",
            },
            allow_redirects=False,
            timeout=self.timeout,
        )
        post.raise_for_status()

        frontdoor_url = self._extract_frontdoor_url(post.text)
        if not frontdoor_url:
            raise AuthenticationError("Salesforce frontdoor redirect was not found")

        frontdoor = self.session.get(frontdoor_url, allow_redirects=True, timeout=self.timeout)
        frontdoor.raise_for_status()

        community = self.session.get(f"{BASE_URL}/s/", allow_redirects=True, timeout=self.timeout)
        community.raise_for_status()
        self.aura_token = self._extract_aura_token(community.text)
        if not self.aura_token:
            raise AuthenticationError("Salesforce Aura token was not found after login")

        LOG.info("Rețele Electrice login succeeded")

    def get_pods(self) -> list[str]:
        value = self._aura_call(
            descriptor="apex://PED_Utility/ACTION$getPODs",
            calling_descriptor="markup://c:PED_HomePage",
        )
        pods = sorted(self._extract_pod_values(value))
        if not pods:
            raise PortalError("No POD values were returned by the portal")
        return pods

    def get_pod_identity(self, pod: str) -> tuple[str, str]:
        # This is the controller used by the load-curve download component.
        value = self._aura_call(
            descriptor="apex://PED_Valori_di_Energia_Ctrl/ACTION$PODDetails",
            calling_descriptor="markup://c:PED_Export_Curves_For_POD_Item",
            params={"PodId": pod},
        )
        if not isinstance(value, dict) or value.get("result") not in (None, "OK"):
            # Fallback used by other meter-reading screens in the same portal.
            value = self._aura_call(
                descriptor="apex://PED_ServizidiMisuraController/ACTION$PODDetails",
                calling_descriptor="markup://c:PED_Reading_Archive_Tab",
                params={"PodId": pod},
            )
        if not isinstance(value, dict):
            raise PortalError(f"PODDetails returned an unexpected response for {pod}")

        cnp = str(value.get("cnp") or value.get("CNP") or "").strip()
        cui = str(value.get("cui") or value.get("CUI") or "").strip()
        if not cnp and not cui:
            raise PortalError(f"PODDetails did not return an account identifier for {pod}")
        return cnp, cui

    def get_component_definition(self, component_name: str) -> Any:
        return self._aura_call(
            descriptor="aura://ComponentController/ACTION$getComponentDef",
            calling_descriptor="UNKNOWN",
            params={"name": component_name},
        )

    def get_component_instance(self, component_name: str) -> Any:
        return self._aura_call(
            descriptor="aura://ComponentController/ACTION$getComponent",
            calling_descriptor="UNKNOWN",
            params={
                "name": component_name,
                "attributes": {},
                "chainLoadLabels": False,
            },
        )

    def probe_reading_archive_component(self) -> dict[str, Any]:
        """Return metadata only; never return raw component/account values."""
        definition = self.get_component_definition(READING_ARCHIVE_COMPONENT)
        instance = self.get_component_instance(READING_ARCHIVE_COMPONENT)
        return {
            "component": READING_ARCHIVE_COMPONENT,
            "calling_descriptor": READING_ARCHIVE_CALLING_DESCRIPTOR,
            "definition": summarize_component_metadata(definition),
            "instance": summarize_component_metadata(instance),
        }

    def get_load_curves(
        self,
        pod: str,
        cnp: str,
        cui: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        params = [
            pod,
            cnp,
            cui,
            start_date.strftime("%d/%m/%Y"),
            end_date.strftime("%d/%m/%Y"),
            "ALL",
        ]
        result = self._call_vf_ws_async("FindOutMeterLoadData", params)
        if not isinstance(result, dict):
            raise PortalError("Load-curve response is not a JSON object")
        if result.get("result") != "OK":
            raise PortalError(f"Load-curve request failed: {result.get('result', 'unknown result')}")
        return result

    def _aura_call(
        self,
        descriptor: str,
        calling_descriptor: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not self.aura_token:
            raise AuthenticationError("Aura token is missing; login is required")

        self.action_counter += 1
        action = {
            "id": f"{self.action_counter};a",
            "descriptor": descriptor,
            "callingDescriptor": calling_descriptor,
            "params": params or {},
            "version": None,
        }
        context = {
            "mode": "PROD",
            "fwuid": AURA_FWUID,
            "app": "siteforce:communityApp",
            "loaded": {"APPLICATION@markup://siteforce:communityApp": AURA_APP_UID},
            "dn": [],
            "globals": {},
            "uad": True,
        }
        response = self.session.post(
            AURA_URL,
            data={
                "message": json.dumps({"actions": [action]}, separators=(",", ":")),
                "aura.context": json.dumps(context, separators=(",", ":")),
                "aura.pageURI": "/s/",
                "aura.token": self.aura_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "*/*",
                "Referer": f"{BASE_URL}/s/",
                "Origin": BASE_URL,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise PortalError("Aura returned a non-JSON response") from exc
        actions = data.get("actions") or []
        if not actions:
            raise PortalError("Aura response did not contain actions")
        action_result = actions[0]
        if action_result.get("state") != "SUCCESS":
            raise PortalError(f"Aura action failed with state {action_result.get('state', 'UNKNOWN')}")
        return action_result.get("returnValue")

    def _call_vf_ws_async(self, method_name: str, method_params: list[Any]) -> Any:
        vf_url = f"{BASE_URL}/{CURVE_VF_PAGE}"
        get_response = self.session.get(vf_url, allow_redirects=True, timeout=self.timeout)
        get_response.raise_for_status()
        soup = BeautifulSoup(get_response.text, "html.parser")

        viewstate = self._extract_field(soup, "com.salesforce.visualforce.ViewState")
        if not viewstate:
            raise PortalError("Visualforce ViewState was not found")
        viewstate_version = self._extract_field(soup, "com.salesforce.visualforce.ViewStateVersion")
        viewstate_mac = self._extract_field(soup, "com.salesforce.visualforce.ViewStateMAC")
        viewstate_csrf = self._extract_field(soup, "com.salesforce.visualforce.ViewStateCSRF")

        form = soup.find("form")
        form_id = form.get("id", "j_id0:j_id2") if form else "j_id0:j_id2"
        form_action = form.get("action", f"/{CURVE_VF_PAGE}") if form else f"/{CURVE_VF_PAGE}"
        action_id = self._extract_a4j_action_id(get_response.text, form_id)

        post_data: dict[str, str] = {
            "AJAXREQUEST": "_viewRoot",
            form_id: form_id,
            "methodN": method_name,
            "params": ",".join(str(value) for value in method_params),
            "uniqueId": str(uuid.uuid4()),
            "com.salesforce.visualforce.ViewState": viewstate,
            action_id: action_id,
        }
        if viewstate_version:
            post_data["com.salesforce.visualforce.ViewStateVersion"] = viewstate_version
        if viewstate_mac:
            post_data["com.salesforce.visualforce.ViewStateMAC"] = viewstate_mac
        if viewstate_csrf:
            post_data["com.salesforce.visualforce.ViewStateCSRF"] = viewstate_csrf

        post_url = urljoin(BASE_URL, form_action)
        LOG.info("Fetching load curves from %s to %s", method_params[3], method_params[4])
        post_response = self.session.post(
            post_url,
            data=post_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "*/*",
                "Referer": vf_url,
                "Origin": BASE_URL,
            },
            timeout=max(self.timeout, 60),
        )
        if post_response.status_code >= 400:
            raise PortalError(
                f"Visualforce {method_name} returned HTTP {post_response.status_code} "
                f"for range {method_params[3]}..{method_params[4]}"
            )
        return parse_a4j_response(post_response.text)

    def _extract_aura_token(self, community_html: str) -> str | None:
        for cookie in self.session.cookies:
            if cookie.name.startswith("__Host-ERIC_PROD"):
                return cookie.value

        jwt = re.search(r"jwt=(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", community_html)
        if jwt:
            return jwt.group(1)

        cookie_name = re.search(r'"eikoocnekot"\s*:\s*"([^"]+)"', community_html)
        if cookie_name:
            value = self.session.cookies.get(cookie_name.group(1))
            if value:
                return value
        return None

    @staticmethod
    def _extract_frontdoor_url(page: str) -> str | None:
        patterns = (
            r"window\.location\.(?:replace|href)\s*[=\(]\s*['\"](https?://[^'\"]*frontdoor\.jsp[^'\"]*)['\"]",
            r"handleRedirect\(['\"](https?://[^'\"]*frontdoor\.jsp[^'\"]*)['\"]",
        )
        for pattern in patterns:
            match = re.search(pattern, page)
            if match:
                return html_lib.unescape(match.group(1))
        return None

    @staticmethod
    def _extract_field(soup: BeautifulSoup, name: str) -> str | None:
        element = soup.find("input", attrs={"name": name}) or soup.find("input", id=name)
        if element:
            return str(element.get("value", ""))
        return None

    @staticmethod
    def _find_input_name(soup: BeautifulSoup, candidates: tuple[str, ...]) -> str:
        for candidate in candidates:
            element = soup.find("input", attrs={"name": re.compile(candidate, re.I)})
            if element and element.get("name"):
                return str(element.get("name"))
            element = soup.find("input", id=re.compile(candidate, re.I))
            if element:
                return str(element.get("name") or element.get("id"))
        return f"loginPage:loginForm:{candidates[0]}"

    @staticmethod
    def _find_submit_name(soup: BeautifulSoup) -> str:
        submit = soup.find("input", attrs={"type": "submit"})
        if submit and submit.get("name"):
            return str(submit.get("name"))
        for element in soup.find_all("input"):
            name = str(element.get("name", ""))
            if "j_id" in name and element.get("value") == name:
                return name
        return "loginPage:loginForm:j_id25"

    @staticmethod
    def _extract_a4j_action_id(page: str, form_id: str) -> str:
        match = re.search(
            r"A4J\.AJAX\.Submit\s*\(\s*'[^']+'\s*,\s*null\s*,\s*\{.*?"
            r"'similarityGroupingId'\s*:\s*'([^']+)'",
            page,
            re.DOTALL,
        )
        if match:
            return match.group(1)
        match = re.search(r"'(j_id\d+:j_id\d+:j_id\d+)'", page)
        if match:
            return match.group(1)
        return f"{form_id}:j_id3"

    @classmethod
    def _extract_pod_values(cls, value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and "pod" in str(key).lower() and cls._looks_like_pod(child):
                    found.add(child.strip())
                found.update(cls._extract_pod_values(child))
        elif isinstance(value, list):
            for child in value:
                found.update(cls._extract_pod_values(child))
        elif isinstance(value, str) and cls._looks_like_pod(value):
            found.add(value.strip())
        return found

    @staticmethod
    def _looks_like_pod(value: str) -> bool:
        return bool(re.fullmatch(r"RO[0-9A-Z]{10,30}", value.strip(), re.I))


def summarize_component_metadata(value: Any) -> dict[str, Any]:
    """Extract only structural metadata safe to expose in diagnostics.

    Raw component payloads can contain account-specific values. This function
    deliberately emits only dictionary key names, Aura/Apex/markup descriptors,
    and action names derivable from those descriptors.
    """
    schema_keys: set[str] = set()
    descriptors: set[str] = set()
    action_names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key)
                if SAFE_NAME_RE.fullmatch(key_text):
                    schema_keys.add(key_text)
                walk(child)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, str):
            return

        for descriptor in SAFE_DESCRIPTOR_RE.findall(node):
            descriptors.add(descriptor)
            if "/ACTION$" in descriptor:
                action_names.add(descriptor.rsplit("/ACTION$", 1)[1])

    walk(value)
    return {
        "schema_keys": sorted(schema_keys),
        "descriptors": sorted(descriptors),
        "action_names": sorted(action_names),
    }


def parse_a4j_response(response_text: str) -> Any:
    soup = BeautifulSoup(response_text, "html.parser")
    result = soup.find(id=re.compile(r"asyncResponse$", re.I))
    if result:
        raw = result.get_text(strip=True)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise PortalError("A4J asyncResponse contained invalid JSON") from exc

    # Fallback for portal variants that only embed the result in JavaScript.
    match = re.search(r"result:\s*'((?:\\.|[^'])*)'", response_text, re.DOTALL)
    if match:
        escaped = match.group(1)
        try:
            raw = bytes(escaped, "utf-8").decode("unicode_escape")
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortalError("A4J JavaScript result could not be decoded") from exc

    raise PortalError("A4J response did not contain asyncResponse JSON")
