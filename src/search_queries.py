from __future__ import annotations

import re


MAX_EXPANDED_QUERIES = 10
HYBRID_QUERY_RE = re.compile(r"\b(?:plug[ -]?in(?:[ -]+hybrid)?|hybrid|hev|phev|huv)\b", re.I)
PLUGIN_RE = re.compile(r"\b(?:phev|plug[ -]?in(?:[ -]+hybrid)?)\b", re.I)
MAKES = tuple(sorted((
    "alfa romeo", "aston martin", "land rover", "mercedes benz", "mercedes",
    "acura", "audi", "bentley", "bmw", "buick", "byd", "cadillac", "chevrolet",
    "chevy", "chrysler", "citroen", "dacia", "dodge", "fiat", "ford", "genesis",
    "gmc", "honda", "hyundai", "infiniti", "jaguar", "jeep", "kia", "lexus",
    "lincoln", "mazda", "mini", "mitsubishi", "nissan", "opel", "peugeot",
    "polestar", "pontiac", "porsche", "ram", "renault", "saab", "saturn", "seat",
    "skoda", "smart", "subaru", "suzuki", "tesla", "toyota", "vauxhall",
    "volkswagen", "volvo", "vw",
), key=len, reverse=True))
MAKE_ALIASES = {
    "chevrolet": ("chevy",), "chevy": ("chevrolet",),
    "volkswagen": ("vw",), "vw": ("volkswagen",),
    "mercedes benz": ("mercedes",), "mercedes": ("mercedes benz",),
}


def hybrid_requested(query: str, powertrain_any: list[str]) -> bool:
    return bool(HYBRID_QUERY_RE.search(query) or any(
        HYBRID_QUERY_RE.fullmatch(value.strip()) for value in powertrain_any
    ))


def model_query(query: str, hybrid: bool) -> str:
    return " ".join((HYBRID_QUERY_RE.sub("", query) if hybrid else query).split()).lower()


def split_make(query: str) -> tuple[str, str]:
    normalized = " ".join(re.findall(r"[a-z0-9]+", query.lower()))
    for make in MAKES:
        if normalized == make:
            return make, ""
        if normalized.startswith(make + " "):
            return make, normalized[len(make):].strip()
        compact_make = make.replace(" ", "")
        if normalized.startswith(compact_make) and len(normalized) > len(compact_make):
            return make, normalized[len(compact_make):].strip()
    return "", normalized


def expand_queries(query: str, configured: list[str], powertrain_any: list[str]) -> list[str]:
    queries: list[str] = []
    keys: set[str] = set()

    def add(value: str, *, explicit: bool = False) -> None:
        value = " ".join(value.split())
        key = value.lower()
        if value and key not in keys and (explicit or len(queries) < MAX_EXPANDED_QUERIES):
            queries.append(value)
            keys.add(key)

    # Explicit aliases remain authoritative; only automatic expansion is bounded.
    for value in [*configured, query]:
        add(value or "", explicit=True)
    hybrid = hybrid_requested(query, powertrain_any)
    base = model_query(query, hybrid)
    make, model = split_make(base)
    if not model:
        return queries
    body = f"{make} {model}".strip()
    omit_make = bool(make and re.search(r"[a-z]", model))
    suffix = " phev" if PLUGIN_RE.search(query) else " hybrid" if hybrid else ""
    add(body + suffix)
    if omit_make:
        add(model + suffix)
    if hybrid:
        add(body)
        if omit_make:
            add(model)
    add(re.sub(r"[^a-z0-9]", "", body) + suffix)
    compact_model = re.sub(r"[^a-z0-9]", "", model)
    add(f"{make} {compact_model}".strip() + suffix)
    if omit_make:
        add(compact_model + suffix)
    for alias in MAKE_ALIASES.get(make, ()):
        add(f"{alias} {model}" + suffix)

    # Common model-number spellings: F150 / F 150 / F-150, CX5 / CX 5 / CX-5.
    spaced_model = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", model)
    spaced_model = re.sub(r"^([a-z]{2})v$", r"\1 v", spaced_model)
    for spelling in dict.fromkeys((spaced_model, spaced_model.replace(" ", "-"))):
        add(f"{make} {spelling}".strip() + suffix)
        if omit_make:
            add(spelling + suffix)
    if hybrid:
        aliases = ("phev", "plug-in hybrid") if PLUGIN_RE.search(query) else ("hev", "phev", "huv")
        for alias in aliases:
            add(f"{body} {alias}")
        if omit_make:
            for alias in aliases:
                add(f"{model} {alias}")
    return queries
