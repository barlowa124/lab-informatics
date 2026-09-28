"""Wire protocol constants shared by the simulator and the driver.

ASCII, newline-terminated, SCPI-flavored. Requests are queries (ending in ?)
or commands. Responses are single lines. Errors live in a device error
register read with SYSTem:ERRor?.
"""

IDENT_RESPONSE = "LABLINK,THRIVE-1000,BIOREACTOR,1.4.2"

CHANNELS = {
    "TEMP": {"unit": "degC", "lo": 4.0, "hi": 45.0},
    "PH": {"unit": "pH", "lo": 5.0, "hi": 9.0},
    "DO": {"unit": "percent", "lo": 0.0, "hi": 100.0},
    "AGIT": {"unit": "rpm", "lo": 0.0, "hi": 1500.0},
    "WEIGHT": {"unit": "g", "lo": 0.0, "hi": 5000.0},
}

SETTABLE = {"TEMP", "PH", "DO", "AGIT"}
