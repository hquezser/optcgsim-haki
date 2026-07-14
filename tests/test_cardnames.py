"""Test de l'extraction des noms de cartes depuis un asset Unity synthétique."""

from optcgsim_haki.cardnames import extract_card_names, load_card_names


def _make_asset(tmp_path, entries):
    """Construit un faux resources.assets : pour chaque (id, name) -> id, id, name.

    Les chaînes sont séparées par des octets NUL (non imprimables), comme dans le vrai asset,
    pour que l'extraction de chaînes les retrouve consécutives.
    """
    parts = ["ButtonChoiceType.X"]
    for cid, name in entries:
        parts += [cid, cid, name]
    parts += ["Action.OP09-001"]
    blob = b"\x00\x00".join(p.encode() for p in parts)
    p = tmp_path / "resources.assets"
    p.write_bytes(blob)
    return p


def test_extract_card_names(tmp_path):
    asset = _make_asset(tmp_path, [
        ("OP09-001", "Shanks"),
        ("PRB01-001", "Sanji"),
        ("ST12-001", "Roronoa Zoro & Sanji"),
    ])
    names = extract_card_names(asset)
    assert names["OP09-001"] == "Shanks"
    assert names["PRB01-001"] == "Sanji"
    assert names["ST12-001"] == "Roronoa Zoro & Sanji"


def test_cache_roundtrip(tmp_path):
    asset = _make_asset(tmp_path, [("OP01-001", "Monkey D. Luffy")])
    cache = tmp_path / "names.json"
    first = load_card_names(asset, cache)
    assert cache.exists()
    # 2e appel : sert depuis le cache (asset supprimé -> doit quand même répondre).
    asset.unlink()
    second = load_card_names(asset, cache)
    assert first == second == {"OP01-001": "Monkey D. Luffy"}
