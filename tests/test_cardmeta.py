"""Tests du parseur de métadonnées de cartes (OPBounty.pck)."""

import json

from optcgsim_haki.cardmeta import _extract_object, iter_pck_objects, parse_pck_cards


def _obj(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def test_extract_object_balances_inner_braces_in_strings():
    s = 'X{"a":"has {curly} braces","b":1}Y'
    start = s.index("{")
    assert _extract_object(s, start) == '{"a":"has {curly} braces","b":1}'


def test_iter_pck_objects_recovers_cards_with_braces_in_description():
    # Régression : une description contenant des accolades de trait ({Red-Haired Pirates})
    # faisait échouer l'ancien regex `[^{}]*` -> la carte était exclue de TOUTES les stats.
    rockstar = _obj(Number="OP16-018", CardType="Character", Name="Rockstar",
                    Description="[Once Per Turn] If your {Red-Haired Pirates} type Character...")
    plain = _obj(Number="OP16-017", CardType="Character", Name="Plain", Description="No braces")
    # Imbriqué dans un objet englobant (cas ST30/"groups"), qui ne doit PAS être capturé seul.
    data = '{"groups":[' + rockstar + ',' + plain + ']}'
    nums = {d["Number"] for d in iter_pck_objects(data)}
    assert nums == {"OP16-018", "OP16-017"}


def test_parse_pck_cards_inner_braces(tmp_path):
    rockstar = _obj(Number="OP16-018", CardType="Character", Name="Rockstar", Cost="1",
                    Counterplus="2000", Color="Red",
                    Description="[Once Per Turn] {Red-Haired Pirates} ...")
    pck = tmp_path / "OPBounty.pck"
    pck.write_bytes(("[" + rockstar + "]").encode("latin-1"))
    meta = parse_pck_cards(pck)
    assert "OP16-018" in meta
    m = meta["OP16-018"]
    assert m.name == "Rockstar"
    assert m.cost == 1
    assert m.counter == 2000
    assert m.colors == ["Red"]
