from slugify import slugify


def test_simple():
    assert slugify("Hello") == "hello"
