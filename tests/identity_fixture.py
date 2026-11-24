"""Local delivery fixture exercises the same two-factor protocol as the HTTP routes."""

from platform_core import identity


def verified_password(store, token, name, old, new):
    received = []
    store.code_senders["email"] = lambda address, code: received.append(code)
    target = "test@example.invalid"
    first = identity.request_code(
        store,
        {
            "purpose": "bind",
            "channel": "email",
            "destination": target,
            "currentPassword": old,
        },
        token=token,
    )
    identity.finish(
        store,
        {"purpose": "bind", "challenge": first["challenge"], "code": received.pop()},
        token=token,
    )
    second = identity.request_code(
        store, {"purpose": "password", "channel": "email", "username": name}
    )
    return identity.finish(
        store,
        {
            "purpose": "password",
            "challenge": second["challenge"],
            "code": received.pop(),
            "newPassword": new,
        },
    )
