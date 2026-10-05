"""A single-process request limit; synchronous requests are never queued."""
from threading import BoundedSemaphore

SOLVE_SLOTS = BoundedSemaphore(5)
