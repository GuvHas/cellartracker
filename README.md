# Disclaimer
This is an personal attempt at creating an integration to CellarTracker to Home Assistant, I am in no way affiliated or connected to CellarTracker! LLC.

The aim is to fetch the data from CellarTracker and display it in a nice way in a dashboard.

Creates two sensors, for total value and total number of bottles.

"CellarTracker!" is a trademark of CellarTracker! LLC

# Requirements
- Having an account at Cellar Tracker - https://cellartracker.com
- HACS: Home Assistant Community Store - https://hacs.xyz/


# Installation
Manually add the repository to HACS 

- **Repository:** https://github.com/GuvHas/cellartracker
- **Category:** Integration

# Configuration:
After adding to HACS, add the integration under Settings / Devices & Services.
Then fill out the configuration using your CellarTracker! username and password.
Optionally change the time between refreshes (Default 1 hour)

Add the index.html file to /config/www

# Example
<img width="772" height="606" alt="image" src="https://github.com/user-attachments/assets/8b19ec91-a1ff-48eb-870f-7eb00981e056" />
