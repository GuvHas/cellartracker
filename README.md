# Disclaimer
This is an personal attempt at creating an integration to CellarTracker to Home Assistant, I am in no way affiliated or connected to CellarTracker! LLC.

The aim is to fetch the data from CellarTracker and display it in a nice way in a dashboard.

Creates one sensor for the whole inventory, with the information per bottle (location, country, appellation, producer etc) as attributes,
Creates two more senors, for total value and total number of bottles.

"CellarTracker!" is a trademark of CellarTracker! LLC

# Requirements
- Having an account at Cellar Tracker - https://cellartracker.com
- HACS: Home Assistant Community Store - https://hacs.xyz/


# Installation
Manually add the repository to HACS 

- **Repository:** https://github.com/GuvHas/cellar_tracker
- **Category:** Integration

# Configuration:
After adding to HACS, add the integration under Settings / Devices & Services.
Then fill out the configuration using your CellarTracker! username and password.
Optionally change the time between refreshes (Default 1 hour)
