"""Conservative US eligibility check for public location labels.

This is a README projection rule. The source location stays unchanged in SQLite
and JSON; an unknown place is not silently treated as a US workplace.
"""
from __future__ import annotations

import re

STATES = frozenset("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN
MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split())
STATE_NAMES = frozenset("""Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia""".split("|"))
# Bare city labels occur in ATS feeds. Keep this list small and unambiguous.
US_CITIES = frozenset({"san francisco", "sunnyvale", "new york city", "new york", "palo alto", "mountain view", "seattle", "boston", "chicago", "austin", "denver", "atlanta", "washington dc"})
FOREIGN_COUNTRIES = frozenset("""Australia|Austria|Belgium|Brazil|Canada|China|Colombia|Denmark|Estonia|France|Germany|India|Ireland|Israel|Italy|Japan|Mexico|Netherlands|New Zealand|Poland|Portugal|Singapore|South Korea|Spain|Sweden|Switzerland|United Kingdom|UK""".split("|"))


def is_us_location(location: str) -> bool:
    value = " ".join(location.strip().split())
    if not value:
        return False
    return any(_segment_is_us(segment.strip()) for segment in re.split(r"\s*[;|•]\s*", value))


def _segment_is_us(value: str) -> bool:
    if re.search(r"\b(?:united states(?: of america)?|usa|u\.s\.a?\.|us)\b", value, re.I):
        return True
    if re.search(r"remote\s*\(any state\)", value, re.I):
        return True
    if re.search(r"\bUS-[A-Z]{2}(?:-|\b)", value):
        return True
    # A city abroad can share a US state abbreviation (e.g. Perth, WA, Australia).
    if any(re.search(r"\b" + re.escape(name) + r"\b", value, re.I) for name in FOREIGN_COUNTRIES):
        return False
    if any(re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", value, re.I) for name in STATE_NAMES):
        return True
    if any(re.search(r",\s*" + code + r"(?:\s*[,;|•/)]|\s*$)", value) for code in STATES):
        return True
    return value.casefold().strip(" ,.-") in US_CITIES
