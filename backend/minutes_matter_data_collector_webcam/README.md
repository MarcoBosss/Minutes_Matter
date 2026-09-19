# Minutes Matter data collector

A small Python program for your `minutes_matter` hackathon project.

It takes:

```text
latitude
longitude
```

and writes a JSON file containing environmental data plus a live glacier webcam snapshot from:

- Open-Meteo
- USGS Earthquake Catalog
- Nepal DHM
- Copernicus GloFAS
- NASA IMERG Early Run
- Foto-Webcam.eu Hintereisferner 1 live/current glacier image

## Files

```text
collector.py
requirements.txt
.env.example
```

## Install

Python 3.11+ recommended.

```bash
pip install -r requirements.txt
```

## Quickest working test

Open-Meteo and USGS require no keys.

Nepal DHM is scraped from its public realtime page.

GloFAS and IMERG need credentials, so skip them on your first run:

```bash
python collector.py \
  --lat 28.2774 \
  --lon 85.3777 \
  --skip-glofas \
  --skip-imerg
```

This creates:

```text
environment_state.json
```

## Full run

```bash
python collector.py \
  --lat 28.2774 \
  --lon 85.3777 \
  --output environment_state.json
```

If a source is unavailable or not configured, the whole program does not crash.
That source gets a status such as:

```json
{
  "status": "not_configured"
}
```

## NASA IMERG

Create a free NASA Earthdata account/token and set:

```text
NASA_EARTHDATA_TOKEN=your_token_here
```

You can put it in a local `.env` file.

Do not commit `.env`.

## GloFAS

Copernicus GloFAS uses the Climate Data Store API.

You need:

1. a free CDS account
2. to accept the GloFAS dataset terms
3. a valid `~/.cdsapirc`

Typical config:

```yaml
url: https://cds.climate.copernicus.eu/api
key: YOUR_PERSONAL_ACCESS_TOKEN
```

## Nepal DHM

The script reads the public realtime stream-flow webpage and tries to filter rows
using a keyword.

Default:

```text
Rasuwa
```

Override it like this:

```bash
python collector.py \
  --lat 28.2774 \
  --lon 85.3777 \
  --dhm-keyword "Rasuwa"
```

Once you identify a specific DHM station name or index, use that instead.

## Output shape

```json
{
  "target": {
    "latitude": 28.2774,
    "longitude": 85.3777
  },
  "sources": {
    "open_meteo": {},
    "usgs_earthquakes": {},
    "nepal_dhm": {},
    "copernicus_glofas": {},
    "nasa_imerg": {}
  },
  "observations_for_gemini": {
    "weather": {},
    "seismic": {},
    "river": {},
    "glofas": {},
    "satellite_precipitation": {}
  }
}
```

For Gemini, use:

```python
payload["observations_for_gemini"]
```

instead of sending the full raw source payload.

## Useful commands

Fast/no-auth-ish:

```bash
python collector.py --lat 28.2774 --lon 85.3777 --skip-glofas --skip-imerg
```

Skip DHM too:

```bash
python collector.py --lat 28.2774 --lon 85.3777 --skip-dhm --skip-glofas --skip-imerg
```

Custom output:

```bash
python collector.py \
  --lat 28.4043 \
  --lon 85.6469 \
  --output upstream.json \
  --skip-glofas \
  --skip-imerg
```

## Suggested location for `minutes_matter`

Put these files somewhere like:

```text
minutes_matter/
  backend/
    data_collector/
      collector.py
      requirements.txt
      .env.example
```

Then either run the script as a subprocess or import `collect()` directly from your backend.


## Live glacier image

The collector now also downloads the current image from:

```text
https://www.foto-webcam.eu/webcam/hintereisferner1/
```

using the site's documented stable current-image URL:

```text
https://www.foto-webcam.eu/webcam/hintereisferner1/current/720.jpg
```

By default, each run creates:

```text
images/
  hintereisferner1_YYYYMMDDTHHMMSSZ.jpg
  hintereisferner1_latest.jpg
```

The JSON also contains metadata under:

```json
"sources": {
  "foto_webcam_glacier": {
    "status": "ok",
    "data": {
      "latest_image_path": "images/hintereisferner1_latest.jpg"
    }
  }
}
```

and a compact reference under:

```json
"observations_for_gemini": {
  "glacier_webcam": {
    "latest_image_path": "images/hintereisferner1_latest.jpg"
  }
}
```

### Run with the webcam

```bash
python collector.py \
  --lat 28.2774 \
  --lon 85.3777 \
  --skip-glofas \
  --skip-imerg
```

The webcam is enabled by default.

To disable it:

```bash
python collector.py \
  --lat 28.2774 \
  --lon 85.3777 \
  --skip-glofas \
  --skip-imerg \
  --skip-webcam
```

### Important location note

`Hintereisferner 1` is located in the Austrian Alps at approximately:

```text
46.7959, 10.7828
3245 m elevation
```

It is **not** a camera in Nepal. Use it as a real live glacier-vision input / proof
of concept, not as visual evidence of conditions at Rasuwagadhi.

For publication or display, preserve the required attribution to
`www.foto-webcam.eu` and link back to the webcam page.
