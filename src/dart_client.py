import io
import zipfile

import requests

from config.settings import get_dart_api_key


BASE_URL = "https://opendart.fss.or.kr/api"


def get_corp_code_file():
    url = f"{BASE_URL}/corpCode.xml"

    params = {
        "crtfc_key": get_dart_api_key(),
    }

    response = requests.get(
        url,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    return response.content


def extract_corp_code_xml(zip_content):
    with zipfile.ZipFile(io.BytesIO(zip_content)) as zip_file:
        xml_content = zip_file.read("CORPCODE.xml")

    return xml_content

