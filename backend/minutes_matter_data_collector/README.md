# Minutes Matter data collector

A small Python program for your `minutes_matter` hackathon project.

It takes:

```text
latitude
longitude
```

and writes a JSON file containing environmental data from:

- Open-Meteo
- USGS Earthquake Catalog
- Nepal DHM
- Copernicus GloFAS
- NASA IMERG Early Run

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
