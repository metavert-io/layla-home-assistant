# Layla for Home Assistant

[![Validate](https://github.com/metavert-io/layla-home-assistant/actions/workflows/validate.yml/badge.svg)](https://github.com/metavert-io/layla-home-assistant/actions/workflows/validate.yml)
[![Tests](https://github.com/metavert-io/layla-home-assistant/actions/workflows/tests.yml/badge.svg)](https://github.com/metavert-io/layla-home-assistant/actions/workflows/tests.yml)
[![HACS custom repository](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)

A custom [Home Assistant](https://www.home-assistant.io) integration for [Layla](https://layla.eco) room sensors,
the noise, occupancy and air-quality sensors LaylaElectric makes for short-term rentals. It reads your sensors from
Layla's cloud and shows them in Home Assistant, so you can graph them, put them on dashboards and use them in
automations.

> **Unofficial.** This project isn't made, endorsed or supported by LaylaElectric. "Layla" is LaylaElectric's name;
> it's used here only to say what the integration works with.

## What it shows

Each Layla sensor becomes a device in Home Assistant with:

- **Readings**: noise (dB), people (low and high estimates), temperature, humidity, air quality index, VOCs,
  mold risk and power, plus Wi-Fi signal and network quality as diagnostics. A sensor is only created for the
  readings the device reports.
- **Alarms**, as on/off sensors that are on while the alarm is active, including while it's snoozed in Layla
  (snoozing only mutes Layla's notifications; the sensor then has a `snoozed` attribute): smoke, carbon monoxide,
  noise, too many people and security by default, plus any other alarm turned on for the device in Layla
  (quiet-hours noise, air quality, CO2, VOCs, mold, party detection) or that goes off. You can choose which ones
  (see [Options](#options)).
- **Active alarms**: how many of the device's alarms are active, with their names, when each started and which
  are snoozed as attributes.
- **Online** (diagnostic): whether the sensor has reported recently.

Each entity also carries a `layla_reading`, `layla_alarm` or `layla_online` attribute and a `layla_device`
attribute, so templates and other tools can find Layla's entities without the entity registry.

## Requirements

- Home Assistant 2026.10 or later.
- A Layla account that signs in with an email and password (see [Known gaps](#known-gaps)).

## Install

### With HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=metavert-io&repository=layla-home-assistant&category=integration)

Or by hand:

1. In Home Assistant, open **HACS**, then the **⋮** menu → **Custom repositories**.
2. Add `https://github.com/metavert-io/layla-home-assistant` with the type **Integration**.
3. Find **Layla** in HACS, select **Download**, then restart Home Assistant.

### By hand

1. Download the latest [release](https://github.com/metavert-io/layla-home-assistant/releases) and copy its
   `custom_components/layla` folder into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.

## Set up

**Settings → Devices & services → Add integration → Layla**, then sign in with the email and password you use in
the Layla app.

- The password is used once, to sign in, and isn't stored. Sign-in uses SRP through Layla's own sign-in service
  (the same AWS Cognito user pool the Layla web app uses), so the password itself isn't sent either.
- Home Assistant keeps only the session's refresh token (and your email, to show which account it is). If Layla
  ends the session, Home Assistant asks you to sign in again.
- One Layla account can be added once; to add another account, add the integration again.

## Options

**Settings → Devices & services → Layla → Configure.** Saving reloads the integration.

| Option | Default | What it does |
|---|---|---|
| Update every | 2 minutes (1–60) | How often Layla is asked for new readings. Each update is one request for your account's settings, one for your properties and one per property. Layla's sensors report about every 5 minutes. |
| Online if it reported within | 60 minutes (5–1440) | Layla doesn't say whether a sensor is connected, so it counts as online if it sent a reading this recently. |
| Properties | All | Which of the account's properties to include. Leave all unticked for every property, including ones added later. Devices in properties you leave out are removed when you save. |
| Put the property's name in front of each device's name | Off | For accounts with several properties whose sensors share names ("Living room"). Entity IDs don't change. |
| Readings | All | Which readings get a sensor. Turning one off removes its entities. |
| Alarm sensors to always create | Smoke, carbon monoxide, noise, too many people, security | Alarm sensors created for every device. One you untick is removed when you save, unless the next option keeps it. |
| Also create sensors for the alarms turned on for each device in Layla, and for any alarm that fires | On | Adds the alarms enabled in each device's Layla settings, and any alarm that goes off. Once a device has a sensor for an alarm it keeps it, so its name, area and automations survive. Turn it off to get exactly the alarms chosen above. |

The temperature comes in the unit set in your Layla account. To show it in the other unit, change the sensor's
unit of measurement in its settings in Home Assistant.

### Advanced: where it signs in

The sign-in form has a collapsed **Advanced** section with Layla's **API address**, **sign-in region**, **user pool
ID** and **app client ID**. The defaults are the ones Layla's web app uses, and you don't need to change them. They're there
in case Layla gives you a client of your own or changes theirs before this integration is updated. Values you leave
at their defaults aren't stored, so a later release can update them.

## Privacy

- Layla's sensors don't record sound or pictures: noise is a level in decibels and occupancy is an estimate.
  This integration only sees what Layla's API reports.
- It only reads. It never changes anything on Layla: no AC control, no alarm settings, no snoozing.
- It talks only to Layla's cloud (`api.laylaelectric.com` and Layla's AWS Cognito sign-in service) and stores only
  the refresh token and your email in Home Assistant.
- Its [diagnostics](https://www.home-assistant.io/integrations/diagnostics/) leave
  out your email, the token, and every device's and property's name, ID, MAC address and serial number, so you can
  attach them to an issue.

## How it works

On each update it calls Layla's REST API:

- `GET /v1/users/self`, for the temperature unit (readings come in the unit the account is set to at the time);
- `GET /v1/properties`;
- for each chosen property, `GET /v1/devices?property_id=…&fields=latest_values,alarm_event_counts,in_alarm,active_alarms,mode`,
  the same request Layla's web app makes.

If one property's request fails, that property's devices show as unavailable until it answers again, and the
others carry on. Nothing is removed because Layla's answer left it out: entities and devices go only when you
change the options.

A few things the [API documentation](https://api-doc-357ca.web.app/) doesn't say, found against real devices:
`/v1/devices/all` leaves out readings, alarms and status and ignores `fields=`; reading times are the property's
local time without a time zone, so they're read in the property's `timezone`; there's no connection status; ranges
come back as 0/0 when there's no range; and there's a `party_detection` alarm.

## Known gaps

- **Google or Apple sign-in:** those Layla accounts have no password, so they can't sign in here.
- **Two-step verification** isn't supported yet.
- **No control:** it doesn't change AC settings, alarms or anything else on Layla.
- **Online** is a guess from the last report, since Layla's API has no connection status.

## Problems and ideas

[Open an issue](https://github.com/metavert-io/layla-home-assistant/issues). For a bug, attach the integration's
diagnostics (**Settings → Devices & services → Layla → ⋮ → Download diagnostics**) and the relevant lines from the
Home Assistant log. Check both for anything you'd rather not share before you post.

## Development

```sh
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

The tests run against the Home Assistant version pinned in `requirements_test.txt`, with sign-in and Layla's API
faked; they need no Layla account. `tests/test_model.py` (parsing Layla's answers) also runs without Home Assistant:
`python3 -m unittest tests.test_model`.

## License

[MIT](LICENSE). Not affiliated with LaylaElectric.
