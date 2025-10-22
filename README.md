# ENTSO-e Data for Home Assistant

This repository contains a Home Assistant custom integration that retrieves electricity generation mix and total load forecasts from the [ENTSO-e Transparency Platform](https://transparency.entsoe.eu/). It is designed to give you a clean, reliable snapshot of upcoming supply and demand so you can build dashboards or automations that react to the grid in real time.

## At a glance

| Capability | Description |
| --- | --- |
| Generation mix sensors | Individual production categories (e.g. solar, onshore wind, hydro) plus a combined total generation sensor with forecast values in the attributes. |
| Load forecast sensors | Current, next hour, minimum, maximum, and average load forecasts, each exposing the full forecast timeline. |
| Guided setup | Optional toggles during the configuration flow let you enable only the sensor groups you need, keeping API usage under control. |

## Prerequisites

An ENTSO-e RESTful API key is required. Request one by registering on the [Transparency Platform](https://transparency.entsoe.eu/) and emailing `transparency@entsoe.eu` with the subject **“RESTful API access”**. Include the email address used during registration in the body of your message. The integration will not function without a valid key.

## Installation options

### Via HACS (recommended)

1. Open **HACS → Integrations** and search for **“ENTSO-e”**.
2. Select **ENTSO-e Data** and follow the prompts to install it.
3. Alternatively, jump straight to the listing using this badge: [![Open the repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jorik41&repository=ENTSO-e&category=integration)
4. Restart Home Assistant after installation to load the new integration.

### Manual installation

1. Download the latest release from this repository.
2. Copy the `custom_components/entsoe_data` directory into your Home Assistant `custom_components` folder.
3. Restart Home Assistant to register the integration.

## Configuration flow

Once the integration files are installed, complete the setup directly within Home Assistant:

1. Navigate to **Settings → Devices & Services**.
2. Click **+ Add integration** and search for **“ENTSO-e”**.
3. Choose **ENTSO-e Data** and enter your ENTSO-e API key.
4. Pick the bidding zone you want to monitor.
5. Decide whether to create generation sensors, load sensors, or both.

All selected sensors will be created automatically when the flow finishes. You can revisit the configuration later to update options or reauthenticate.

## Sensor reference

### Generation mix sensors (MW)

Each category sensor reports the current measured output and exposes the full forecast timeline through the `timeline` attribute. By default, entity IDs follow the pattern `entsoe_data.<key>` (for example `entsoe_data.generation_total_generation` for the aggregated total output sensor).

### Load forecast sensors (MW)

Load sensors provide the present and next hour values along with minimum, maximum, and average forecasts. They also expose the full timeline through their attributes. Day-ahead sensors use keys such as `entsoe_data.load_current` and `entsoe_data.load_next`; other horizons append `_week_ahead`, `_month_ahead`, or `_year_ahead` as appropriate.

## Example ApexCharts configuration

Visualise the forecast timeline using the [ApexCharts Card](https://github.com/RomRider/apexcharts-card). The snippet below plots the day-ahead total load forecast entity (default ID `entsoe_data.load_current`):

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Total load forecast
series:
  - entity: entsoe_data.load_current
    data_generator: |
      return Object.entries(entity.attributes.timeline).map(([time, value]) => {
        return [new Date(time), value];
      });
```

Replace the entity ID with the sensor you want to plot. Any entity exposing a `timeline` attribute works with the same pattern.

## Keeping the integration up to date

The integration is under active development. When a new version is released:

- **HACS installations:** update from the HACS UI and restart Home Assistant when prompted.
- **Manual installations:** download the latest files, replace the existing `custom_components/entsoe_data` directory, and restart Home Assistant.

If an update does not apply cleanly or you encounter issues, reinstalling the integration usually resolves the problem.

## Data handling and privacy

- Your ENTSO-e API key is stored securely in Home Assistant's configuration entry storage and is only used to authenticate requests made by the integration.
- All data is fetched directly from the ENTSO-e Transparency Platform over HTTPS using the official REST interface exposed by ENTSO-e.
- The integration does not transmit or store any personal information beyond the API key required for authentication.

## AI-generated content disclaimer

This documentation has been modified and written with the assistance of artificial intelligence tools.
