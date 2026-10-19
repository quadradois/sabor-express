import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def dono(client, db):
    user = get_user_model().objects.create_user("dono", password="x")
    client.force_login(user)
    return user
