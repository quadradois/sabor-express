from decimal import Decimal as D
import pytest
from web.templatetags.formato import quantidade

@pytest.mark.parametrize("q,u,esperado", [
    (D("1800"), "g", "1,8 kg"), (D("4500"), "g", "4,5 kg"), (D("360"), "g", "360 g"),
    (D("157.5"), "g", "157,5 g"), (D("2700"), "mL", "2,7 L"), (D("90"), "mL", "90 mL"),
    (D("30"), "un", "30 un"), (D("1957.5"), "g", "1,958 kg"),
])
def test_quantidade(q, u, esperado):
    assert quantidade(q, u) == esperado

@pytest.mark.parametrize("q,esperado", [(D("999.9996"), "1 kg"), (D("1000"), "1 kg")])
def test_quantidade_arredonda_antes_de_escolher_unidade(q, esperado):
    assert quantidade(q, "g") == esperado
