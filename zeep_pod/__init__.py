"""ZEEP Pod application package.

``app.py`` remains the process composition root while domain logic is moved
into focused modules under this package.  Modules in this package must not
start threads, open serial ports, or mutate production data at import time.
"""
