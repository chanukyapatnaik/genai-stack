import json
import requests
import logging
from urllib.parse import urljoin
from requests.auth import _basic_auth_str
from pathlib import Path
from uuid import uuid4

from .base import EtlBase
from .exception import LLMStackEtlException


class AirbyteConfig:
    source: dict
    destination: dict


class AirbyteEtl(EtlBase):
    """Airbyte ETL Class

    Attributes:
        name: A string to name the ETL class
        config: A string that holds the json file path which contains the configs
                required to setup airbyte connection.
        host: A string which contains the host of the airbyte
        workspace_id: An optional string which contains the workspace id of the airbyte
    """

    def __init__(self, name: str = "Airbyte", config: str = None) -> None:
        """Initializes the instances based on the name and config

        Args:
            name: A string to name the ETL class
            config: A string that holds the json file path which contains the configs
                    required to setup airbyte connection.
        """
        self.name = name
        self.config = config
        self.load_config()

    @staticmethod
    def _read_json_file(file_path: str):
        with open(file_path) as file:
            data = json.load(file)
        return data

    def load_config(self):
        """Loads the configs and can set as class attrs"""
        logging.info("Loading Configs")
        f = Path(self.config)

        if not f.exists():
            raise LLMStackEtlException(
                f"Unable to find the file. Input given - {self.config}",
            )

        try:
            f = self._read_json_file(f.absolute())
            self.config_dict = f
            self.host = self.config_dict.get("host") or "http://localhost:8000/"
            self.workspace_id = self.config_dict.get("workspace_id") or self._create_workspace_id()  # noqa: E501
        except json.JSONDecodeError as e:
            raise LLMStackEtlException("Unable to read the config file.") from e

    @property
    def _auth_header(self):
        header = {}
        auth_dict = self.config_dict.get("auth", {})

        if api_key := auth_dict.get("api-key"):
            header["Authorization"] = f"Bearer {api_key}".strip()
        elif auth_dict.get("username") and auth_dict.get("password"):
            encoded_auth = _basic_auth_str(
                username=auth_dict.get("username"),
                password=auth_dict.get("password"),
            )
            header["Authorization"] = encoded_auth
        else:
            raise LLMStackEtlException(
                "No Auth provided for Airbyte. Either api-key or username, password should be provided in the config.json"  # noqa: E501
            )
        return header

    @property
    def _headers(self):
        return self._auth_header

    def _create_source(self):
        json_resp = self._config_dict_extraction(
            "source",
            "/api/v1/sources/create",
            "sourceDefinitionId",
        )
        self.source_id = json_resp.get("sourceId")
        return json_resp

    def _create_destination(self):
        json_resp = self._config_dict_extraction(
            "destination", "/api/v1/destinations/create", "destinationDefinitionId"
        )
        self.destination_id = json_resp.get("destinationId")
        return json_resp

    def _config_dict_extraction(self, arg0, arg1, arg2):
        source: dict = self.config_dict.get(arg0)
        response = requests.post(
            url=urljoin(f"{self.host}", arg1),
            headers=self._headers,
            json={
                "name": source.get("name"),
                arg2: source.get(arg2),
                "workspaceId": self.workspace_id,
                "connectionConfiguration": source.get("configs"),
            },
        )
        if not response.ok:
            raise LLMStackEtlException(f"Exception: {response.text}")
        return response.json()

    def _create_connection(self):
        payload = {
            "prefix": "genai_stack",
            "sourceId": self.source_id,
            "destinationId": self.destination_id,
            "status": "active",
        }
        response = requests.post(
            url=urljoin(self.host, "/api/v1/connections/create"),
            headers=self._headers,
            json=payload,
        )

        if not response.ok:
            raise LLMStackEtlException(f"Exception: {response.text}")

        json_response = response.json()
        self.connection_id = json_response["connectionId"]
        print(f"Connection was created - {self.connection_id}")
        return json_response

    def _create_workspace_id(self):
        """If a workspace_id is not provided in the config.json, it will be created."""
        payload = {"name": uuid4().hex}
        response = requests.post(
            url=urljoin(self.host, "/api/v1/workspaces/create"),
            headers=self._headers,
            json=payload,
        )
        if not response.ok:
            raise LLMStackEtlException(f"Exception: Unable to create a workspace.\n{response.text}")  # noqa: E501
        print(f'Created Workspace - {response.json().get("workspaceId")}')
        return response.json().get("workspaceId")

    def source_definitions_list(self):
        response = requests.post(
            url=urljoin(self.host, "/api/v1/source_definitions/list"),
            headers=self._headers,
            json={},
        )
        if response.ok:
            return response.json().get("sourceDefinitions")
        else:
            raise LLMStackEtlException(f"Exception: {response.text}")

    def destination_definitions_list(self):
        response = requests.post(
            url=urljoin(self.host, "/api/v1/destination_definitions/list"),
            headers=self._headers,
            json={},
        )
        if response.ok:
            return response.json().get("sourceDefinitions")
        else:
            raise LLMStackEtlException(f"Exception: {response.text}")

    def run(self):
        self._create_source()
        self._create_destination()
        self._create_connection()
