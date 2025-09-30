# Home Assistant ENTSO-e Data

Custom component for Home Assistant that retrieves electricity generation mix and total load forecasts from the [ENTSO-e Transparency Platform](https://transparency.entsoe.eu/).

The integration exposes the latest generation output per production category together with total load forecasts for the selected bidding zone. Each sensor includes a full timeline for the returned dataset, making it easy to build dashboards or automations that respond to upcoming changes in supply and demand.

## Features

- Generation mix sensors for every available production category and a total generation sensor with upcoming forecast values in the attributes.
- Load forecast sensors that report the current, next hour, minimum, maximum and average load along with the complete forecast timeline.
- Optional toggles during setup to enable or disable the generation and load sensor groups depending on your needs or API quota.

## Requirements

You need an ENTSO-e Restful API key for this integration. To request the API key, register on the [Transparency Platform](https://transparency.entsoe.eu/) and send an email to transparency@entsoe.eu with “Restful API access” in the subject line. Include the email address you used for registration in the message body.

## Installation

### HACS

Search for "ENTSO-e" when adding HACS integrations and add "ENTSO-e Data".

Or use this link to go directly there: [![Or use this link.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JaccoR&repository=hass-entso-e&category=integration)

Restart Home Assistant and add the integration through Settings.

### Manual

Download this repository and place the contents of `custom_components` in the `custom_components` folder of your Home Assistant installation. Restart Home Assistant and add the integration through Settings.

## Configuration

1. Go to **Settings → Devices & Services**.
2. Click **+ Add integration**.
3. Search for "ENTSO-e" and select **ENTSO-e Data**.
4. Enter your ENTSO-e API key and choose the bidding zone you want to monitor.
5. Optionally toggle the generation mix and load forecast sensor groups.

The sensors are created automatically after the configuration flow completes.

## Sensors

### Generation mix (MW)

- Total generation output for the selected bidding zone.
- Individual production category sensors (for example wind onshore, solar, hydro, etc.) with next-hour forecasts in the attributes.

### Load forecast (MW)

- Current and next hour load forecast sensors.
- Minimum, maximum and average forecast sensors.
- Each sensor exposes the full timeline and relevant timestamps in the attributes.

## ApexCharts example

You can visualise the timeline data using the [ApexCharts Card](https://github.com/RomRider/apexcharts-card). Below is a minimal example for the total load forecast sensor:

```
type: custom:apexcharts-card
header:
  show: true
  title: Total load forecast
series:
  - entity: sensor.total_load_forecast
    data_generator: |
      return Object.entries(entity.attributes.timeline).map(([time, value]) => {
        return [new Date(time), value];
      });
```

## Updates

The integration is in active development and may receive frequent updates. If you encounter issues after updating, please reinstall the integration through HACS or reapply the manual installation steps.
