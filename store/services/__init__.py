"""Domain services.

Views and API endpoints stay thin: they validate input, call one of these
services and render a response.  Keeping ordering, locking and state
transitions here makes them testable and reusable by both interfaces.
"""
