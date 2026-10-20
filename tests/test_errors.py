from hermes_cua_spaces.errors import NotSignedInError, SpaceNotFoundError, UnsupportedSpaceError, explain, CuaSpacesError


def _exc(kind: str, msg: str = "boom"):
    return type(kind, (Exception,), {})(msg)


def test_not_signed_in_says_what_to_run():
    e = explain(_exc("Unauthenticated", "token abc123 rejected"))
    assert isinstance(e, NotSignedInError)
    assert "cua auth login" in str(e)
    assert "abc123" not in str(e)  # never echo what could be a token


def test_not_found_names_the_space_and_next_step():
    e = explain(_exc("NotFound"), space="mybox")
    assert isinstance(e, SpaceNotFoundError)
    assert "'mybox'" in str(e) and "cua spaces ls" in str(e)


def test_capability_missing():
    assert isinstance(explain(_exc("CapabilityMissing", "no shell")), UnsupportedSpaceError)


def test_unknown_kind_still_readable():
    e = explain(_exc("Weird", "first line\nsecond line"), space="x")
    assert "first line" in str(e) and "second line" not in str(e)


def test_passthrough():
    original = CuaSpacesError("already plain")
    assert explain(original) is original
