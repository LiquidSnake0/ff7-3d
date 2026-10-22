"""Projection du GTE avec la caméra d'un écran, telle que FieldCalcWorldToScreenPos l'emploie.

SetRotMatrix / SetTransMatrix(&lookAt), SetGeomOffset(0, 0), SetGeomScreen(zoom) puis RotTransPers :
    c  = (R · v) >> 12 + t        (espace caméra)
    sx = H · c.x / c.z,  sy = H · c.y / c.z,  avec H = zoom
Les coordonnées écran obtenues sont dans le même repère que les tuiles du décor (origine au centre).
La case d'OT d'un point vaut c.z / 4 (moyenne des SZ divisée par 4 pour un polygone).
"""
import numpy as np


def vers_camera(camera, points):
    """points : (N, 3) coordonnées du monde -> (N, 3) espace caméra, en unités GTE."""
    r = np.array(camera.axes, dtype=np.float64)
    t = np.array(camera.translation, dtype=np.float64)
    p = np.asarray(points, dtype=np.float64)
    return p @ r.T / 4096.0 + t


def projeter(camera, points):
    """-> (N, 2) coordonnées écran et (N,) z caméra."""
    c = vers_camera(camera, points)
    z = c[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        sx = camera.zoom * c[:, 0] / z
        sy = camera.zoom * c[:, 1] / z
    return np.stack([sx, sy], axis=1), z


def id_vers_z(profondeur_id):
    """Case d'OT -> z caméra approché (pas de 4)."""
    return 4.0 * np.asarray(profondeur_id, dtype=np.float64)


def rayon(camera, sx, sy):
    """Direction (espace caméra) du rayon qui passe par le point écran (sx, sy), pour z = 1."""
    return np.stack([np.asarray(sx, float) / camera.zoom, np.asarray(sy, float) / camera.zoom,
                     np.ones_like(np.asarray(sx, float))], axis=-1)
