"""Identify the connecting peer for local login attempt limits."""

from fastapi import Request


def client_key(request: Request) -> str:
    """Use the ASGI peer rather than trusting forwarding headers in requests."""
    return request.client.host if request.client is not None else "unknown-client"
