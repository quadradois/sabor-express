def test_anonimo_vai_para_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.url.startswith("/entrar/")


def test_dono_ve_inicio(client, dono):
    r = client.get("/")
    assert r.status_code == 200
    assert "Sabor Express" in r.content.decode()
