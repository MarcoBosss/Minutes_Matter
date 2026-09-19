#!/usr/bin/env python3
"""
Minutes Matter - Environmental Data Collector

Given a latitude and longitude, this script collects data from:
1. Open-Meteo
2. USGS Earthquake Catalog
3. Nepal DHM realtime stream-flow page (best effort)
4. Copernicus GloFAS (optional credentials)
5. NASA IMERG Early Run (optional credentials)

It writes a single JSON file.

Examples:
    python collector.py --lat 28.2774 --lon 85.3777
    python collector.py --lat 28.2774 --lon 85.3777 --output rasuwagadhi.json
    python collector.py --lat 28.2774 --lon 85.3777 --skip-glofas --skip-imerg
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

USER_AGENT = "MinutesMatter-Hackathon/1.0"
TIMEOUT = 25


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: Optional[datetime] = None) -> str:
    return (dt or now_utc()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def result_ok(source: str, data: Any, note: Optional[str] = None) -> Dict[str, Any]:
    out = {
        "source": source,
        "status": "ok",
        "retrieved_at": iso_utc(),
        "data": data,
    }
    if note:
        out["note"] = note
    return out


def result_error(source: str, error: Exception | str, status: str = "error", data: Any = None) -> Dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "retrieved_at": iso_utc(),
        "error": str(error),
        "data": data,
    }


def get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = TIMEOUT):
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Open-Meteo
# ---------------------------------------------------------------------------

def fetch_open_meteo(lat: float, lon: float) -> Dict[str, Any]:
    source = "open_meteo"
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join([
                "temperature_2m",
                "precipitation",
                "rain",
                "snowfall",
                "weather_code",
                "wind_speed_10m",
                "wind_gusts_10m",
            ]),
            "hourly": ",".join([
                "precipitation",
                "rain",
                "snowfall",
                "soil_moisture_0_to_1cm",
                "soil_moisture_1_to_3cm",
                "freezing_level_height",
                "temperature_2m",
            ]),
            "past_days": 1,
            "forecast_days": 2,
            "timezone": "UTC",
        }

        raw = get_json(url, params=params)

        # Keep about 24h history + 24h forecast.
        hourly = raw.get("hourly", {})
        keep_idx: List[int] = []
        now = now_utc()
        for i, t in enumerate(hourly.get("time", [])):
            try:
                dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
                if now - timedelta(hours=24) <= dt <= now + timedelta(hours=24):
                    keep_idx.append(i)
            except Exception:
                pass

        trimmed = {}
        for key, values in hourly.items():
            if isinstance(values, list) and keep_idx:
                trimmed[key] = [values[i] for i in keep_idx if i < len(values)]
            else:
                trimmed[key] = values

        data = {
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "elevation_m": raw.get("elevation"),
            "timezone": raw.get("timezone"),
            "current_units": raw.get("current_units"),
            "current": raw.get("current"),
            "hourly_units": raw.get("hourly_units"),
            "hourly_48h_window": trimmed,
        }
        return result_ok(source, data)
    except Exception as e:
        return result_error(source, e)


# ---------------------------------------------------------------------------
# USGS earthquakes
# ---------------------------------------------------------------------------

def fetch_usgs(lat: float, lon: float, radius_km: float = 250.0, lookback_hours: int = 72) -> Dict[str, Any]:
    source = "usgs_earthquakes"
    try:
        url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
        params = {
            "format": "geojson",
            "latitude": lat,
            "longitude": lon,
            "maxradiuskm": radius_km,
            "starttime": (now_utc() - timedelta(hours=lookback_hours)).isoformat(),
            "orderby": "time",
            "limit": 100,
        }
        raw = get_json(url, params=params)

        events = []
        for feature in raw.get("features", []):
            props = feature.get("properties", {})
            coords = ((feature.get("geometry") or {}).get("coordinates") or [None, None, None])

            event_time = None
            ts = props.get("time")
            if isinstance(ts, (int, float)):
                event_time = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")

            events.append({
                "id": feature.get("id"),
                "magnitude": props.get("mag"),
                "place": props.get("place"),
                "time": event_time,
                "longitude": coords[0] if len(coords) > 0 else None,
                "latitude": coords[1] if len(coords) > 1 else None,
                "depth_km": coords[2] if len(coords) > 2 else None,
                "type": props.get("type"),
                "url": props.get("url"),
            })

        mags = [e["magnitude"] for e in events if isinstance(e.get("magnitude"), (int, float))]
        return result_ok(source, {
            "radius_km": radius_km,
            "lookback_hours": lookback_hours,
            "event_count": len(events),
            "max_magnitude": max(mags) if mags else None,
            "events": events[:25],
        })
    except Exception as e:
        return result_error(source, e)


# ---------------------------------------------------------------------------
# Nepal DHM realtime stream page
# ---------------------------------------------------------------------------

def _clean_column_name(value: Any) -> str:
    s = re.sub(r"\s+", " ", str(value)).strip().lower()
    return s


def fetch_nepal_dhm(keyword: str = "Rasuwa", max_rows: int = 25) -> Dict[str, Any]:
    """
    Best-effort parser for Nepal DHM's public realtime stream-flow table.

    Important:
    DHM's page is a webpage, not a stable documented JSON API. This function
    intentionally fails gracefully if the table layout changes.
    """
    source = "nepal_dhm"
    url = "https://dhm.gov.np/hydrology/realtime-stream"

    try:
        import pandas as pd

        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))

        if not tables:
            raise RuntimeError("No HTML tables found on DHM realtime-stream page.")

        chosen = None
        for table in tables:
            cols = [_clean_column_name(c) for c in table.columns]
            joined = " | ".join(cols)
            if "station" in joined and ("water level" in joined or "discharge" in joined):
                chosen = table.copy()
                break

        if chosen is None:
            raise RuntimeError("Could not identify a realtime stream table on the DHM page.")

        chosen.columns = [_clean_column_name(c) for c in chosen.columns]

        kw = keyword.strip().lower()
        if kw:
            mask = chosen.astype(str).apply(
                lambda col: col.str.lower().str.contains(re.escape(kw), na=False)
            ).any(axis=1)
            matched = chosen[mask].copy()
        else:
            matched = chosen.copy()

        matched_found = len(matched) > 0
        output = matched if matched_found else chosen.head(max_rows)

        rows = []
        for _, row in output.head(max_rows).iterrows():
            item = {}
            for k, v in row.to_dict().items():
                if hasattr(v, "item"):
                    try:
                        v = v.item()
                    except Exception:
                        pass
                if isinstance(v, float) and math.isnan(v):
                    v = None
                item[str(k)] = v
            rows.append(item)

        note = None
        if not matched_found:
            note = (
                f"No DHM row matched keyword={keyword!r}; returning a small table sample. "
                "Set --dhm-keyword to an exact station/district/basin once you identify it."
            )

        return result_ok(source, {
            "page": url,
            "keyword": keyword,
            "keyword_match_found": matched_found,
            "rows": rows,
        }, note=note)

    except Exception as e:
        return result_error(source, e, status="unavailable")


# ---------------------------------------------------------------------------
# Copernicus GloFAS (optional)
# ---------------------------------------------------------------------------

def _first_data_var(ds):
    variables = list(ds.data_vars)
    if not variables:
        raise RuntimeError("GloFAS response contains no data variables.")
    return variables[0]


def _find_coord(ds, names: Iterable[str]) -> Optional[str]:
    for name in names:
        if name in ds.coords:
            return name
    return None


def fetch_glofas(lat: float, lon: float) -> Dict[str, Any]:
    """
    Optional authenticated GloFAS fetch.

    Requires:
      - cdsapi
      - xarray
      - cfgrib
      - eccodes
      - ~/.cdsapirc configured
      - accepted GloFAS dataset terms
    """
    source = "copernicus_glofas"

    try:
        import cdsapi
        import xarray as xr

        padding = 0.20
        area = [lat + padding, lon - padding, lat - padding, lon + padding]

        dates = [now_utc().date(), (now_utc() - timedelta(days=1)).date()]
        last_error = None

        for d in dates:
            try:
                request = {
                    "system_version": "operational",
                    "hydrological_model": "lisflood",
                    "product_type": "control_forecast",
                    "variable": "river_discharge_in_the_last_24_hours",
                    "year": f"{d.year:04d}",
                    "month": f"{d.month:02d}",
                    "day": f"{d.day:02d}",
                    "leadtime_hour": ["24", "48", "72"],
                    "area": area,
                    "data_format": "grib2",
                    "download_format": "unarchived",
                }

                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "glofas.grib2"

                    client = cdsapi.Client(quiet=True)
                    client.retrieve("cems-glofas-forecast", request).download(str(target))

                    ds = xr.open_dataset(
                        target,
                        engine="cfgrib",
                        backend_kwargs={"indexpath": ""},
                    )

                    lat_name = _find_coord(ds, ["latitude", "lat"])
                    lon_name = _find_coord(ds, ["longitude", "lon"])
                    var = _first_data_var(ds)

                    point = ds
                    if lat_name and lon_name:
                        point = ds.sel({lat_name: lat, lon_name: lon}, method="nearest")

                    da = point[var]

                    try:
                        import numpy as np
                        flat = np.asarray(da.values).reshape(-1)
                        values = [
                            None if not np.isfinite(v) else float(v)
                            for v in flat[:20]
                        ]
                    except Exception:
                        values = [str(da.values)]

                    data = {
                        "forecast_initialization_date": d.isoformat(),
                        "requested_area_nwse": area,
                        "variable": var,
                        "units": da.attrs.get("units"),
                        "values": values,
                    }
                    ds.close()
                    return result_ok(source, data)

            except Exception as e:
                last_error = e

        raise last_error or RuntimeError("GloFAS retrieval failed.")

    except Exception as e:
        msg = str(e).lower()
        status = "error"
        if any(term in msg for term in ["cdsapirc", "token", "credential", "terms"]):
            status = "not_configured"
        return result_error(source, e, status=status)


# ---------------------------------------------------------------------------
# NASA IMERG Early Run (optional)
# ---------------------------------------------------------------------------

def _choose_cmr_download(entry: Dict[str, Any]) -> Optional[str]:
    candidates = []
    for link in entry.get("links", []) or []:
        href = link.get("href")
        if not href or not href.startswith("http"):
            continue

        text = " ".join([
            href,
            str(link.get("rel", "")),
            str(link.get("title", "")),
            str(link.get("type", "")),
        ]).lower()

        score = 0
        if ".hdf5" in href.lower():
            score += 10
        if "data#" in str(link.get("rel", "")).lower():
            score += 10
        if "opendap" in text:
            score -= 10
        if "browse" in text:
            score -= 10

        candidates.append((score, href))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _nearest_index(values, target: float) -> int:
    import numpy as np
    arr = np.asarray(values, dtype=float)
    return int(np.nanargmin(np.abs(arr - target)))


def fetch_imerg(lat: float, lon: float) -> Dict[str, Any]:
    """
    Optional authenticated NASA IMERG Early Run fetch.

    Set:
        NASA_EARTHDATA_TOKEN=...

    The script:
    1. discovers the newest IMERG Early Run granule through NASA CMR
    2. downloads the HDF5 file
    3. reads precipitation at the nearest grid cell
    """
    source = "nasa_imerg"

    try:
        import h5py
        import numpy as np

        # GPM_3IMERGHHE.07 at GES DISC
        collection_concept_id = "C2723758340-GES_DISC"

        cmr = get_json(
            "https://cmr.earthdata.nasa.gov/search/granules.json",
            params={
                "collection_concept_id": collection_concept_id,
                "sort_key": "-start_date",
                "page_size": 1,
            },
        )

        entries = ((cmr.get("feed") or {}).get("entry") or [])
        if not entries:
            raise RuntimeError("NASA CMR returned no IMERG Early Run granules.")

        entry = entries[0]
        granule_id = entry.get("title") or entry.get("producer_granule_id")
        time_start = entry.get("time_start")
        time_end = entry.get("time_end")
        download_url = _choose_cmr_download(entry)

        if not download_url:
            raise RuntimeError("Could not find a downloadable IMERG HDF5 link.")

        token = os.getenv("NASA_EARTHDATA_TOKEN", "").strip()
        if not token:
            return result_error(
                source,
                "NASA_EARTHDATA_TOKEN is not set.",
                status="not_configured",
                data={
                    "granule_id": granule_id,
                    "time_start": time_start,
                    "time_end": time_end,
                    "download_url_discovered": download_url,
                },
            )

        r = requests.get(
            download_url,
            headers={
                "User-Agent": USER_AGENT,
                "Authorization": f"Bearer {token}",
            },
            timeout=90,
            allow_redirects=True,
        )
        r.raise_for_status()

        with h5py.File(io.BytesIO(r.content), "r") as f:
            if "/Grid/lat" in f:
                lats = f["/Grid/lat"][:]
            elif "/Grid/latitude" in f:
                lats = f["/Grid/latitude"][:]
            else:
                raise RuntimeError("IMERG file does not contain latitude grid.")

            if "/Grid/lon" in f:
                lons = f["/Grid/lon"][:]
            elif "/Grid/longitude" in f:
                lons = f["/Grid/longitude"][:]
            else:
                raise RuntimeError("IMERG file does not contain longitude grid.")

            if "/Grid/precipitation" not in f:
                raise RuntimeError("IMERG file does not contain /Grid/precipitation.")

            lat_idx = _nearest_index(lats, lat)
            lon_idx = _nearest_index(lons, lon)

            ds = f["/Grid/precipitation"]
            shape = ds.shape

            # Typical IMERG V07 layout is [time, lon, lat].
            if len(shape) != 3:
                raise RuntimeError(f"Unexpected IMERG precipitation shape: {shape}")

            if shape[1] == len(lons) and shape[2] == len(lats):
                value = ds[0, lon_idx, lat_idx]
            elif shape[1] == len(lats) and shape[2] == len(lons):
                value = ds[0, lat_idx, lon_idx]
            else:
                raise RuntimeError(
                    f"Could not map IMERG dimensions {shape} to lon={len(lons)}, lat={len(lats)}"
                )

            value = float(value)
            if value < 0 or not np.isfinite(value):
                value = None

            units = ds.attrs.get("units", "mm/hr")
            if isinstance(units, bytes):
                units = units.decode("utf-8", "replace")

            return result_ok(source, {
                "granule_id": granule_id,
                "time_start": time_start,
                "time_end": time_end,
                "grid_latitude": float(lats[lat_idx]),
                "grid_longitude": float(lons[lon_idx]),
                "precipitation_rate": value,
                "units": str(units),
            })

    except Exception as e:
        msg = str(e).lower()
        status = "error"
        if any(term in msg for term in ["401", "403", "token", "earthdata"]):
            status = "not_configured"
        return result_error(source, e, status=status)



# ---------------------------------------------------------------------------
# Foto-Webcam.eu live glacier image
# ---------------------------------------------------------------------------

FOTO_WEBCAM_PRESETS = {
    "hintereisferner1": {
        "name": "Hintereisferner 1",
        "latitude": 46.7959,
        "longitude": 10.7828,
        "elevation_m": 3245,
        "direction_degrees": 270,
        "page_url": "https://www.foto-webcam.eu/webcam/hintereisferner1/",
        "attribution": "www.foto-webcam.eu",
    }
}


def fetch_glacier_webcam(
    camera_name: str = "hintereisferner1",
    width: int = 720,
    image_dir: str = "images",
) -> Dict[str, Any]:
    """
    Download the current Foto-Webcam.eu image.

    The website documents stable current-image URLs in this form:
        https://www.foto-webcam.eu/webcam/<camera>/current/<width>.jpg

    Supported documented widths:
        150, 180, 240, 320, 400, 640, 720

    This function stores:
      - a timestamped snapshot for time-series comparison
      - a *_latest.jpg copy for easy frontend access

    Note: this webcam is in the Austrian Alps, not Nepal. It is useful as a
    real glacier-vision input for the prototype, but it should not be presented
    as visual evidence for the Nepal target coordinate.
    """
    source = "foto_webcam_glacier"

    try:
        allowed_widths = {150, 180, 240, 320, 400, 640, 720}
        if width not in allowed_widths:
            raise ValueError(
                f"Unsupported webcam width {width}. "
                f"Use one of {sorted(allowed_widths)}."
            )

        preset = FOTO_WEBCAM_PRESETS.get(camera_name, {})
        page_url = preset.get(
            "page_url",
            f"https://www.foto-webcam.eu/webcam/{camera_name}/",
        )
        image_url = (
            f"https://www.foto-webcam.eu/webcam/"
            f"{camera_name}/current/{width}.jpg"
        )

        r = requests.get(
            image_url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        r.raise_for_status()

        content_type = (r.headers.get("Content-Type") or "").lower()
        if "image" not in content_type and not r.content.startswith(b"\xff\xd8"):
            raise RuntimeError(
                f"Webcam response did not look like an image "
                f"(Content-Type={content_type!r})."
            )

        out_dir = Path(image_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
        timestamped = out_dir / f"{camera_name}_{stamp}.jpg"
        latest = out_dir / f"{camera_name}_latest.jpg"

        timestamped.write_bytes(r.content)
        latest.write_bytes(r.content)

        data = {
            "camera_id": camera_name,
            "camera_name": preset.get("name", camera_name),
            "camera_location": {
                "latitude": preset.get("latitude"),
                "longitude": preset.get("longitude"),
                "elevation_m": preset.get("elevation_m"),
                "direction_degrees": preset.get("direction_degrees"),
            },
            "webcam_page": page_url,
            "image_url": image_url,
            "width_px": width,
            "downloaded_at": iso_utc(),
            "http_last_modified": r.headers.get("Last-Modified"),
            "timestamped_image_path": str(timestamped),
            "latest_image_path": str(latest),
            "bytes": len(r.content),
            "content_type": r.headers.get("Content-Type"),
            "attribution": preset.get(
                "attribution",
                "www.foto-webcam.eu",
            ),
            "important_note": (
                "This webcam is in the Austrian Alps and is not located at "
                "the latitude/longitude supplied to the environmental collector."
            ),
        }
        return result_ok(source, data)

    except Exception as e:
        return result_error(source, e)


# ---------------------------------------------------------------------------
# Compact payload for Gemini / frontend
# ---------------------------------------------------------------------------

def compact_observations(sources: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "weather": {},
        "seismic": {},
        "river": {},
        "glofas": {},
        "satellite_precipitation": {},
        "glacier_webcam": {},
    }

    om = sources.get("open_meteo", {})
    if om.get("status") == "ok":
        current = ((om.get("data") or {}).get("current") or {})
        out["weather"] = {
            "time": current.get("time"),
            "temperature_c": current.get("temperature_2m"),
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "snowfall_cm": current.get("snowfall"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_gusts_kmh": current.get("wind_gusts_10m"),
        }

    usgs = sources.get("usgs_earthquakes", {})
    if usgs.get("status") == "ok":
        data = usgs.get("data") or {}
        out["seismic"] = {
            "event_count": data.get("event_count"),
            "max_magnitude": data.get("max_magnitude"),
            "events": (data.get("events") or [])[:5],
        }

    dhm = sources.get("nepal_dhm", {})
    if dhm.get("status") == "ok":
        data = dhm.get("data") or {}
        out["river"] = {
            "keyword": data.get("keyword"),
            "keyword_match_found": data.get("keyword_match_found"),
            "rows": data.get("rows"),
        }

    gf = sources.get("copernicus_glofas", {})
    if gf.get("status") == "ok":
        data = gf.get("data") or {}
        out["glofas"] = {
            "forecast_initialization_date": data.get("forecast_initialization_date"),
            "variable": data.get("variable"),
            "units": data.get("units"),
            "values": data.get("values"),
        }

    im = sources.get("nasa_imerg", {})
    if im.get("status") == "ok":
        data = im.get("data") or {}
        out["satellite_precipitation"] = {
            "time_start": data.get("time_start"),
            "time_end": data.get("time_end"),
            "grid_latitude": data.get("grid_latitude"),
            "grid_longitude": data.get("grid_longitude"),
            "precipitation_rate": data.get("precipitation_rate"),
            "units": data.get("units"),
        }

    webcam = sources.get("foto_webcam_glacier", {})
    if webcam.get("status") == "ok":
        data = webcam.get("data") or {}
        out["glacier_webcam"] = {
            "camera_id": data.get("camera_id"),
            "camera_name": data.get("camera_name"),
            "camera_location": data.get("camera_location"),
            "downloaded_at": data.get("downloaded_at"),
            "http_last_modified": data.get("http_last_modified"),
            "latest_image_path": data.get("latest_image_path"),
            "image_url": data.get("image_url"),
            "attribution": data.get("attribution"),
            "important_note": data.get("important_note"),
        }

    return out


def collect(
    lat: float,
    lon: float,
    dhm_keyword: str,
    usgs_radius_km: float,
    usgs_hours: int,
    skip_dhm: bool,
    skip_glofas: bool,
    skip_imerg: bool,
    skip_webcam: bool = False,
    webcam_name: str = "hintereisferner1",
    webcam_width: int = 720,
    image_dir: str = "images",
) -> Dict[str, Any]:

    sources: Dict[str, Any] = {}

    print("[1/6] Open-Meteo")
    sources["open_meteo"] = fetch_open_meteo(lat, lon)

    print("[2/6] USGS")
    sources["usgs_earthquakes"] = fetch_usgs(
        lat,
        lon,
        radius_km=usgs_radius_km,
        lookback_hours=usgs_hours,
    )

    if skip_dhm:
        sources["nepal_dhm"] = result_error("nepal_dhm", "Skipped", status="skipped")
    else:
        print("[3/6] Nepal DHM")
        sources["nepal_dhm"] = fetch_nepal_dhm(dhm_keyword)

    if skip_glofas:
        sources["copernicus_glofas"] = result_error("copernicus_glofas", "Skipped", status="skipped")
    else:
        print("[4/6] Copernicus GloFAS")
        sources["copernicus_glofas"] = fetch_glofas(lat, lon)

    if skip_imerg:
        sources["nasa_imerg"] = result_error("nasa_imerg", "Skipped", status="skipped")
    else:
        print("[5/6] NASA IMERG")
        sources["nasa_imerg"] = fetch_imerg(lat, lon)

    if skip_webcam:
        sources["foto_webcam_glacier"] = result_error(
            "foto_webcam_glacier", "Skipped", status="skipped"
        )
    else:
        print("[6/6] Foto-Webcam.eu glacier image")
        sources["foto_webcam_glacier"] = fetch_glacier_webcam(
            camera_name=webcam_name,
            width=webcam_width,
            image_dir=image_dir,
        )

    return {
        "schema_version": "1.0",
        "generated_at": iso_utc(),
        "target": {
            "latitude": lat,
            "longitude": lon,
        },
        "sources": sources,
        "observations_for_gemini": compact_observations(sources),
        "disclaimer": (
            "Hackathon prototype only. Environmental/model observations are not a "
            "validated disaster prediction or public-warning product."
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Collect environmental data for a latitude/longitude and write JSON."
    )
    parser.add_argument("--lat", type=float, required=True, help="Latitude, e.g. 28.2774")
    parser.add_argument("--lon", type=float, required=True, help="Longitude, e.g. 85.3777")
    parser.add_argument("--output", default="environment_state.json", help="Output JSON filename")
    parser.add_argument(
        "--dhm-keyword",
        default=os.getenv("DHM_STATION_KEYWORD", "Rasuwa"),
        help="Keyword used to filter Nepal DHM table",
    )
    parser.add_argument("--usgs-radius-km", type=float, default=250.0)
    parser.add_argument("--usgs-hours", type=int, default=72)
    parser.add_argument("--skip-dhm", action="store_true")
    parser.add_argument("--skip-glofas", action="store_true")
    parser.add_argument("--skip-imerg", action="store_true")
    parser.add_argument("--skip-webcam", action="store_true")
    parser.add_argument(
        "--webcam-name",
        default="hintereisferner1",
        help="Foto-Webcam.eu camera ID (default: hintereisferner1)",
    )
    parser.add_argument(
        "--webcam-width",
        type=int,
        default=720,
        choices=[150, 180, 240, 320, 400, 640, 720],
        help="Downloaded webcam width in pixels",
    )
    parser.add_argument(
        "--image-dir",
        default="images",
        help="Directory for downloaded webcam images",
    )

    args = parser.parse_args()

    payload = collect(
        lat=args.lat,
        lon=args.lon,
        dhm_keyword=args.dhm_keyword,
        usgs_radius_km=args.usgs_radius_km,
        usgs_hours=args.usgs_hours,
        skip_dhm=args.skip_dhm,
        skip_glofas=args.skip_glofas,
        skip_imerg=args.skip_imerg,
        skip_webcam=args.skip_webcam,
        webcam_name=args.webcam_name,
        webcam_width=args.webcam_width,
        image_dir=args.image_dir,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print()
    print(f"Wrote JSON: {output.resolve()}")
    print("Source status:")
    for name, result in payload["sources"].items():
        print(f"  {name}: {result.get('status')}")


if __name__ == "__main__":
    main()
