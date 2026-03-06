"""Tool for getting data from Central Bank of Russia."""

import re
import time
import httpx
import xml.etree.ElementTree as ET
import logging
from datetime import date
from typing import Optional, Tuple

from agent.exceptions import ExternalAPIError

logger = logging.getLogger(__name__)

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CBR_KEY_RATE_URL = "https://www.cbr.ru/hd_base/KeyRate/"

_RATE_CACHE_TTL = 3600

_rate_cache: Optional[Tuple[str, float]] = None
_cbr_cache: dict = {}


def get_current_rate() -> str:
    """Get current key rate from CBR website (cached for 1 hour)."""
    global _rate_cache
    now = time.monotonic()
    if _rate_cache is not None:
        value, cached_at = _rate_cache
        if now - cached_at < _RATE_CACHE_TTL:
            return value

    try:
        with httpx.Client(verify=False, timeout=10) as client:
            response = client.get(
                CBR_KEY_RATE_URL,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            response.raise_for_status()

        matches = re.findall(
            r'(\d{2}\.\d{2}\.\d{4})\s*</td>\s*<td[^>]*>\s*(\d+[,]\d+)',
            response.text,
        )
        if matches:
            rate_date, rate_str = matches[0]
            rate = float(rate_str.replace(",", "."))
            result = f"Ключевая ставка ЦБ РФ: {rate}% (с {rate_date})"
            _rate_cache = (result, now)
            return result

        alt_matches = re.findall(
            r'(\d{2}\.\d{2}\.\d{4})[^<]{0,50}?(\d{2}[,]\d{2})',
            response.text[:20000],
        )
        if alt_matches:
            rate_date, rate_str = alt_matches[0]
            rate = float(rate_str.replace(",", "."))
            result = f"Ключевая ставка ЦБ РФ: {rate}% (с {rate_date})"
            _rate_cache = (result, now)
            return result

        raise ExternalAPIError("could not parse key rate from CBR page")

    except ExternalAPIError:
        raise
    except Exception as exc:
        logger.error("error getting CBR key rate: %s", exc)
        raise ExternalAPIError(str(exc)) from exc


def get_cbr_data(target_date: Optional[date] = None) -> str:
    """Get CBR currency rates and key rate for the given date (cached for 1 hour).

    Args:
        target_date: Date to fetch rates for. Defaults to today.

    Returns:
        String with CBR rates for the requested date.
    """
    req_date = target_date if target_date is not None else date.today()
    cache_key = req_date.isoformat()
    now = time.monotonic()

    if cache_key in _cbr_cache:
        value, cached_at = _cbr_cache[cache_key]
        if now - cached_at < _RATE_CACHE_TTL:
            return value

    try:
        today_str = req_date.strftime("%d/%m/%Y")
        url = f"{CBR_DAILY_URL}?date_req={today_str}"
        with httpx.Client(verify=False, timeout=10) as client:
            response = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            response.raise_for_status()

        root = ET.fromstring(response.text)
        rate_date = root.attrib.get("Date", today_str)

        currencies = {}
        for valute in root.findall("Valute"):
            code = valute.find("CharCode").text
            name = valute.find("Name").text
            value_el = valute.find("Value")
            nominal_el = valute.find("Nominal")
            if code in ("USD", "EUR", "CNY"):
                currencies[code] = {
                    "name": name,
                    "value": value_el.text if value_el is not None else "",
                    "nominal": nominal_el.text if nominal_el is not None else "1",
                }

        result = f"Курсы валют ЦБ РФ на {rate_date}:\n"
        for code, data in currencies.items():
            result += f"  {code}: {data['value']} руб. (за {data['nominal']} {data['name']})\n"

        try:
            result += f"\n{get_current_rate()}"
        except ExternalAPIError:
            pass

        _cbr_cache[cache_key] = (result, now)
        return result

    except ExternalAPIError:
        raise
    except Exception as exc:
        logger.error("error fetching CBR data: %s", exc)
        raise ExternalAPIError(str(exc)) from exc
