"""Tests de la géométrie de l'overlay (pur, sans natif)."""

from optcgsim_haki.overlay.geometry import (
    Rect,
    WindowFollower,
    compute_overlay_frame,
    parse_window_bounds,
)


def _win(owner, x, y, w, h, layer=0):
    return {
        "kCGWindowOwnerName": owner,
        "kCGWindowLayer": layer,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
    }


# --- compute_overlay_frame : conversion Quartz (haut-gauche) -> Cocoa (bas-gauche) ---

def test_frame_flips_y_origin():
    game = Rect(100, 50, 800, 600)        # Quartz : 50 px depuis le HAUT
    f = compute_overlay_frame(game, screen_h=1000)
    assert (f.x, f.w, f.h) == (100, 800, 600)
    assert f.y == 1000 - 50 - 600          # = 350, bas de la frame depuis le BAS de l'écran


def test_frame_top_of_screen_maps_high():
    # Fenêtre collée en haut (y=0) -> en Cocoa son bas = screen_h - h (vers le haut).
    f = compute_overlay_frame(Rect(0, 0, 400, 300), screen_h=900)
    assert f.y == 600


def test_frame_inset_shrinks_all_edges():
    f = compute_overlay_frame(Rect(100, 50, 800, 600), screen_h=1000, inset=10)
    assert f.x == 110 and f.w == 780 and f.h == 580
    assert f.y == 1000 - 50 - 600 + 10     # 360


# --- parse_window_bounds : sélection de la fenêtre du jeu ---

def test_picks_matching_owner():
    wins = [_win("Finder", 0, 0, 100, 100), _win("OPTCGSim", 10, 20, 1280, 720)]
    r = parse_window_bounds(wins, "OPTCGSim")
    assert r == Rect(10, 20, 1280, 720)


def test_owner_match_is_case_insensitive_substring():
    assert parse_window_bounds([_win("OPTCGSim Player", 0, 0, 50, 50)], "optcgsim") is not None


def test_ignores_non_zero_layer():
    # Couche != 0 = overlay/menu système -> ignoré.
    assert parse_window_bounds([_win("OPTCGSim", 0, 0, 800, 600, layer=25)], "OPTCGSim") is None


def test_picks_largest_when_multiple():
    wins = [
        _win("OPTCGSim", 0, 0, 200, 100),     # petite fenêtre auxiliaire
        _win("OPTCGSim", 5, 5, 1280, 720),    # fenêtre de jeu
    ]
    assert parse_window_bounds(wins, "OPTCGSim") == Rect(5, 5, 1280, 720)


def test_none_when_absent_or_malformed():
    assert parse_window_bounds([], "OPTCGSim") is None
    assert parse_window_bounds([{"kCGWindowOwnerName": "OPTCGSim"}], "OPTCGSim") is None  # pas de bounds
    assert parse_window_bounds([_win("OPTCGSim", 0, 0, 0, 0)], "OPTCGSim") is None        # aire nulle


# --- WindowFollower : suivi de la fenêtre du jeu (déplacement, fermeture, restart) ---

GAME = Rect(100, 50, 800, 600)
H = 1000.0


def test_follower_first_tick_applies_frame():
    f = WindowFollower()
    a = f.tick(GAME, H)
    assert a.frame == compute_overlay_frame(GAME, H)
    assert a.show is None  # déjà visible au lancement


def test_follower_idle_when_nothing_moved():
    f = WindowFollower()
    f.tick(GAME, H)
    assert f.tick(GAME, H).is_noop  # pas de setFrame à chaque tick


def test_follower_moves_with_game_window():
    f = WindowFollower()
    f.tick(GAME, H)
    moved = Rect(GAME.x + 200, GAME.y, GAME.w, GAME.h)
    a = f.tick(moved, H)
    assert a.frame == compute_overlay_frame(moved, H)


def test_follower_subpixel_jitter_is_ignored():
    f = WindowFollower(epsilon=0.5)
    f.tick(GAME, H)
    jitter = Rect(GAME.x + 0.3, GAME.y, GAME.w, GAME.h)
    assert f.tick(jitter, H).is_noop


def test_follower_tolerates_transient_miss():
    # Un raté ponctuel de Quartz ne doit pas faire clignoter l'overlay.
    f = WindowFollower(miss_grace=3)
    f.tick(GAME, H)
    assert f.tick(None, H).is_noop
    assert f.tick(None, H).is_noop


def test_follower_hides_when_game_closes():
    f = WindowFollower(miss_grace=3)
    f.tick(GAME, H)
    f.tick(None, H); f.tick(None, H)
    assert f.tick(None, H).show is False       # grace atteinte -> masquer
    assert f.tick(None, H).is_noop             # une seule fois, pas à chaque tick


def test_follower_reshows_and_realigns_on_restart():
    f = WindowFollower(miss_grace=1)
    f.tick(GAME, H)
    f.tick(None, H)                            # sim fermé -> hide
    restarted = Rect(300, 80, 1280, 720)       # relancé ailleurs
    a = f.tick(restarted, H)
    assert a.show is True
    assert a.frame == compute_overlay_frame(restarted, H)


def test_follower_reshow_without_move_if_same_position():
    f = WindowFollower(miss_grace=1)
    f.tick(GAME, H)
    f.tick(None, H)                            # hide
    a = f.tick(GAME, H)                        # réapparaît au même endroit
    assert a.show is True and a.frame is None  # ré-afficher suffit, la frame n'a pas changé


def test_follower_missing_screen_height_counts_as_miss():
    f = WindowFollower(miss_grace=1)
    f.tick(GAME, H)
    assert f.tick(GAME, None).show is False


def test_follower_force_reapply():
    f = WindowFollower()
    f.tick(GAME, H)
    f.force_reapply()                          # menu « Recaler sur le jeu »
    assert f.tick(GAME, H).frame == compute_overlay_frame(GAME, H)
